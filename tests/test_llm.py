"""Tầng [2] — đề xuất của LLM vẫn phải đi qua caps như mọi lệnh khác."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import caps_theo

from agentcar.agent import Agent
from agentcar.caps import load_caps
from agentcar.config import LLMSettings
from agentcar.lexicon import load_lexicon
from agentcar.llm import DashScopeClient, CloudPath, build_cloud_path, render_digest

# Chụp lại bản gốc TRƯỚC khi conftest thay bằng hàm nổ.
REAL_COMPLETE = DashScopeClient.complete
from agentcar.plan import Code, RawCommand, Verdict
from agentcar.safety import VehicleState as S

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
LEX = load_lexicon(CAPS)
CFG = LLMSettings(api_key="sk-test", enabled=True, timeout_ms=1200, model="qwen-plus")


class FakeClient:
    """Không chạm mạng. Trả đúng chuỗi được dựng sẵn."""

    def __init__(self, reply="", error: Exception | None = None, delay_ms: float = 0.0):
        self.reply, self.error, self.delay_ms = reply, error, delay_ms
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, user, timeout_s):
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return self.reply


def reply(*commands) -> str:
    return json.dumps({"commands": list(commands)}, ensure_ascii=False)


def agent_with(client, caps=None) -> Agent:
    """nlu=False: những test dưới đây đo TẦNG CLOUD.

    Tầng [1b] (model NLU trên xe) đứng trước cloud và bắt được phần lớn câu tầng
    luật bó tay — bật nó lên thì cloud không bao giờ được gọi, và test hoá ra
    đang đo tầng khác. Muốn đo cloud thì phải cô lập cloud.
    """
    caps = caps or CAPS
    return Agent(caps, LEX, llm=CloudPath(caps, LEX, client, CFG), nlu=False)


def test_cloud_runs_only_when_edge_misses():
    client = FakeClient(reply({"device": "hvac", "action": "decrease"}))
    agent = agent_with(client)
    agent.handle("bật điều hòa", S())          # tầng edge bắt được
    assert client.calls == []
    agent.handle("nóng quá", S())              # tầng edge bó tay
    assert len(client.calls) == 1


def test_llm_suggestion_is_executed_after_validation():
    agent = agent_with(FakeClient(reply(
        {"device": "hvac", "action": "decrease", "value": 2, "unit": "celsius"})))
    turn = agent.handle("nóng quá", S())
    assert turn.verdict == Verdict.OK
    assert turn.results[0].command.action == "decrease"
    assert "Đã giảm điều hòa" in turn.tts


def test_fabricated_device_is_rejected():
    """Model bịa thiết bị thì tầng [3] chặn, không xuống PlanRunner."""
    agent = agent_with(FakeClient(reply({"device": "ghe_bay", "action": "fly"})))
    turn = agent.handle("cho xe bay lên", S())
    assert turn.verdict == Verdict.INVALID
    assert turn.results[0].code == Code.UNKNOWN_DEVICE


def test_fabricated_action_is_rejected():
    agent = agent_with(FakeClient(reply({"device": "mirror", "action": "adjust"})))
    assert agent.handle("chỉnh lại giùm em", S()).results[0].code == Code.INVALID_ACTION


def test_llm_cannot_bypass_safety():
    """Đề xuất của model vẫn phải qua tầng [4]."""
    agent = agent_with(FakeClient(reply({"device": "mirror", "action": "fold"})))
    turn = agent.handle("gương gập lại giùm", S(speed_kmh=50))
    assert turn.verdict == Verdict.DENY


def test_llm_value_out_of_range_is_refused():
    """Chính sách `ba`: cloud đoán bừa 999 thì tầng tất định chặn, không cắt về 40.

    Với chính sách `qc` (mặc định hiện tại) thì 999 đi thẳng xuống xe — đó là
    quyết định nghiệm thu, không phải lỗi. Xem khối `policy` trong caps.
    """
    agent = agent_with(FakeClient(reply(
        {"device": "volume", "action": "set_level", "value": 999, "unit": "level"})),
        caps=caps_theo(CAPS, gia_tri_ngoai_dai="ba"))
    # Câu phải là câu tầng luật CHỊU THUA, để lượt này đi tới cloud. Trước đây
    # dùng "mở hết cỡ đi" — từ khi có cực trị thì tầng luật hiểu luôn, và test
    # đo nhầm sang VA_DEVICE_REQUIRED.
    turn = agent.handle("làm như hôm qua đi", S())
    assert turn.results[0].command is None
    assert turn.results[0].code == Code.OUT_OF_RANGE


def test_empty_answer_escalates():
    agent = agent_with(FakeClient(reply()))
    assert agent.handle("hôm nay trời đẹp quá", S()).verdict == Verdict.ESCALATE_UNKNOWN


def test_network_error_escalates_and_is_traced():
    agent = agent_with(FakeClient(error=OSError("mất mạng")))
    turn = agent.handle("nóng quá", S())
    assert turn.verdict == Verdict.ESCALATE_UNKNOWN
    assert any("không gọi được" in n for n in turn.trace)


def test_garbage_answer_escalates():
    agent = agent_with(FakeClient("xin chào, tôi không hiểu"))
    assert agent.handle("nóng quá", S()).verdict == Verdict.ESCALATE_UNKNOWN


def test_deadline_is_enforced():
    slow = CloudPath(CAPS, LEX, FakeClient(reply({"device": "hvac", "action": "turn_on"})),
                    LLMSettings(api_key="sk", enabled=True, timeout_ms=0))
    outcome = slow.interpret("nóng quá")
    assert not outcome.ok and "quá hạn" in outcome.error


def test_at_most_four_commands():
    agent = agent_with(FakeClient(reply(*([{"device": "wifi", "action": "turn_on"}] * 9))))
    assert len(agent.handle("làm gì đó đi", S()).results) == 4


def test_no_key_means_no_cloud():
    assert build_cloud_path(CAPS, LEX, LLMSettings(enabled=True)) is None
    assert build_cloud_path(CAPS, LEX, LLMSettings(api_key="sk", enabled=False)) is None
    assert build_cloud_path(CAPS, LEX, LLMSettings(api_key="sk", enabled=True)) is not None


def test_digest_hides_what_the_car_cannot_do():
    """Cái gì xe không làm được thì không đưa vào prompt — model khỏi phải đoán."""
    digest = render_digest(CAPS, LEX)
    listed = {line.split(" (")[0] for line in digest.splitlines()}
    assert {"auto_highbeam", "hud", "tire_pressure"} & listed == set()   # support:false
    assert "frunk" in listed                                            # BA chốt 28/09: VF9 có cốp trước
    assert "nav" not in listed                                                    # cloud_only
    assert "fx_none" not in digest                                                # bị exclude (D2)
    assert "hvac" in listed


class FakeConnection:
    """Đếm số lần thực sự mở kết nối."""

    opened = 0

    def __init__(self, host, timeout=None):
        FakeConnection.opened += 1
        self.host, self.timeout, self.closed, self.fail_once = host, timeout, False, False

    def request(self, method, path, body=None, headers=None):
        if self.fail_once:
            raise OSError("kết nối cũ đã bị đóng")

    def getresponse(self):
        class R:
            status = 200

            @staticmethod
            def read():
                return json.dumps({"choices": [{"message": {"content": reply()}}]}).encode()
        return R()

    def close(self):
        self.closed = True


@pytest.fixture
def fake_https(monkeypatch):
    FakeConnection.opened = 0
    created: list[FakeConnection] = []

    def factory(host, timeout=None):
        conn = FakeConnection(host, timeout)
        created.append(conn)
        return conn

    monkeypatch.setattr("agentcar.llm.http.client.HTTPSConnection", factory)
    monkeypatch.setattr("agentcar.llm.DashScopeClient.complete", REAL_COMPLETE)
    return created


def test_connection_is_reused_across_calls(fake_https):
    """Bắt tay TLS mỗi lượt tốn ~400ms — đủ để đẩy câu vốn kịp hạn thành quá hạn."""
    client = DashScopeClient(CFG)
    for _ in range(3):
        client.complete("sys", "nóng quá", 1.2)
    assert FakeConnection.opened == 1


def test_stale_connection_is_reopened_once(fake_https):
    client = DashScopeClient(CFG)
    client.complete("sys", "nóng quá", 1.2)
    fake_https[0].fail_once = True                  # phía kia đóng kết nối
    client.complete("sys", "lạnh quá", 1.2)
    assert FakeConnection.opened == 2 and fake_https[0].closed


# ------------------------------------------------------------------ mất mạng
def slow_with(client, clock=None, **kw):
    return CloudPath(CAPS, LEX, client, CFG, clock=clock or (lambda: 0.0), **kw)


def test_unreachable_is_flagged_apart_from_bad_output():
    """Mất mạng khác 'model trả rác' — một cái phải báo cho người dùng, cái kia không."""
    assert slow_with(FakeClient(error=OSError("mất mạng"))).interpret("nóng quá").unreachable
    assert not slow_with(FakeClient("không phải json")).interpret("nóng quá").unreachable


def test_breaker_opens_after_repeated_failures():
    """Mạng treo thì mỗi câu phải chờ hết deadline. Hỏng liên tiếp thì ngưng gọi."""
    client = FakeClient(error=OSError("mất mạng"))
    slow = slow_with(client, breaker_after=2)
    for _ in range(2):
        slow.interpret("nóng quá")
    assert slow.breaker_open
    before = len(client.calls)
    outcome = slow.interpret("lạnh quá")
    assert len(client.calls) == before          # không gọi nữa
    assert outcome.unreachable and "tạm ngưng" in outcome.error


def test_breaker_recovers_after_cooldown():
    now = [0.0]
    client = FakeClient(error=OSError("mất mạng"))
    slow = slow_with(client, clock=lambda: now[0], breaker_after=2, breaker_cooldown_s=30)
    slow.interpret("a"); slow.interpret("b")
    assert slow.breaker_open
    now[0] = 31.0
    assert not slow.breaker_open
    client.error, client.reply = None, reply({"device": "wifi", "action": "turn_on"})
    assert slow.interpret("bật wifi").ok and slow.failures == 0


def test_bad_output_does_not_open_the_breaker():
    """Model trả rác không phải lỗi mạng — vẫn nên gọi tiếp câu sau."""
    slow = slow_with(FakeClient("rác"), breaker_after=2)
    slow.interpret("a"); slow.interpret("b")
    assert not slow.breaker_open


def test_offline_answer_is_spoken():
    """Im lặng là tệ nhất: người dùng không biết xe có nghe thấy không."""
    agent = agent_with(FakeClient(error=OSError("mất mạng")))
    turn = agent.handle("nóng quá", S())
    assert turn.results[0].code == Code.LLM_UNAVAILABLE
    assert "mất kết nối" in turn.tts


def test_timeout_is_spoken_too():
    """Chờ 3 giây rồi không nghe gì là tệ nhất — phải nói ra."""
    slow = CloudPath(CAPS, LEX, FakeClient(reply({"device": "wifi", "action": "turn_on"})),
                    LLMSettings(api_key="sk", enabled=True, timeout_ms=0))
    agent = Agent(CAPS, LEX, llm=slow, nlu=False)   # đo cloud, phải tắt tầng [1b]
    turn = agent.handle("nóng quá", S())
    assert turn.results[0].code == Code.LLM_TIMEOUT
    assert "hơi lâu" in turn.tts


def test_plain_escalate_stays_silent():
    """Model hiểu nhưng không có lệnh nào — để tầng trên trả lời, không nói chen."""
    turn = agent_with(FakeClient(reply())).handle("hôm nay trời đẹp quá", S())
    assert turn.results[0].code == Code.ESCALATE_UNKNOWN and turn.tts == ""


def test_edge_never_touches_the_network(fake_https):
    """Câu thường phải chạy được khi mất mạng hoàn toàn."""
    client = FakeClient(error=OSError("mất mạng"))
    agent = agent_with(client)
    assert agent.handle("bật điều hòa", S()).verdict == Verdict.OK
    assert client.calls == []


def test_fresh_connection_is_not_retried(fake_https):
    """Kết nối vừa mở mà hỏng thì mạng đang hỏng — thử lại chỉ làm chờ gấp đôi."""
    from agentcar.llm import DashScopeClient

    class Dead(FakeConnection):
        def request(self, *a, **kw):
            raise OSError("không tới được")

    fake_https.clear()
    FakeConnection.opened = 0
    import agentcar.llm as llm_module
    original = llm_module.http.client.HTTPSConnection
    llm_module.http.client.HTTPSConnection = lambda host, timeout=None: Dead(host, timeout)
    try:
        with pytest.raises(OSError):
            DashScopeClient(CFG).complete("sys", "nóng quá", 1.2)
        assert FakeConnection.opened == 1
    finally:
        llm_module.http.client.HTTPSConnection = original


# --------------------------------------------------------------- khung JSON lệch
# Model trả ĐÚNG đáp án nhưng sai hình dạng khá thường. Parser cũ chỉ biết khoá
# "commands" nên vứt sạch rồi báo "không hiểu" — đo trên 500 câu stress mất 23 câu
# chỉ vì chuyện này.
@pytest.mark.parametrize("raw, want", [
    ('{"screen_control": {"action": "open", "item": "trip_statistics"}}',
     ("screen_control", "open")),                      # tên thiết bị làm khoá
    ('{"device": "hvac", "action": "turn_on"}', ("hvac", "turn_on")),   # lệnh trần
    ('{"commands": {"device": "window", "action": "open"}}',
     ("window", "open")),                              # quên bọc thành list
    ('{"commands": [{"device": "fan", "action": "turn_on"}]}',
     ("fan", "turn_on")),                              # đúng hợp đồng
])
def test_parse_accepts_common_wrong_shapes(raw, want):
    slow = CloudPath(CAPS, LEX, DashScopeClient(CFG), CFG)
    commands, error, _, _, _ = slow.parse(raw)
    assert error is None
    assert [(c.device, c.action) for c in commands] == [want]


@pytest.mark.parametrize("raw", [
    '{"reply": "Em chưa biết ạ"}',
    '{"route": "nav"}',
    '{"ask": "Anh muốn bật đèn nào ạ?"}',
    '{"ghi_chu": {"abc": 1}}',
])
def test_widened_parse_does_not_invent_commands(raw):
    """Nới parse KHÔNG được biến mọi thứ thành lệnh — bịa lệnh tệ hơn không hiểu."""
    slow = CloudPath(CAPS, LEX, DashScopeClient(CFG), CFG)
    commands, _, _, _, _ = slow.parse(raw)
    assert commands == []


# --------------------------------------------------------- chốt 7: phủ sóng thấp
# Fast path ghép được lệnh KHÔNG có nghĩa là nó hiểu đúng câu — nó chỉ cần nhặt
# trúng vài từ khoá. Đo trên 500 câu stress: bỏ qua ≤2 chữ thì đúng 76.5%, bỏ qua
# ≥7 chữ chỉ còn 23.8%.
RAMBLING = ("Bạn ơi, mở giùm mình cái phần cài đặt âm thanh trên màn hình nha "
            "rồi bật sưởi ghế lái")


def test_low_coverage_asks_cloud_even_though_edge_had_a_command():
    client = FakeClient(reply({"device": "screen_control", "action": "open",
                               "item": "volume_settings"}))
    agent = Agent(CAPS, LEX, llm=CloudPath(CAPS, LEX, client, CFG), low_coverage=4)
    turn = agent.handle(RAMBLING, S())
    assert client.calls, "bỏ qua quá nhiều chữ thì phải hỏi tầng [2]"
    assert turn.checkpoint == 7
    assert [r.command.item for r in turn.results if r.command] == ["volume_settings"]


def test_low_coverage_keeps_edge_command_when_cloud_is_unreachable():
    """Mất mạng KHÔNG được biến thành im lặng — ngưỡng chỉ đổi thứ tự ưu tiên."""
    import urllib.error
    client = FakeClient(error=urllib.error.URLError("mạng chết"))
    agent = Agent(CAPS, LEX, llm=CloudPath(CAPS, LEX, client, CFG), low_coverage=4)
    turn = agent.handle(RAMBLING, S())
    assert turn.verdict == Verdict.OK
    assert [r.command.device for r in turn.results if r.command] \
        == ["screen_control", "seat_heating"]


def test_low_coverage_keeps_edge_command_when_cloud_returns_no_command():
    client = FakeClient('{"reply": "dạ em chưa rõ"}')
    agent = Agent(CAPS, LEX, llm=CloudPath(CAPS, LEX, client, CFG), low_coverage=4)
    turn = agent.handle(RAMBLING, S())
    assert [r.command.device for r in turn.results if r.command] \
        == ["screen_control", "seat_heating"]


def test_clear_command_never_pays_for_a_cloud_call():
    """Câu DÀI mà tầng edge hiểu hết thì vẫn chạy tại chỗ — ngưỡng đo độ hiểu,
    không đo độ dài."""
    client = FakeClient(reply({"device": "hvac", "action": "turn_on"}))
    agent = Agent(CAPS, LEX, llm=CloudPath(CAPS, LEX, client, CFG), low_coverage=4)
    turn = agent.handle("mở cửa kính sau bên trái xuống 50% rồi bật quạt thổi mặt "
                        "mức 3 và mở spotify lên", S())
    assert not client.calls, "câu rõ ràng không được tốn vòng gọi mạng"
    assert turn.checkpoint == 2
    assert len([r for r in turn.results if r.command]) == 3


# ------------------------------------------------- luật C: một lượt, một vòng cloud
class DemCloud:
    """Đếm số lần một lượt nói gọi ra cloud."""

    client = None
    settings = LLMSettings(model="gia-lap")

    def __init__(self, commands=None):
        self.dem = 0
        self._commands = commands or [RawCommand(device="hvac", action="turn_on")]

    def interpret(self, text, context=""):
        self.dem += 1
        me = self

        class Out:
            ok, unreachable, timed_out, error = True, False, False, None
            elapsed_ms = 900.0
            ask = reply = route = None
            commands = me._commands
        return Out()


@pytest.mark.parametrize("cau", [
    "nóng quá",
    "trời ơi nay nóng kinh khủng mà xe thì bí quá làm gì đi",
    "anh thấy trong người khó chịu quá đi mất thôi làm gì đó cho dễ chịu đi",
    "mở ứng dụng",
])
def test_mot_luot_chi_mot_vong_cloud(cau):
    """caps khai deadline_ms=1200 mà một vòng cloud đo thật đã p50 903ms, p90 1275ms.
    Gọi hai lần là chắc chắn vượt trần và tốn gấp đôi tiền.

    Đã từng hỏng thật: câu edge trượt hoàn toàn thì gần như luôn còn nhiều chữ
    không khớp, nên nhánh low_coverage thoả ngay sau khi nhánh 'không ra lệnh nào'
    vừa gọi cloud xong — câu dài nói vòng ăn đủ hai vòng, ~1800ms.
    """
    cloud = DemCloud()
    Agent(CAPS, LEX, llm=cloud, handlers={}).handle(cau, S())
    assert cloud.dem <= 1, f"gọi cloud {cloud.dem} lần trong một lượt"
