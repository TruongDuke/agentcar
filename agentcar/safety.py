"""Tầng [4] — policy an toàn theo trạng thái xe."""
from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .caps import Caps, SafetyRule
from .catalog import QUERY
from .plan import Code, Command, Result, Verdict

_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}
_ORDERING = (">=", "<=", ">", "<")
_WHEN_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(.+?)\s*$")

DEFAULT_STATE_FIELDS = ("gear", "speed_kmh", "battery_pct", "charging", "parking_brake")


@dataclass
class VehicleState:
    """Trạng thái xe. Mặc định = xe đỗ an toàn, để test không bị chặn ngoài ý muốn."""

    gear: str = "P"
    speed_kmh: float = 0.0
    battery_pct: float = 100.0
    charging: bool = False
    parking_brake: str = "engaged"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def dang_chay(self) -> bool:
        """Xe KHÔNG đứng yên — hoặc cần số rời P, hoặc bánh còn quay.

        Trước đây 13 luật an toàn viết `gear != P`, tức là treo toàn bộ phán đoán
        "xe đang chạy" lên MỘT tín hiệu. Đặt số P mà tốc độ 72 km/h thì cốp trước,
        cốp sau, cửa kính, cửa sổ trời đều mở được — chỉ hai luật có nhìn tốc độ
        (gập gương, nắp sạc) là chặn. Trong xe thật P ở 72 km/h không xảy ra, nên
        đây là chuyện tín hiệu số bị sai hoặc cũ, mà tầng an toàn chính là lớp
        phải đứng vững khi tín hiệu sai. Gộp hai tín hiệu lại: chặt hơn, không
        bao giờ lỏng hơn.

        Thiếu tín hiệu nào thì coi như tín hiệu đó không nói gì, y như Condition
        xử lý KeyError — nhưng ở đây tín hiệu CÒN LẠI vẫn chặn được.

        Đọc qua `get()` chứ không đọc thẳng thuộc tính: thiếu tín hiệu nào thì
        tín hiệu đó không được quyền nói "xe đang đỗ" bằng giá trị mặc định.
        Thiếu CẢ HAI thì ném KeyError, đúng như một trường không tồn tại — rule
        bỏ qua và ghi chú "thiếu tín hiệu", y hệt nết cũ.
        """
        co = False
        for ten, dang_chay in (("gear", lambda v: v != "P"),
                               ("speed_kmh", lambda v: (v or 0) > 0)):
            try:
                gia_tri = self.get(ten)
            except KeyError:
                continue
            co = True
            if dang_chay(gia_tri):
                return True
        if not co:
            raise KeyError("gear/speed_kmh")
        return False

    def get(self, name: str) -> Any:
        if hasattr(self, name) and name != "extra":
            return getattr(self, name)
        if name in self.extra:
            return self.extra[name]
        raise KeyError(name)

    def describe(self) -> str:
        base = " ".join(f"{f}={self.get(f)}" for f in DEFAULT_STATE_FIELDS)
        extra = " ".join(f"{k}={v}" for k, v in self.extra.items())
        return f"{base} {extra}".strip()


@dataclass(frozen=True)
class Condition:
    field: str
    op: str
    value: Any
    raw: str

    def holds(self, state: VehicleState) -> bool:
        try:
            actual = state.get(self.field)
        except KeyError:
            return False  # thiếu tín hiệu -> rule không kích hoạt (xem note ở evaluate)
        if self.op in _ORDERING and not (
            isinstance(actual, (int, float)) and isinstance(self.value, (int, float))
        ):
            return False
        return _OPS[self.op](actual, self.value)


def _literal(text: str) -> Any:
    text = text.strip().strip('"').strip("'")
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


def parse_when(expr: str) -> Condition:
    m = _WHEN_RE.match(expr or "")
    if not m:
        raise ValueError(f"không parse được điều kiện: {expr!r}")
    field_name, op, rhs = m.groups()
    return Condition(field=field_name, op=op, value=_literal(rhs), raw=expr)


def rule_condition(rule: SafetyRule) -> Condition:
    return parse_when(rule.when)


def evaluate(caps: Caps, command: Command, state: VehicleState, confirmed: bool = False) -> Result:
    """DENY thắng CONFIRM; không rule nào khớp thì OK.

    Query đi thẳng, trừ khi có rule ghi đích danh action: query (xem Caps.rules_for).
    """
    notes: list[str] = []
    hits: list[tuple[SafetyRule, Condition]] = []

    for rule in caps.rules_for(command.device, command.action):
        cond = rule_condition(rule)
        try:
            state.get(cond.field)
        except KeyError:
            notes.append(f"thiếu tín hiệu '{cond.field}' -> bỏ qua rule #{rule.index}")
            continue
        if cond.holds(state):
            hits.append((rule, cond))

    wanted = [(Verdict.DENY, Code.SAFETY_DENY)]
    if not confirmed:
        wanted.append((Verdict.CONFIRM, Code.NEED_CONFIRM))
    for verdict, code in wanted:
        for rule, cond in hits:
            if rule.verdict == verdict:
                return Result(
                    verdict=verdict,
                    command=command,
                    code=code,
                    reason=rule.reason,
                    notes=notes + [f"rule #{rule.index}: {rule.device}/{rule.action} when {cond.raw}"],
                )

    if confirmed and any(r.verdict == Verdict.CONFIRM for r, _ in hits):
        notes.append("người dùng đã xác nhận; trạng thái xe được kiểm lại tại thời điểm đồng ý")
    if command.action == QUERY:
        notes.append("query: bỏ qua safety")
    return Result(verdict=Verdict.OK, command=command, notes=notes)
