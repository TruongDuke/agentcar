"""Test sinh tự động từ caps — mỗi lần caps đổi, bộ test này tự bám theo."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import caps_theo

from agentcar.caps import load_caps
from agentcar.plan import Code, RawCommand, Verdict
from agentcar.resolve import resolve, snap
from helpers import first_mode, minimal_raw

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")

PAIRS = [(d.name, a) for d in CAPS.devices.values() for a in CAPS.effective_actions(d)]
NUMERIC = [d.name for d in CAPS.devices.values() if d.has_number and CAPS.effective_actions(d)]
ZONED = [d.name for d in CAPS.devices.values() if d.zones and CAPS.effective_actions(d)]
MODED = [d.name for d in CAPS.devices.values() if d.modes and CAPS.effective_actions(d)]
UNSUPPORTED = [d.name for d in CAPS.devices.values() if not d.support]


def test_every_device_type_is_in_catalog():
    missing = [d.type for d in CAPS.devices.values() if d.type not in CAPS.catalog.types]
    assert not missing, f"type chưa khai trong caps/actions.yaml: {missing}"


def test_default_action_is_always_valid():
    for dev in CAPS.devices.values():
        if dev.default_action and dev.support and not dev.cloud_only:
            assert dev.default_action in CAPS.effective_actions(dev), dev.name


@pytest.mark.parametrize("device,action", PAIRS, ids=[f"{d}.{a}" for d, a in PAIRS])
def test_every_valid_action_resolves(device, action):
    dev = CAPS.devices[device]
    result = resolve(CAPS, minimal_raw(CAPS, dev, action))
    assert result.verdict == Verdict.OK, f"{device}.{action}: {result.code} {result.reason}"
    assert result.command.action == action


@pytest.mark.parametrize("device", UNSUPPORTED)
def test_unsupported_devices_reject_everything(device):
    dev = CAPS.devices[device]
    for action in CAPS.catalog_actions(dev) + [None]:
        result = resolve(CAPS, RawCommand(device, action=action))
        assert result.verdict == Verdict.NOT_SUPPORT


@pytest.mark.parametrize("device", ZONED)
def test_unknown_zone_always_rejected(device):
    dev = CAPS.devices[device]
    action = CAPS.effective_actions(dev)[0]
    raw = minimal_raw(CAPS, dev, action)
    raw.zone = "khong_ton_tai"
    assert resolve(CAPS, raw).code == Code.INVALID_ZONE


@pytest.mark.parametrize("device", MODED)
def test_unknown_mode_always_rejected(device):
    dev = CAPS.devices[device]
    raw = RawCommand(device, action=CAPS.effective_actions(dev)[0], mode="khong_ton_tai")
    assert resolve(CAPS, raw).code == Code.INVALID_MODE


@pytest.mark.parametrize("device", MODED)
def test_excluded_modes_never_accepted(device):
    dev = CAPS.devices[device]
    for mode in dev.exclude:
        if mode in dev.modes:
            raw = RawCommand(device, action="set_mode", mode=mode)
            assert resolve(CAPS, raw).code in (Code.MODE_EXCLUDED, Code.INVALID_ACTION)


@pytest.mark.parametrize("device", NUMERIC)
@pytest.mark.parametrize("factor", [-100, -1, 0, 0.37, 1, 2, 1000])
def test_value_in_range_lands_right(device, factor):
    """Trong [lo, hi]: luôn rơi đúng bội resolution, bất kể chính sách nào."""
    dev = CAPS.devices[device]
    if "set_level" not in CAPS.effective_actions(dev):
        pytest.skip("không có set_level")
    unit = dev.value.unit()
    asked = unit.lo + (unit.hi - unit.lo) * factor
    if not unit.lo <= asked <= unit.hi:
        pytest.skip("ca ngoài dải có test riêng cho từng chính sách")

    result = resolve(CAPS, RawCommand(device, action="set_level", value=asked))
    assert result.ok, result.reason
    assert unit.lo <= result.command.value <= unit.hi
    if unit.resolution and unit.lo < result.command.value < unit.hi:
        steps = result.command.value / unit.resolution
        assert abs(steps - round(steps)) < 1e-9, result.command.value


@pytest.mark.parametrize("device", NUMERIC)
@pytest.mark.parametrize("factor", [-100, -1, 2, 1000])
def test_ngoai_dai_theo_ba_thi_khong_ra_lenh(device, factor):
    """Chính sách `ba` (BA sheet 3.1 #1): không gửi lệnh, báo dải hợp lệ."""
    dev = CAPS.devices[device]
    if "set_level" not in CAPS.effective_actions(dev):
        pytest.skip("không có set_level")
    unit = dev.value.unit()
    asked = unit.lo + (unit.hi - unit.lo) * factor
    caps = caps_theo(CAPS, gia_tri_ngoai_dai="ba")

    result = resolve(caps, RawCommand(device, action="set_level", value=asked))
    assert result.command is None, f"{device}: {asked} ngoài dải mà vẫn ra lệnh"
    assert result.code == Code.OUT_OF_RANGE
    assert result.range_spec == (unit.lo, unit.hi, unit.name)


@pytest.mark.parametrize("device", NUMERIC)
@pytest.mark.parametrize("factor", [-100, -1, 2, 1000])
def test_ngoai_dai_theo_qc_thi_giu_nguyen_so(device, factor):
    """Chính sách `qc` (QC Sunroof E197): gửi lệnh với đúng con số đã nói."""
    dev = CAPS.devices[device]
    if "set_level" not in CAPS.effective_actions(dev):
        pytest.skip("không có set_level")
    unit = dev.value.unit()
    asked = unit.lo + (unit.hi - unit.lo) * factor
    caps = caps_theo(CAPS, gia_tri_ngoai_dai="qc")

    result = resolve(caps, RawCommand(device, action="set_level", value=asked))
    assert result.ok, result.reason
    assert result.command.value == snap(asked, unit), "chỉ được snap, không được cắt về dải"


@pytest.mark.parametrize("device", [d.name for d in CAPS.devices.values() if not d.readable and not d.query_only])
def test_unreadable_devices_reject_query(device):
    result = resolve(CAPS, RawCommand(device, action="query"))
    assert result.verdict != Verdict.OK
