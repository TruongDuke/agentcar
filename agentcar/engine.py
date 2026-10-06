"""Nối tầng [3] và [4]. Tầng hiểu (grammar/LLM) sẽ gọi vào đây."""
from __future__ import annotations

from .caps import Caps
from .plan import RawCommand, Result, Verdict
from .resolve import resolve
from .safety import VehicleState, evaluate


def decide(caps: Caps, raw: RawCommand, state: VehicleState | None = None,
           confirmed: bool = False) -> Result:
    res = resolve(caps, raw)
    if res.verdict != Verdict.OK or res.command is None:
        return res
    out = evaluate(caps, res.command, state or VehicleState(), confirmed=confirmed)
    out.notes = res.notes + out.notes
    # Tầng an toàn dựng Result MỚI nên cờ do resolve đặt bị rơi. Chép sang, nếu
    # không thì "vùng do mặc định hay do người dùng nêu" mất ngay tại đây.
    out.zone_mac_dinh = res.zone_mac_dinh
    return out
