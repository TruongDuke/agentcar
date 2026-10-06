"""Trạng thái thiết bị và câu trả lời cho câu hỏi."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.agent import Agent
from agentcar.caps import load_caps
from agentcar.plan import Command
from agentcar.safety import VehicleState as S
from agentcar.state import MockStateProvider

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")


@pytest.fixture
def agent():
    return Agent(CAPS)


def say(agent, *lines: str) -> str:
    out = ""
    for line in lines:
        out = agent.handle(line, S()).tts
    return out


def test_unknown_before_anything_happens(agent):
    assert "chưa biết" in say(agent, "điều hòa đang bật không")


@pytest.mark.parametrize("script,expected", [
    (["bật điều hòa", "điều hòa bao nhiêu độ"], "Điều hòa đang ở 22 độ ạ."),
    (["tắt điều hòa", "điều hòa đang bật không"], "Điều hòa đang tắt ạ."),
    (["mở cửa kính", "cửa kính mở chưa"], "Cửa kính đang mở ạ."),
    (["đóng cửa kính", "cửa kính mở chưa"], "Cửa kính đang đóng ạ."),
    (["gập gương", "gương đang thế nào"], "Gương đang gập ạ."),
    (["bật wifi", "wifi đang bật không"], "Wifi đang bật ạ."),
    (["bật chế độ cắm trại", "chế độ nào đang bật"], "Đang bật chế độ cắm trại ạ."),
    (["mở spotify", "đang mở app gì"], "Đang mở spotify ạ."),
    (["bật sưởi ghế lái mức 2", "sưởi ghế đang thế nào"], "Sưởi ghế đang ở mức 2 ạ."),
])
def test_query_reflects_what_was_executed(agent, script, expected):
    assert say(agent, *script) == expected


def test_relative_change_updates_the_known_value(agent):
    assert say(agent, "bật điều hòa", "tăng 2 độ", "điều hòa bao nhiêu độ") == "Điều hòa đang ở 24 độ ạ."


def test_relative_change_starts_from_comfort_default(agent):
    """Không biết mức cũ thì lấy comfort_default trong caps làm mốc.

    Trước đây đây là no-op im lặng, mà agent vẫn nói "đã tăng âm lượng 2 mức ạ" —
    hỏi lại thì bảo chưa biết. Âm lượng khai comfort_default 12, nudge 2.
    """
    assert say(agent, "tăng âm lượng", "âm lượng bao nhiêu") == "Âm lượng đang ở mức 14 ạ."


def test_mode_groups_coexist(agent):
    """D1 kiểm tới tận câu trả lời: đặt nhóm này không xoá nhóm kia."""
    answer = say(agent, "lấy gió trong", "thổi mặt", "quạt gió đang thế nào")
    assert "lấy gió trong" in answer and "thổi mặt" in answer


def test_blocked_command_does_not_change_state(agent):
    agent.handle("gập gương", S(speed_kmh=50))          # DENY
    assert "chưa biết" in agent.handle("gương đang thế nào", S()).tts


def test_pending_command_does_not_change_state(agent):
    agent.handle("mở cửa kính", S(gear="D"))            # CONFIRM, chưa chạy
    assert "chưa biết" in agent.handle("cửa kính mở chưa", S()).tts
    agent.handle("ừ", S(gear="D"))
    assert agent.handle("cửa kính mở chưa", S()).tts == "Cửa kính đang mở ạ."


def test_zone_fallback_when_asked_generally(agent):
    """Đặt đúng một vùng rồi hỏi chung chung thì trả vùng đó, không nói không biết."""
    provider = MockStateProvider(CAPS)
    provider.apply(Command("seat_heating", "set_level", zone="driver", value=2, unit="level"))
    assert provider.get("seat_heating", "all").value == 2


def test_two_zones_make_a_general_question_ambiguous():
    provider = MockStateProvider(CAPS)
    provider.apply(Command("seat_heating", "set_level", zone="driver", value=2, unit="level"))
    provider.apply(Command("seat_heating", "set_level", zone="passenger", value=3, unit="level"))
    assert not provider.get("seat_heating", "all").known


def test_query_never_reaches_the_plan_runner(agent):
    """Câu hỏi không phải lệnh: không được sinh ra tác động nào."""
    agent.handle("bật điều hòa", S())
    before = agent.devices.get("hvac", "all")
    agent.handle("điều hòa bao nhiêu độ", S())
    assert agent.devices.get("hvac", "all") == before


# ------------------------------------------------------------------ lưu ra file
def test_state_survives_a_new_process(tmp_path):
    """Mỗi lần gọi `agentcar run` là một tiến trình mới — không lưu thì câu hỏi
    trạng thái luôn trả 'chưa biết'."""
    path = tmp_path / "device-state.json"
    first = Agent(CAPS, state_provider=MockStateProvider(CAPS, path))
    first.handle("bật điều hòa 24 độ", S())

    second = Agent(CAPS, state_provider=MockStateProvider(CAPS, path))
    assert second.handle("điều hòa bao nhiêu độ", S()).tts == "Điều hòa đang ở 24 độ ạ."


def test_no_path_means_no_file(tmp_path):
    """Mặc định không ghi gì — thư viện và test không được tự sinh rác."""
    MockStateProvider(CAPS).apply(Command("hvac", "turn_on", zone="all"))
    assert not list(tmp_path.iterdir())


def test_corrupt_state_file_is_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("không phải json", encoding="utf-8")
    assert MockStateProvider(CAPS, path).snapshot() == []


def test_reset_clears_the_file(tmp_path):
    path = tmp_path / "state.json"
    provider = MockStateProvider(CAPS, path)
    provider.apply(Command("hvac", "turn_on", zone="all"))
    provider.reset()
    assert MockStateProvider(CAPS, path).snapshot() == []


# ------------------------------------------- lệnh trùng trạng thái đang có
def test_bat_thu_dang_bat_thi_noi_ra_chu_khong_gui_lai(agent):
    """"bật điều hòa" khi nó đang bật không phải lỗi — chỉ là không có gì để làm.
    Gửi lại lệnh rồi báo "đã bật" là báo một việc không xảy ra."""
    agent.handle("bật điều hòa", S())
    truoc = len(agent.runner.log)

    turn = agent.handle("bật điều hòa", S())
    assert len(agent.runner.log) == truoc, "vẫn gửi lệnh xuống xe"
    assert turn.tts == "Điều hòa đang ở 22 độ ạ."


@pytest.mark.parametrize("dau,lap,doi", [
    ("mở cửa kính", "mở cửa kính", "đóng cửa kính"),
    ("điều hòa 22 độ", "điều hòa 22 độ", "điều hòa 25 độ"),
    ("lấy gió trong", "lấy gió trong", "lấy gió ngoài"),
])
def test_chi_bo_qua_lenh_TRUNG(agent, dau, lap, doi):
    """Trùng thì bỏ qua, khác thì vẫn chạy."""
    agent.handle(dau, S())
    n = len(agent.runner.log)
    agent.handle(lap, S())
    assert len(agent.runner.log) == n, f"{lap!r} trùng mà vẫn gửi"
    agent.handle(doi, S())
    assert len(agent.runner.log) == n + 1, f"{doi!r} khác mà không gửi"


def test_chua_biet_trang_thai_thi_van_gui(agent):
    """Không biết thì thà gửi lệnh thừa còn hơn bỏ qua lệnh người dùng thật sự muốn."""
    turn = agent.handle("bật điều hòa", S())
    assert len(agent.runner.log) == 1
    assert turn.tts == "Đã bật điều hòa 22 độ ạ."


def test_hai_lenh_cung_nhom_mode_chi_noi_lenh_cuoi(agent):
    """"lấy gió trong rồi lấy gió ngoài" — hai chế độ loại trừ nhau, catalog biết
    điều đó qua mode_group. Nói cả hai là nói làm hai việc trong khi chỉ có một."""
    turn = agent.handle("lấy gió trong rồi lấy gió ngoài", S())
    assert turn.tts == "Đã chuyển quạt gió sang lấy gió ngoài ạ."


def test_hai_lenh_KHAC_nhom_thi_giu_ca_hai(agent):
    """"lấy gió trong" và "thổi mặt" cùng là quạt gió nhưng khác nhóm — không đè nhau."""
    turn = agent.handle("lấy gió trong và thổi mặt", S())
    assert turn.tts.count("Đã chuyển") == 2


def test_boundary_respects_a_negative_step():
    """"tăng -3 nấc" thực chất là GIẢM 3, nên thiết bị đang ở max không được đáp
    "đang tối đa rồi, không tăng thêm được" — câu đó làm nó giảm thật.

    Dấu âm chỉ đọc được từ khi normalize() thôi xoá nó cùng dấu câu (4c1c2d2);
    trước đó không câu nào tới được nhánh này. Lòi ra lúc demo trên trình duyệt.
    """
    from agentcar.plan import Command
    from agentcar.state import DeviceState, cham_bien

    o_max = DeviceState(on=True, value=40, unit="level")
    assert cham_bien(CAPS, Command(device="volume", action="increase",
                                   unit="level", step=3), o_max) == "max"
    assert cham_bien(CAPS, Command(device="volume", action="increase",
                                   unit="level", step=-3), o_max) is None
