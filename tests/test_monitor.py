"""Nguồn tín hiệu xe: kịch bản lái thay cho một VehicleState đứng yên."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.agent import Agent
from agentcar.caps import SafetyRule, load_caps
from agentcar.monitor import FixedMonitor, MockSignalMonitor
from agentcar.plan import Verdict
from agentcar.safety import VehicleState as S

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
DRIVE = ROOT / "scenarios" / "city_drive.yaml"


@pytest.fixture
def clock():
    return [0.0]


def monitor(rows, clock, **kw):
    return MockSignalMonitor.from_rows(rows, clock=lambda: clock[0], **kw)


# ----------------------------------------------------------------- kịch bản
def test_giu_nguyen_truong_moc_sau_khong_khai(clock):
    m = monitor([{"at": 0, "gear": "P", "battery": 80},
                 {"at": 5, "gear": "D", "speed": 30}], clock)
    assert m.at(5).gear == "D"
    assert m.at(5).battery_pct == 80        # mốc sau không nhắc pin thì giữ của mốc trước


@pytest.mark.parametrize("second,speed", [(0, 0), (4.9, 0), (5, 30), (99, 30)])
def test_bac_thang_khong_noi_suy(clock, second, speed):
    m = monitor([{"at": 0, "speed": 0}, {"at": 5, "speed": 30}], clock)
    assert m.at(second).speed_kmh == speed


def test_truoc_moc_dau_tien_coi_nhu_xe_do(clock):
    m = monitor([{"at": 10, "gear": "D", "speed": 50}], clock)
    assert m.at(0).gear == "P" and m.at(0).speed_kmh == 0
    assert m.at(10).gear == "D"


def test_dong_ho_bat_dau_o_lan_doc_dau_tien(clock):
    m = monitor([{"at": 0, "speed": 0}, {"at": 5, "speed": 30}], clock)
    clock[0] = 100.0                        # dựng monitor xong bỏ đó 100 giây
    assert m.read().speed_kmh == 0          # vẫn đang ở giây 0 của kịch bản
    clock[0] = 105.0
    assert m.read().speed_kmh == 30


def test_period_quay_lai_dau(clock):
    rows = [{"at": 0, "speed": 0}, {"at": 5, "speed": 30}]
    looped, once = monitor(rows, clock, period=8.0), monitor(rows, clock)
    looped.read(), once.read()
    clock[0] = 9.0
    assert looped.read().speed_kmh == 0     # 9 % 8 = 1 -> về mốc đầu
    assert once.read().speed_kmh == 30      # không khai period thì đứng ở mốc cuối


def test_moc_cuoi_van_duoc_phat_truoc_khi_quay_lai(clock):
    """Chu kỳ phải DÀI HƠN mốc cuối. Lấy chu kỳ đúng bằng mốc cuối thì mốc đó rơi
    trúng điểm wrap và không bao giờ đọc ra được — đã dính đúng lỗi này một lần."""
    m = monitor([{"at": 0, "speed": 0}, {"at": 5, "speed": 30}], clock, period=8.0)
    m.read()
    for giay, speed in ((5, 30), (7.9, 30), (8, 0)):
        clock[0] = giay
        assert m.read().speed_kmh == speed


def test_tin_hieu_ngoai_nam_cai_mac_dinh_vao_extra(clock):
    m = monitor([{"at": 0, "charging": "yes", "door_open": True}], clock)
    state = m.at(0)
    assert state.charging is True           # "yes" trong YAML vẫn ra bool
    assert state.get("door_open") is True


def test_doc_file_kich_ban():
    m = MockSignalMonitor.from_yaml(DRIVE)
    assert m.period == 60 and m.loops
    assert m.duration == 52                         # chu kỳ dài hơn mốc cuối
    assert m.at(0).gear == "P"
    assert m.at(6).parking_brake == "released"      # alias brake
    assert m.at(12).speed_kmh == 34                 # alias speed
    assert m.at(52).battery_pct == 21               # alias battery


# -------------------------------------------------------------------- agent
def test_khong_co_monitor_thi_xe_do():
    assert Agent(CAPS).read_state().describe() == S().describe()


def test_state_truyen_vao_thang_monitor(clock):
    m = monitor([{"at": 0, "gear": "D", "speed": 60}], clock)
    agent = Agent(CAPS, clock=lambda: clock[0], monitor=m)
    # eval và test cần dựng tình huống cố định, nên state truyền tay phải thắng
    assert agent.handle("gập gương", S()).verdict == Verdict.OK


def test_fixed_monitor_sua_tai_cho():
    fixed = FixedMonitor()
    agent = Agent(CAPS, monitor=fixed)
    assert agent.handle("mở cửa kính").verdict == Verdict.OK
    fixed.state.gear = "D"                  # repl :set gear=D sửa đúng chỗ này
    assert agent.handle("mở cửa kính").verdict == Verdict.CONFIRM


def test_cung_mot_cau_hai_thoi_diem_hai_ket_qua(clock):
    agent = Agent(CAPS, clock=lambda: clock[0],
                  monitor=MockSignalMonitor.from_yaml(DRIVE, clock=lambda: clock[0]))
    assert agent.handle("gập gương").verdict == Verdict.OK       # giây 0, xe đỗ
    clock[0] = 20.0                                              # giây 20, 34 km/h
    assert agent.handle("gập gương").verdict == Verdict.DENY


def test_xe_tang_toc_trong_luc_cho_xac_nhan_thi_bi_tu_choi(clock):
    """Lời hứa ở Agent._apply_pending, tới giờ mới kiểm được.

    caps/vf9.yaml không có thiết bị nào vừa CONFIRM vừa DENY, nên thêm một luật
    DENY cho riêng test này thay vì sửa caps thật.
    """
    caps = load_caps(ROOT / "caps" / "vf9.yaml")
    caps.safety.append(SafetyRule(
        device="window", action="open", verdict=Verdict.DENY, when="speed_kmh >= 60",
        reason="Xe đang chạy quá nhanh, chưa mở cửa kính được ạ.", index=len(caps.safety)))
    m = monitor([{"at": 0, "gear": "D", "speed": 12}, {"at": 3, "speed": 62}], clock)
    agent = Agent(caps, clock=lambda: clock[0], monitor=m)

    assert agent.handle("mở cửa kính").verdict == Verdict.CONFIRM
    clock[0] = 3.0                          # người dùng nghĩ 3 giây, xe tăng tốc
    answer = agent.handle("ừ")
    assert answer.verdict == Verdict.DENY
    assert agent.pending is None
    assert agent.runner.log == []           # và lệnh KHÔNG được gửi xuống xe
