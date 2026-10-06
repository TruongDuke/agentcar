"""Mốc xuất phát cho thiết bị, và việc dùng chung trạng thái giữa các tiến trình."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar import baseline
from agentcar.caps import load_caps
from agentcar.lexicon import load_lexicon
from agentcar.respond import Responder
from agentcar.agent import Agent
from agentcar.plan import Verdict
from agentcar.safety import VehicleState as S
from agentcar.server import Simulator
from agentcar.state import DeviceState, MockStateProvider

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")


@pytest.fixture(scope="module")
def responder():
    return Responder(CAPS, load_lexicon(CAPS))


def state_of(rows, device):
    return next(st for name, _, st in rows if name == device)


def test_thiet_bi_khong_ho_tro_thi_khong_nap(responder):
    """Nói 'đang tắt' về thứ xe không làm được là bịa — khác hẳn 'chưa biết'."""
    rows = baseline.rows(CAPS, responder)
    named = {name for name, _, _ in rows}
    unsupported = {n for n, d in CAPS.devices.items() if not CAPS.effective_actions(d)}
    assert unsupported and not (named & unsupported)
    assert named == set(CAPS.devices) - unsupported


@pytest.mark.parametrize("device,on", [
    ("mirror", True),        # gương bình thường là MỞ, tức không gập
    ("window", False),       # cửa kính đóng
    ("trunk", False),
    ("hvac", False),         # điều hoà tắt
    ("ambient_light", False),
])
def test_moc_xuat_phat_tung_loai(responder, device, on):
    assert state_of(baseline.rows(CAPS, responder), device).on is on


def test_khong_bia_ra_muc_hay_mode(responder):
    """Tắt thì chỉ biết là tắt. Gán sẵn 22 độ cho điều hoà đang tắt là bịa một
    thiết lập mà chưa ai đặt."""
    st = state_of(baseline.rows(CAPS, responder), "hvac")
    assert st.value is None and st.unit is None and not st.modes and st.item is None


def test_seed_thay_sach_cai_dang_giu(responder):
    provider = MockStateProvider(CAPS)
    provider._store[("hvac", "all")] = DeviceState(on=True, value=30, unit="celsius")
    provider.seed(baseline.rows(CAPS, responder))
    assert provider.get("hvac", "all") == DeviceState(on=False)


def test_song_qua_tien_trinh_khac(responder, tmp_path):
    """Hai MockStateProvider trỏ cùng file = hai tiến trình nhìn chung một xe."""
    path = tmp_path / "device-state.json"
    MockStateProvider(CAPS, path).seed(baseline.rows(CAPS, responder))
    assert MockStateProvider(CAPS, path).get("mirror", "all").on is True


# ------------------------------------------------------------------ giả lập web
def test_simulator_thay_thay_doi_tu_ngoai(tmp_path):
    path = tmp_path / "device-state.json"
    sim = Simulator(CAPS, path=path, start_at_baseline=True)
    assert sim.snapshot()["devices"]

    # "tiến trình khác" (CLI) đổi trạng thái thẳng vào file
    other = MockStateProvider(CAPS, path)
    other._store[("hvac", "all")] = DeviceState(on=True, value=26, unit="celsius")
    other._save()

    hvac = [d for d in sim.snapshot()["devices"] if d["device"] == "hvac"][0]
    assert hvac["on"] is True and hvac["value"] == 26


def test_simulator_rieng_thi_khong_dung_chung(tmp_path):
    sim = Simulator(CAPS, path=None, start_at_baseline=True)
    before = sim.snapshot()["devices"]
    MockStateProvider(CAPS, tmp_path / "khac.json").seed([])
    assert sim.snapshot()["devices"] == before


def test_nut_moc_xuat_phat(tmp_path):
    sim = Simulator(CAPS, path=tmp_path / "s.json")
    assert sim.snapshot()["devices"] == []
    assert len(sim.baseline()["devices"]) == len(baseline.rows(CAPS, sim.agent.responder))


def test_giam_dieu_hoa_tu_moc_xuat_phat(responder):
    """Lỗi thật đã gặp trên giao diện: baseline đặt điều hoà TẮT, nói "giảm điều
    hoà" thì agent báo "Đã giảm điều hòa 2 độ ạ" mà thẻ vẫn hiện "tắt" — nói một
    đằng, trạng thái một nẻo.

    Đổi 29/09 theo BA sheet 3.2 #46 (và cột Q ô Q5/Q8/Q10: lệnh MỨC lấy mặc định
    là "vùng đang BẬT"): không vùng nào bật thì KHÔNG có mặc định, phải hỏi lại
    thay vì tự bật hộ. Cái lo gốc vẫn được giữ — agent không còn báo một việc
    không xảy ra. Trả lời vùng xong thì kết cục y như cũ: bật lên, 20 độ.
    """
    provider = MockStateProvider(CAPS)
    provider.seed(baseline.rows(CAPS, responder))
    agent = Agent(CAPS, state_provider=provider)

    turn = agent.handle("giảm điều hoà 2 độ", S())
    assert not [r for r in turn.results if r.ok and r.command and not r.hoi_vung], \
        "điều hoà đang tắt mà vẫn gửi lệnh"
    assert "đang tắt" in turn.tts and "vùng nào" in turn.tts
    assert provider.get("hvac", "all").on is False, "chưa trả lời mà đã bật"

    turn = agent.handle("cả xe", S())
    assert turn.verdict == Verdict.OK
    state = provider.get("hvac", "all")
    assert state.on is True, "trả lời vùng rồi mà thiết bị vẫn tắt"
    assert state.value == 20 and state.unit == "celsius"
