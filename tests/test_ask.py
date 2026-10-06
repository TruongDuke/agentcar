"""Hỏi lại khi người nói thiếu thiết bị — và nhớ động từ đã hỏi."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.agent import Agent
from agentcar.caps import load_caps
from agentcar.config import LLMSettings
from agentcar.plan import Code, Verdict
from agentcar.safety import VehicleState as S

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")


@pytest.fixture
def clock():
    return [0.0]


@pytest.fixture
def agent(clock):
    # llm_settings rỗng = không có cloud: cả luồng này phải chạy được khi mất mạng
    return Agent(CAPS, llm_settings=LLMSettings(), clock=lambda: clock[0])


def test_ask_lists_real_options(agent):
    turn = agent.handle("bật đèn", S())
    assert turn.verdict == Verdict.ASK and turn.results[0].code == Code.DEVICE_REQUIRED
    spoken = turn.tts.lower()          # lựa chọn đầu tiên được viết hoa
    for option in ("đèn viền", "đèn trần", "đèn sương mù"):
        assert option in spoken


def test_options_never_include_what_the_car_lacks(agent):
    """auto_highbeam (đèn pha) là support:false — nhắc tới là làm người dùng tưởng có."""
    assert "đèn pha" not in agent.handle("bật đèn", S()).tts


def test_options_are_filtered_by_the_verb(agent):
    """'gập' chỉ gương làm được, nên không liệt kê đèn/ghế."""
    turn = agent.handle("gập cái gương", S())
    assert turn.verdict != Verdict.ASK or "đèn" not in turn.tts


def test_generic_ask_when_there_is_no_hint(agent):
    assert agent.handle("bật", S()).tts == "Anh/chị muốn bật cái gì ạ?"


def test_remembers_the_verb_it_asked_about(agent):
    """Cái bẫy chính: trả lời chỉ có tên thiết bị, không có động từ."""
    agent.handle("tắt đèn", S())
    turn = agent.handle("đèn viền", S())
    assert turn.results[0].command.action == "turn_off", turn.tts


def test_without_memory_the_answer_would_be_inverted(agent):
    """Đối chứng: cùng câu 'đèn viền' nhưng không có gì đang chờ thì là BẬT."""
    turn = agent.handle("đèn viền", S())
    assert turn.results[0].command.action == "turn_on"


def test_verb_maps_to_the_right_action_per_device(agent):
    """'mở' là open với cửa kính nhưng turn_on với wifi."""
    agent.handle("mở", S())
    assert agent.handle("cửa kính", S()).results[0].command.action == "open"
    agent.handle("mở", S())
    assert agent.handle("wifi", S()).results[0].command.action == "turn_on"


def test_explicit_verb_in_the_answer_wins(agent):
    agent.handle("bật", S())
    turn = agent.handle("tắt đèn viền", S())
    assert turn.results[0].command.action == "turn_off"


def test_pending_slot_expires(agent, clock):
    agent.handle("tắt đèn", S())
    clock[0] = 60.0
    assert agent.handle("đèn viền", S()).results[0].command.action == "turn_on"


def test_conditional_is_refused_locally(agent):
    turn = agent.handle("mở cửa sổ trời khi nào tới nhà", S())
    assert turn.results[0].code == Code.NOT_SCHEDULABLE
    assert not [r for r in turn.results if r.command]
    assert "hẹn giờ" in turn.tts


def test_these_two_classes_need_no_cloud(agent):
    """Cả hai lớp phải trả lời được khi mất mạng — đó mới là lý do làm tại chỗ."""
    assert agent.cloud is None
    assert agent.handle("bật đèn", S()).tts
    assert agent.handle("5 phút nữa bật điều hòa", S()).tts


# ------------------------------------------------------------------ tham chiếu mơ hồ
def test_vague_reference_asks_about_the_last_device(agent):
    """'chỉnh cái kia lên' — hỏi xác nhận tại chỗ, không gọi cloud."""
    agent.handle("bật đèn viền", S())
    turn = agent.handle("chỉnh cái kia lên", S())
    assert turn.verdict == Verdict.ASK
    assert turn.results[0].code == Code.VAGUE_REFERENCE
    assert "chỉnh đèn viền" in turn.tts and turn.awaiting_confirm


def test_answering_yes_runs_it(agent):
    agent.handle("bật đèn viền", S())
    agent.handle("chỉnh cái kia lên", S())
    turn = agent.handle("ừ", S())
    assert turn.results[0].command.device == "ambient_light"
    assert turn.results[0].command.action == "increase"


def test_answering_no_cancels(agent):
    agent.handle("bật đèn viền", S())
    agent.handle("chỉnh cái kia lên", S())
    assert agent.handle("thôi", S()).verdict == Verdict.CANCELLED


def test_it_prefers_an_action_that_needs_no_value(agent):
    """'lên' (increase) dùng được ngay; set_level thì lại phải hỏi thêm mức."""
    agent.handle("bật đèn viền", S())
    agent.handle("chỉnh cái kia lên", S())
    assert agent.pending.commands[0].action == "increase"


def test_resolvable_reference_is_not_questioned(agent):
    """'cái đó tắt đi' suy ra được từ lượt trước thì chạy thẳng, KHÔNG hỏi."""
    agent.handle("bật đèn viền", S())
    turn = agent.handle("cái đó tắt đi", S())
    assert turn.verdict == Verdict.OK and turn.checkpoint == 2
    assert turn.results[0].command.action == "turn_off"


def test_nothing_mentioned_yet_means_nothing_to_ask_about(agent):
    """Chưa nhắc thiết bị nào thì chốt này bỏ qua, để tầng trên lo."""
    turn = agent.handle("chỉnh cái kia lên", S())
    assert turn.results[0].code != Code.VAGUE_REFERENCE


def test_vague_check_needs_no_cloud(agent):
    assert agent.cloud is None
    agent.handle("bật đèn viền", S())
    assert agent.handle("chỉnh cái kia lên", S()).cloud_ms is None


# ------------------------------------------- hỏi số liệu sống: có nguồn / không nguồn
def _dem_cloud():
    """Cloud giả chỉ để ĐẾM số lần gọi."""
    from agentcar.config import LLMSettings

    class Dem:
        client = None
        settings = LLMSettings(model="gia-lap")

        def __init__(self):
            self.dem = 0

        def interpret(self, text, context=""):
            self.dem += 1

            class Out:
                ok, unreachable, timed_out, error = True, False, False, None
                elapsed_ms = 900.0
                ask = reply = route = None
                commands = []
            return Out()
    return Dem()


def _tro_ly(client):
    from agentcar.assistant import CloudAssistant

    def thoi_tiet(lat, lon, timeout_s=3.0):
        return {"temperature_2m": 31.5, "weather_code": 1, "wind_speed_10m": 8.0,
                "relative_humidity_2m": 70, "apparent_temperature": 35.0}
    return CloudAssistant(client=client.client, settings=client.settings,
                          weather=thoi_tiet, city="Hà Nội")


@pytest.mark.parametrize("cau,chu_de", [
    ("giá vàng hôm nay bao nhiêu", "giá vàng"),
    ("tỉ giá đô la bao nhiêu", "tỉ giá"),
    ("tin tức hôm nay thế nào", "tin tức"),
])
def test_hoi_so_lieu_song_khong_co_nguon_thi_khong_goi_cloud(cau, chu_de):
    """Câu trả lời cuối cùng vẫn là "chưa xem được" dù có gọi cloud hay không —
    vậy thì trả lời thẳng trên xe, khỏi tốn ~900ms và tiền."""
    cl = _dem_cloud()
    turn = Agent(CAPS, llm=cl, handlers={"assistant": _tro_ly(cl)}).handle(cau, S())
    assert cl.dem == 0, f"vẫn gọi cloud {cl.dem} lần"
    assert chu_de in turn.tts and "chưa xem được" in turn.tts


def test_hoi_thoi_tiet_co_nguon_that_cung_khong_goi_cloud():
    """Nhận ra câu hỏi thời tiết chỉ là khớp từ khoá — làm được trên xe. Số liệu lấy
    từ Open-Meteo, không qua model lần nào."""
    cl = _dem_cloud()
    turn = Agent(CAPS, llm=cl, handlers={"assistant": _tro_ly(cl)}).handle(
        "hôm nay trời thế nào", S())
    assert cl.dem == 0
    assert "32 độ" in turn.tts


def test_hoi_kien_thuc_chung_thi_VAN_phai_len_cloud():
    """Không có nguồn nào thay thế được — đây đúng chỗ cần cloud."""
    cl = _dem_cloud()
    Agent(CAPS, llm=cl, handlers={"assistant": _tro_ly(cl)}).handle(
        "ai phát minh ra bóng đèn", S())
    assert cl.dem == 1
