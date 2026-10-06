"""Mốc xuất phát: xe vừa nổ máy, chưa ai bật gì.

MockStateProvider chỉ biết những gì chính agent đã đặt, nên lúc mới chạy thì 30
thiết bị đều "chưa biết" — bảng trạng thái gần như trống, không có gì để theo dõi.
Thực tế xe nào cũng có một mốc xuất phát: đèn tắt, cửa đóng, gương mở.

Trạng thái suy từ catalog chứ không khai tay cho từng thiết bị, đúng lối
Responder.state_kind: thêm thiết bị mới vào caps thì nó tự có mốc xuất phát.

Thiết bị caps khai là không hỗ trợ thì KHÔNG nạp: nói "đang tắt" về một thứ xe
không làm được là bịa, khác hẳn với thú nhận "chưa biết".
"""
from __future__ import annotations

from typing import Optional

from .caps import Caps
from .respond import Responder
from .state import DeviceState

Row = tuple[str, Optional[str], DeviceState]

# on=True nghĩa là gì thì tuỳ loại (xem DeviceState). Gương "bình thường" là MỞ,
# tức không gập — nên nó là loại duy nhất xuất phát ở True.
_NORMAL_ON = {"fold": True}


def rows(caps: Caps, responder: Responder) -> list[Row]:
    out: list[Row] = []
    for name, dev in caps.devices.items():
        if not caps.effective_actions(dev):
            continue
        kind = responder.state_kind(dev)
        out.append((name, dev.default_zone, DeviceState(on=_NORMAL_ON.get(kind, False))))
    return out


def describe(caps: Caps, responder: Responder) -> str:
    counted = len(rows(caps, responder))
    return f"đã đặt {counted}/{len(caps.devices)} thiết bị về mốc xuất phát (đèn tắt, cửa đóng, gương mở)"
