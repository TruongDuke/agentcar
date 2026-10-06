"""Sinh command tối thiểu hợp lệ cho mọi (device, action) — dùng chung cho test."""
from __future__ import annotations

from typing import Optional

from agentcar.caps import Caps, Device
from agentcar.catalog import VALUE_ACTIONS
from agentcar.plan import RawCommand


def first_mode(dev: Device) -> Optional[str]:
    return next((m for m in dev.modes if m not in dev.exclude), None)


def mid_value(dev: Device) -> Optional[float]:
    if dev.value is None or not dev.value.is_number:
        return None
    unit = dev.value.unit()
    return None if unit is None else (unit.lo + unit.hi) / 2


def minimal_raw(caps: Caps, dev: Device, action: str) -> RawCommand:
    raw = RawCommand(device=dev.name, action=action)
    if action in VALUE_ACTIONS and dev.has_number:
        raw.value = mid_value(dev)
    if action in ("set_mode", "clear_mode"):
        raw.mode = first_mode(dev)
    if caps.catalog.spec(dev.type).mode_as_action and action == "turn_off":
        raw.mode = first_mode(dev)  # D3: tắt scene phải nói rõ scene nào
    if dev.has_items and action in ("open", "close"):
        raw.item = next(iter(dev.items))
    return raw
