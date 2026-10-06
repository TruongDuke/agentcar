"""Bảng trạng thái thiết bị để xem trong terminal.

`serve` đã vẽ được cái này trong trình duyệt, nhưng phải mở tab và bấm. Khi đang
gõ câu trong repl ở một cửa sổ, thứ cần là một cửa sổ khác nằm im và tự cập nhật.

MockStateProvider ghi ra logs/device-state.json để trạng thái sống qua nhiều tiến
trình, nên bảng này đọc thẳng file đó: `agentcar repl` ở cửa sổ này, `agentcar
devices --watch` ở cửa sổ kia, hai tiến trình khác nhau vẫn thấy chung một xe.

Thiết bị người dùng chưa đụng tới thì KHÔNG hiện — MockStateProvider chỉ biết
những gì chính agent đã đặt, in ra 30 dòng "chưa biết" chỉ tổ che mất 3 dòng có
nghĩa. Muốn thấy hết thì --all.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .caps import Caps
from .lexicon import DEVICE, ITEM, MODE, UNIT, ZONE
from .respond import Responder
from .safety import VehicleState

CHANGED = "▸"       # đánh dấu dòng vừa đổi so với lần vẽ trước
UNKNOWN = "chưa biết"   # slot rỗng và thiết bị chưa đụng tới đều là không có tin

# Chữ cho state.on, tuỳ loại thiết bị — cùng một `on=True` mà cửa kính là "mở",
# gương là "mở" (đối lập với gập), điều hoà là "bật".
_WORDS = {
    "aperture": ("mở", "đóng"),
    "fold": ("mở", "gập"),
    "switch": ("bật", "tắt"),
    "level": ("bật", "tắt"),
    "item": ("bật", "tắt"),
    "scene": ("bật", "tắt"),
}


@dataclass(frozen=True)
class Row:
    key: str            # device/zone, để so hai lần vẽ với nhau
    label: str          # tên tiếng Việt
    ident: str          # device/zone dạng kỹ thuật
    value: str          # trạng thái đọc ra

    def line(self, changed: bool) -> str:
        mark = CHANGED if changed else " "
        return f"{mark} {self.label:<24} {self.ident:<26} {self.value}"


def _describe(responder: Responder, caps: Caps, st: dict[str, Any]) -> str:
    dev = caps.devices.get(st["device"])
    if dev is None:
        return UNKNOWN
    kind = responder.state_kind(dev)
    bits: list[str] = []

    modes = [responder.name_of(MODE, m) for m in st["modes"].values()]
    if st["on"] is not None and not (kind == "scene" and modes):
        on_word, off_word = _WORDS.get(kind, _WORDS["switch"])
        bits.append(on_word if st["on"] else off_word)
    bits += modes
    if st["value"] is not None:
        unit = responder.name_of(UNIT, st["unit"]) if st["unit"] else ""
        # "mức 2" đọc xuôi, "22 độ" cũng đọc xuôi — khác nhau chỗ đặt đơn vị.
        number = f"{st['value']:g}"
        bits.append(f"{unit} {number}" if unit == "mức" else f"{number} {unit}".strip())
    if st["item"]:
        bits.append(responder.name_of(ITEM, st["item"]))
    return "  ".join(bits) or UNKNOWN


def known(st: dict[str, Any]) -> bool:
    """Slot rỗng vẫn bị ghi ra file — apply() tạo slot trước rồi mới biết là không
    suy ra được gì (tăng mức trong khi chưa biết mức cũ). In ra thì chỉ tổ chiếm dòng.
    """
    return not (st["on"] is None and st["value"] is None
                and not st["modes"] and st["item"] is None)


def rows(caps: Caps, responder: Responder, snapshot: list[dict[str, Any]],
         show_all: bool = False) -> list[Row]:
    seen = {st["device"] for st in snapshot if known(st)}
    out: list[Row] = []
    for st in snapshot:
        if not known(st) and not show_all:
            continue
        device, zone = st["device"], st["zone"]
        dev = caps.devices.get(device)
        label = responder.name_of(DEVICE, device)
        if zone and dev is not None and zone != dev.default_zone:
            label += " · " + responder.name_of(ZONE, zone, device=device)
        out.append(Row(key=f"{device}/{zone or ''}", label=label,
                       ident=f"{device}/{zone or '-'}", value=_describe(responder, caps, st)))
    if show_all:
        for name in caps.devices:
            if name not in seen:
                out.append(Row(key=f"{name}/", label=responder.name_of(DEVICE, name),
                               ident=f"{name}/-", value=UNKNOWN))
    return out


def render(caps: Caps, responder: Responder, snapshot: list[dict[str, Any]],
           vehicle: Optional[VehicleState] = None, previous: Optional[list[Row]] = None,
           show_all: bool = False, stamp: str = "") -> tuple[str, list[Row]]:
    """Trả về (text để in, rows để so ở lần vẽ sau)."""
    current = rows(caps, responder, snapshot, show_all=show_all)
    was = {r.key: r.value for r in (previous or [])}
    # Lần vẽ đầu chưa có gì để so, đánh dấu tất cả thì thành nhiễu.
    first = previous is None

    count = len({st["device"] for st in snapshot if known(st)})
    head = f"{caps.model} — {count}/{len(caps.devices)} thiết bị đang biết trạng thái"
    lines = [f"{head}{('   ' + stamp) if stamp else ''}"]
    if vehicle is not None:
        lines.append(f"  {vehicle.describe()}")
    lines.append("")
    if not current:
        lines.append("  chưa thiết bị nào được đặt — nói một câu rồi xem lại")
    for row in current:
        lines.append(row.line(changed=not first and was.get(row.key) != row.value))
    return "\n".join(lines), current
