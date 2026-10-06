"""Safety sweep — sinh test từ chính caps: mỗi rule 2 ca (thoả / không thoả)."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.caps import load_caps
from agentcar.engine import decide
from agentcar.plan import RawCommand, Verdict
from agentcar.safety import VehicleState, parse_when

from helpers import minimal_raw

ROOT = Path(__file__).resolve().parent.parent

CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
RULES = list(CAPS.safety)


def _violating(value):
    """Giá trị làm điều kiện SAI (dùng cho op '==')."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    return {"P": "D", "engaged": "released"}.get(value, value + "_other")


def satisfying_state(cond) -> VehicleState:
    """State mặc định (xe đỗ an toàn) chỉ đổi đúng 1 trường để rule kích hoạt."""
    if cond.op == "==":
        v = cond.value
    elif cond.op == "!=":
        v = _violating(cond.value)
    elif cond.op == ">":
        v = cond.value + 1
    elif cond.op == ">=":
        v = cond.value
    elif cond.op == "<":
        v = cond.value - 1
    else:  # <=
        v = cond.value
    # dang_chay là tín hiệu DẪN XUẤT (gộp gear + speed), không gán thẳng được.
    if cond.field == "dang_chay":
        return VehicleState(gear="D") if v else VehicleState()
    return VehicleState(**{cond.field: v})


def rule_command(rule) -> RawCommand:
    dev = CAPS.devices[rule.device]
    action = "open" if rule.is_wildcard else rule.action
    return minimal_raw(CAPS, dev, action)


def _id(rule):
    return f"{rule.index:02d}-{rule.device}-{rule.action}-{rule.when.replace(' ', '')}"


@pytest.mark.parametrize("rule", RULES, ids=[_id(r) for r in RULES])
def test_rule_fires_when_condition_holds(rule):
    cond = parse_when(rule.when)
    result = decide(CAPS, rule_command(rule), satisfying_state(cond))
    assert result.verdict == rule.verdict
    assert result.reason == rule.reason


@pytest.mark.parametrize("rule", RULES, ids=[_id(r) for r in RULES])
def test_rule_silent_in_safe_state(rule):
    result = decide(CAPS, rule_command(rule), VehicleState())
    assert result.verdict == Verdict.OK, result.reason


def test_deny_wins_over_confirm(caps):
    """scene_mode/camp: pin thấp (DENY) thắng mọi verdict nhẹ hơn."""
    r = decide(caps, RawCommand("scene_mode", action="camp"), VehicleState(gear="D", battery_pct=10))
    assert r.verdict == Verdict.DENY


def test_query_bypasses_safety(caps):
    """charge_port có rule action:'*' — query vẫn phải đi qua được."""
    assert decide(caps, RawCommand("charge_port", action="query"), VehicleState(speed_kmh=60)).ok


def test_wildcard_covers_control_actions(caps):
    for action in ("open", "close"):
        r = decide(caps, RawCommand("charge_port", action=action), VehicleState(speed_kmh=1))
        assert r.verdict == Verdict.DENY


def _thieu(*ten):
    class Thieu(VehicleState):
        def get(self, name):
            if name in ten:
                raise KeyError(name)
            return super().get(name)
    return Thieu


def test_missing_signal_skips_rule(caps):
    """Thiếu HẾT tín hiệu thì rule bỏ qua VÀ nói ra là thiếu, không đoán bừa."""
    r = decide(caps, RawCommand("window", action="open"), _thieu("gear", "speed_kmh")())
    assert r.ok and any("thiếu tín hiệu" in n for n in r.notes)


def test_one_missing_signal_still_guards():
    """Mất tín hiệu cần số mà bánh vẫn quay thì tầng an toàn PHẢI còn chặn.

    Trước đây 13 luật treo hết vào `gear != P`, nên số P (hoặc tín hiệu số hỏng)
    ở 72 km/h là cốp trước, cốp sau, cửa kính, cửa sổ trời mở được tất.
    """
    chay = _thieu("gear")(speed_kmh=72)
    assert decide(CAPS, RawCommand("trunk", action="open"), chay).verdict == Verdict.DENY
    assert decide(CAPS, RawCommand("frunk", action="open"), chay).verdict == Verdict.DENY


def test_parked_gear_does_not_excuse_a_moving_car():
    """Số P mà 72 km/h là tín hiệu mâu thuẫn — chọn phía chặt hơn."""
    mau_thuan = VehicleState(gear="P", speed_kmh=72)
    assert decide(CAPS, RawCommand("trunk", action="open"), mau_thuan).verdict == Verdict.DENY
    assert decide(CAPS, RawCommand("window", action="open"), mau_thuan).verdict == Verdict.CONFIRM
    # và xe đỗ thật thì vẫn cho qua
    assert decide(CAPS, RawCommand("trunk", action="open"), VehicleState()).ok


def test_safety_gated_devices_all_have_rules(caps):
    """Device khai safety_gated thì phải có ít nhất 1 rule, nếu không là khai thừa."""
    gated = {d.name for d in caps.devices.values() if d.safety_gated}
    covered = {r.device for r in caps.safety}
    assert gated <= covered, f"safety_gated nhưng không có rule: {gated - covered}"
