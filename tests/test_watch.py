"""Bảng trạng thái thiết bị trong terminal."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.agent import Agent
from agentcar.caps import load_caps
from agentcar.lexicon import load_lexicon
from agentcar.respond import Responder
from agentcar.safety import VehicleState as S
from agentcar.watch import render, rows

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")


@pytest.fixture(scope="module")
def responder():
    return Responder(CAPS, load_lexicon(CAPS))


def slot(device, zone=None, **kw):
    base = {"device": device, "zone": zone, "on": None, "value": None,
            "unit": None, "modes": {}, "item": None}
    base.update(kw)
    return base


def draw(responder, snapshot, **kw):
    return render(CAPS, responder, snapshot, **kw)[0]


def test_slot_rong_khong_chiem_dong(responder):
    snapshot = [slot("hvac", "all", on=True), slot("hvac", "driver")]
    assert "hvac/driver" not in draw(responder, snapshot)
    assert "hvac/driver" in draw(responder, snapshot, show_all=True)


@pytest.mark.parametrize("device,on,word", [
    ("window", True, "mở"), ("window", False, "đóng"),
    ("mirror", True, "mở"), ("mirror", False, "gập"),
    ("hvac", True, "bật"), ("hvac", False, "tắt"),
])
def test_chu_theo_loai_thiet_bi(responder, device, on, word):
    """Cùng một on=True mà cửa kính là 'mở', gương là 'mở' (đối với gập), điều hoà
    là 'bật' — chữ suy từ catalog chứ không khai tay cho từng thiết bị."""
    line = [r for r in rows(CAPS, responder, [slot(device, "all", on=on)])][0]
    assert line.value == word


def test_doc_don_vi_xuoi_tieng_viet(responder):
    snapshot = [slot("hvac", "all", on=True, value=22, unit="celsius"),
                slot("seat_heating", "driver", on=True, value=2, unit="level")]
    text = draw(responder, snapshot)
    assert "22 độ" in text and "mức 2" in text


def test_dem_theo_thiet_bi_khong_theo_vung(responder):
    snapshot = [slot("window", "rear_left", on=True), slot("window", "rear_right", on=True)]
    assert f"1/{len(CAPS.devices)}" in draw(responder, snapshot)


def test_danh_dau_dong_vua_doi(responder):
    before = [slot("window", "all", on=True), slot("hvac", "all", on=True)]
    after = [slot("window", "all", on=False), slot("hvac", "all", on=True)]

    first, previous = render(CAPS, responder, before)
    assert "▸" not in first          # lần vẽ đầu chưa có gì để so

    second, _ = render(CAPS, responder, after, previous=previous)
    marked = [ln for ln in second.splitlines() if ln.startswith("▸")]
    assert len(marked) == 1 and "window" in marked[0]


def test_chua_co_gi_thi_noi_ra(responder):
    assert "chưa thiết bị nào được đặt" in draw(responder, [])


def test_kem_dong_tin_hieu_xe(responder):
    text = draw(responder, [], vehicle=S(gear="D", speed_kmh=40))
    assert "gear=D" in text and "speed_kmh=40" in text


def test_ve_duoc_trang_thai_that_tu_agent(responder):
    """Không chỉ dựng dict bằng tay — snapshot thật của agent phải vẽ ra được."""
    agent = Agent(CAPS)
    for line in ("bật sưởi ghế lái mức 2", "mở cửa kính", "điều hoà 22 độ"):
        agent.handle(line, S())
    text = draw(responder, agent.devices.snapshot())
    assert "sưởi ghế" in text and "cửa kính" in text and "điều hòa" in text
