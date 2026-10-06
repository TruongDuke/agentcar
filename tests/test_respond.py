"""Câu trả lời tiếng Việt — ghép từ template, không dùng mô hình sinh."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import caps_theo

from agentcar.agent import Agent
from agentcar.caps import load_caps
from agentcar.evaluate import load_cases
from agentcar.lexicon import load_lexicon
from agentcar.plan import RawCommand, Verdict
from agentcar.resolve import resolve
from agentcar.respond import Responder
from agentcar.safety import VehicleState as S
from helpers import minimal_raw

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
LEX = load_lexicon(CAPS)
SAY = Responder(CAPS, LEX)


def speak(text: str, state: S | None = None, caps=None) -> str:
    agent = Agent(caps or CAPS, LEX)
    return agent.handle(text, state or S()).tts


@pytest.mark.parametrize("text,expected", [
    ("bật điều hòa", "Đã bật điều hòa 22 độ ạ."),
    ("bật sưởi ghế lái mức 2", "Đã chỉnh sưởi ghế lái mức 2 ạ."),   # không lặp chữ "ghế"
    ("đóng rèm", "Đã đóng rèm ạ."),                                  # không nói "cửa sổ trời rèm"
    ("sấy kính sau", "Đã bật sấy kính phía sau ạ."),                 # "phía sau", không phải "hàng ghế sau"
    ("mở cửa kính", "Đã mở cửa kính ạ."),                            # zone mặc định thì không đọc
    ("tăng âm lượng", "Đã tăng âm lượng 2 mức ạ."),                  # delta đọc khác tuyệt đối
    ("âm lượng 30", "Đã chỉnh âm lượng mức 30 ạ."),
    ("tắt tiếng", "Đã tắt tiếng ạ."),                                # D4: set_level(0) của volume
    ("đèn viền màu xanh dương", "Đã chuyển đèn viền sang xanh dương ạ."),
    ("bật chế độ cắm trại", "Đã bật chế độ cắm trại ạ."),
    ("tắt chế độ thú cưng", "Đã tắt chế độ thú cưng ạ."),
    ("mở spotify", "Đã mở spotify ạ."),
    ("gập gương", "Đã gập gương ạ."),
])
def test_sentences(text, expected):
    assert speak(text) == expected


def test_decimal_uses_comma():
    assert "23,5 độ" in speak("bật điều hòa hai mươi ba độ rưỡi")


def test_deny_and_confirm_use_caps_reason_verbatim():
    """Câu từ chối do bên định nghĩa xe viết, không được diễn đạt lại."""
    reason = next(r.reason for r in CAPS.safety if r.device == "mirror")
    assert speak("gập gương", S(speed_kmh=50)) == reason


def test_escalate_says_nothing():
    """Tầng trên sẽ trả lời, agent không nói chen."""
    assert speak("hôm nay trời đẹp quá") == ""


def test_query_without_a_state_provider_flags_needs_state():
    """Responder gọi trực tiếp, không kèm trạng thái, thì phải báo thiếu chứ không bịa."""
    result = resolve(CAPS, RawCommand("hvac", action="query"))
    speech = SAY.say(result)
    assert speech.needs_state and speech.text == ""


def test_query_is_answered_from_device_state():
    agent = Agent(CAPS, LEX)
    assert "chưa biết" in agent.handle("điều hòa đang bật không", S()).tts
    agent.handle("bật điều hòa", S())
    assert agent.handle("điều hòa đang bật không", S()).tts == "Điều hòa đang ở 22 độ ạ."


def test_error_sentences():
    assert speak("bật đèn pha tự động") == "Xe mình không có đèn pha tự động ạ."
    # Câu báo dải chỉ xuất hiện ở chính sách `ba`; mặc định đang là `qc`.
    assert speak("bật điều hòa 35 độ", caps=caps_theo(CAPS, gia_tri_ngoai_dai="ba")) \
        .startswith("Điều hòa chỉ hỗ trợ từ 16 đến 32 độ")
    assert speak("mở ứng dụng") == "Anh/chị muốn mở cái gì ạ?"
    assert "không hỗ trợ chế độ" in speak("tắt hiệu ứng đèn viền")


def test_cancelled_sentence():
    agent = Agent(CAPS, LEX)
    agent.handle("mở cửa kính", S(gear="D"))
    assert agent.handle("thôi", S(gear="D")).tts == "Vâng, em không làm nữa ạ."


# ------------------------------------------------------------------ bao phủ
CONTROL_PAIRS = [
    (d.name, a)
    for d in CAPS.devices.values()
    for a in CAPS.effective_actions(d)
    if a != "query"
]


@pytest.mark.parametrize("device,action", CONTROL_PAIRS, ids=[f"{d}.{a}" for d, a in CONTROL_PAIRS])
def test_every_control_action_has_a_sentence(device, action):
    """Thêm action mới mà quên viết template thì test này fail."""
    result = resolve(CAPS, minimal_raw(CAPS, CAPS.devices[device], action))
    assert result.ok, result.reason
    speech = SAY.say(result)
    assert speech.text.endswith("ạ."), f"{device}.{action}: {speech.text!r}"
    assert "{" not in speech.text


def test_golden_ok_cases_all_speak():
    """Mọi câu trong bộ chuẩn chạy được đều phải có câu trả lời."""
    silent = []
    for case in load_cases(ROOT / "tests" / "golden.vi.yaml"):
        agent = Agent(CAPS, LEX)
        for prior in case.get("context") or []:
            agent.handle(prior, S(**(case.get("state") or {})))
        turn = agent.handle(case["say"], S(**(case.get("state") or {})))
        if turn.verdict == Verdict.OK and not turn.tts and not turn.needs_state:
            silent.append(case["say"])
    assert not silent, silent


def test_boundary_reply_survives_a_state_read_without_a_number():
    """cham_bien tính trên lần đọc trạng thái THỨ NHẤT, câu trả lời dựng trên lần
    THỨ HAI (agent._voice gọi lại devices.get). Hai lần đọc lệch nhau được — khác
    vùng, hoặc xe vừa đổi. Trước đây chỗ đó gọi thẳng float(state.value) nên cả
    lượt nổ TypeError: một câu trong 24.851 câu golden đủ để hạ agent."""
    from agentcar.state import DeviceState

    result = resolve(CAPS, minimal_raw(CAPS, CAPS.devices["fan"], "increase"))
    result.cham_bien = "max"
    speech = SAY.say(result, DeviceState())          # known=False, value=None
    assert speech.text and "tối đa" not in speech.text


def test_no_golden_sentence_makes_the_agent_raise():
    """Đáp sai còn chữa được, nổ giữa lượt thì không: người dùng mất luôn câu."""
    agent = Agent(CAPS, LEX)
    for case in load_cases(ROOT / "tests" / "golden_qc.vi.yaml")[:3000]:
        try:
            agent.handle(case["say"])
        except Exception as exc:                      # noqa: BLE001
            pytest.fail(f"« {case['say']} » -> {type(exc).__name__}: {exc}")
