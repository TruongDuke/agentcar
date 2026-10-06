"""Trợ lý chung — nhận câu ngoài miền xe. Không gọi mạng trong test."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.agent import Agent
from agentcar.assistant import CITIES, CloudAssistant
from agentcar.caps import load_caps
from agentcar.config import LLMSettings
from agentcar.lexicon import load_lexicon
from agentcar.llm import CloudPath
from agentcar.plan import Code, Verdict
from agentcar.safety import VehicleState as S

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
LEX = load_lexicon(CAPS)
WEATHER = {"temperature_2m": 30.4, "weather_code": 0, "relative_humidity_2m": 68}


class Client:
    def __init__(self, reply='{"reply":"Paris ạ."}'):
        self.reply, self.calls = reply, 0

    def complete(self, system, user, timeout_s):
        self.calls += 1
        return self.reply


def assistant(client=None, weather=lambda lat, lon: WEATHER, **kw):
    return CloudAssistant(client=client or Client(), settings=LLMSettings(),
                          weather=weather, clock=lambda: 0.0, **kw)


def test_answers_from_knowledge():
    assert assistant().answer("thủ đô nước Pháp là gì") == "Paris ạ."


@pytest.mark.parametrize("text", [
    "thời tiết hôm nay thế nào", "thoi tiet the nao", "dự báo thế nào",
    "ngoài trời bao nhiêu độ",
])
def test_weather_questions_skip_the_model(text):
    """Nhận ra bằng từ khoá thì khỏi gọi model: 3200ms xuống còn một lượt HTTP."""
    client = Client()
    answer = assistant(client).answer(text)
    assert client.calls == 0
    assert "30 độ" in answer and "trời quang" in answer


def test_weather_is_cached():
    calls = []

    def weather(lat, lon):
        calls.append(1)
        return WEATHER

    a = assistant(weather=weather)
    for _ in range(3):
        a.answer("thời tiết thế nào")
    assert len(calls) == 1


def test_stale_weather_is_better_than_nothing():
    """Hết hạn mà lấy lại không được thì dùng số cũ, đừng nói 'chưa lấy được'."""
    state = {"ok": True}

    def weather(lat, lon):
        return WEATHER if state["ok"] else None

    clock = [0.0]
    a = CloudAssistant(client=Client(), settings=LLMSettings(), weather=weather,
                       clock=lambda: clock[0], cache_ttl_s=10)
    a.answer("thời tiết thế nào")
    state["ok"], clock[0] = False, 999
    assert "30 độ" in a.answer("thời tiết thế nào")


def test_fetch_failure_says_so():
    a = assistant(weather=lambda lat, lon: None)
    assert "chưa lấy được" in a.answer("thời tiết thế nào")


def test_unknown_city_is_admitted():
    a = assistant(city="Paris")
    assert "chưa biết toạ độ" in a.answer("thời tiết thế nào")


def test_prose_answer_is_salvaged():
    """Model trả văn xuôi thay vì JSON thì vẫn dùng — thà nói còn hơn im lặng."""
    assert assistant(Client("Paris ạ, thủ đô nước Pháp.")).answer("thủ đô Pháp") \
        == "Paris ạ, thủ đô nước Pháp."


def test_broken_model_returns_nothing():
    assert assistant(Client("{}")).answer("câu gì đó") is None


def test_model_error_is_swallowed():
    class Boom:
        def complete(self, *a, **kw):
            raise OSError("mất mạng")

    assert assistant(Boom()).answer("câu gì đó") is None


def test_every_city_has_coordinates():
    for city, coords in CITIES.items():
        assert len(coords) == 2 and all(isinstance(c, float) for c in coords)


# ------------------------------------------------------------------ nối vào agent
def car_agent(handler):
    class Cloud:
        def complete(self, system, user, timeout_s):
            return '{"route":"assistant"}'

    return Agent(CAPS, LEX, handlers={"assistant": handler},
                 llm=CloudPath(CAPS, LEX, Cloud(), LLMSettings()))


def test_routed_question_is_answered_and_spoken():
    turn = car_agent(assistant()).handle("thủ đô nước Pháp là gì", S())
    assert turn.verdict == Verdict.REPLY
    assert turn.results[0].target == "assistant" and turn.tts == "Paris ạ."


def test_handler_failure_is_never_silent():
    """Giao rồi mà bên kia không trả lời được thì PHẢI nói một câu."""
    class Mute:
        def answer(self, text):
            return None

    turn = car_agent(Mute()).handle("câu gì đó lạ", S())
    assert turn.results[0].code == Code.NO_ANSWER
    assert turn.tts == "Em chưa trả lời được câu này ạ."


def test_car_commands_never_reach_the_assistant():
    class Loud:
        def __init__(self):
            self.called = False

        def answer(self, text):
            self.called = True
            return "không nên tới đây"

    handler = Loud()
    agent = car_agent(handler)
    assert agent.handle("bật điều hòa", S()).verdict == Verdict.OK
    assert not handler.called


def test_model_cannot_misuse_the_weather_tool():
    """Model chỉ có một tool nên hay dùng bừa: 'giá vàng hôm nay' từng được trả lời
    bằng thời tiết."""
    a = assistant(Client('{"tool":"weather"}'))
    assert a.answer("giá vàng hôm nay") is None
    assert "30 độ" in a.answer("thời tiết thế nào")


# ------------------------------------------------------------------ lọc chữ nước ngoài
@pytest.mark.parametrize("raw,expected", [
    ("Em chưa cập nhật giá vàng实时, anh/chị xem app ngân hàng ạ.",
     "Em chưa cập nhật giá vàng, anh/chị xem app ngân hàng ạ."),
    ("Thủ đô nước Pháp là Paris ạ.", "Thủ đô nước Pháp là Paris ạ."),
    ("Đèn viền màu xanh ạ。", "Đèn viền màu xanh ạ"),
])
def test_foreign_characters_are_stripped(raw, expected):
    """Câu này sẽ được ĐỌC TO — chữ Hán lẫn vào là nghe hỏng."""
    from agentcar.llm import clean_speech
    assert clean_speech(raw) == expected


def test_mostly_foreign_text_is_rejected():
    """Mất quá nhiều chữ thì bỏ hẳn, thà nói 'chưa trả lời được'."""
    from agentcar.llm import clean_speech
    assert clean_speech("天气很好，今天不错") is None


def test_assistant_output_is_filtered():
    assert assistant(Client('{"reply":"Giá vàng实时 chưa có ạ."}')).answer("giá vàng") \
        == "Giá vàng chưa có ạ."
