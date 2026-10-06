"""Luật suy luận: nạp từ dữ liệu, lọc theo caps, sinh phần prompt.

Trước đây mấy luật này là văn xuôi viết tay trong prompt — trùng lặp mà không ai
thấy, trỏ tới thiết bị không tồn tại mà không ai kiểm. Ở đây chúng là dữ liệu:
lọc được theo từng dòng xe, linter kiểm được, và thêm luật không phải sửa prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .caps import Caps

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "caps" / "reasoning.vi.yaml"


@dataclass(frozen=True)
class Rule:
    kind: str                  # sensations | situations
    cues: tuple[str, ...]
    device: str
    action: Optional[str] = None
    mode: Optional[str] = None
    index: int = 0

    @property
    def cue_text(self) -> str:
        return " / ".join(self.cues)

    def target(self, caps: Caps) -> str:
        """Phần model phải xuất ra. Phụ thuộc caps vì thiết bị kiểu mode_as_action
        (scene_mode) dùng TÊN MODE làm action, không có set_mode."""
        if not self.mode:
            return f"{self.device} {self.action}"
        dev = caps.devices.get(self.device)
        if dev is not None and caps.catalog.spec(dev.type).mode_as_action:
            return f"{self.device} {self.mode}"
        return f"{self.device} set_mode {self.mode}"


@dataclass
class RuleSet:
    rules: list[Rule] = field(default_factory=list)
    ambiguous: tuple[str, ...] = ()
    vague: tuple[str, ...] = ()
    answer_knowledge: bool = True
    needs_live_data: tuple[str, ...] = ()
    route_to: Optional[str] = None      # trợ lý chung nhận câu hỏi ngoài miền xe
    city: str = "Hà Nội"                # vị trí tạm khai, dùng cho thời tiết
    path: Optional[Path] = None

    def of(self, kind: str) -> list[Rule]:
        return [r for r in self.rules if r.kind == kind]


def load_rules(path: Path | str = DEFAULT_PATH) -> RuleSet:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules: list[Rule] = []
    for kind in ("sensations", "situations"):
        for i, row in enumerate(raw.get(kind) or []):
            cues = tuple(c.strip() for c in str(row.get("cue", "")).split(",") if c.strip())
            rules.append(Rule(kind=kind, cues=cues, device=str(row.get("device", "")),
                              action=row.get("action"), mode=row.get("mode"), index=i))
    knowledge = raw.get("knowledge") or {}
    return RuleSet(rules=rules, ambiguous=tuple(raw.get("ambiguous") or []),
                   vague=tuple(raw.get("vague_references") or []),
                   answer_knowledge=bool(knowledge.get("answer_from_knowledge", True)),
                   route_to=knowledge.get("route_to") or None,
                   city=knowledge.get("city") or "Hà Nội",
                   needs_live_data=tuple(knowledge.get("needs_live_data") or []),
                   path=Path(path))


def check(caps: Caps, rule: Rule) -> Optional[str]:
    """Lý do luật không dùng được với dòng xe này, None nếu hợp lệ."""
    if not rule.cues:
        return "không có cue nào"
    dev = caps.devices.get(rule.device)
    if dev is None:
        return f"không có thiết bị '{rule.device}'"
    actions = caps.effective_actions(dev)
    if not actions:
        return f"'{rule.device}' không dùng được trên xe này"
    if rule.mode:
        if rule.mode not in dev.modes or rule.mode in dev.exclude:
            return f"'{rule.device}' không có mode '{rule.mode}'"
        # mode_as_action: chính tên mode là action (scene_mode camp/pet/wash)
        needed = (rule.mode if caps.catalog.spec(dev.type).mode_as_action else "set_mode")
        if needed not in actions:
            return f"'{rule.device}' không đặt được mode '{rule.mode}'"
    elif rule.action:
        if rule.action not in actions:
            return f"'{rule.device}' không có action '{rule.action}'"
    else:
        return "thiếu cả action và mode"
    return None


def applicable(caps: Caps, rule_set: RuleSet) -> tuple[list[Rule], list[tuple[Rule, str]]]:
    """Chia luật thành (dùng được, bị loại kèm lý do) cho đúng dòng xe này."""
    kept, dropped = [], []
    for rule in rule_set.rules:
        why = check(caps, rule)
        (dropped.append((rule, why)) if why else kept.append(rule))
    return kept, dropped


def duplicates(caps: Caps, rule_set: RuleSet) -> list[str]:
    """Cue trùng nhau — thứ mà văn xuôi không bao giờ cho thấy."""
    seen: dict[str, str] = {}
    clashes = []
    for rule in rule_set.rules:
        target = rule.target(caps)
        for cue in rule.cues:
            key = cue.lower()
            if key in seen and seen[key] != target:
                clashes.append(f"'{cue}': {seen[key]} vs {target}")
            seen[key] = target
    return clashes


def render(caps: Caps, rule_set: RuleSet) -> str:
    """Phần luật trong prompt, sinh từ dữ liệu đã lọc theo caps."""
    kept, _ = applicable(caps, rule_set)
    blocks = []

    sensations = [r for r in kept if r.kind == "sensations"]
    if sensations:
        lines = "\n".join(f'    "{r.cue_text}" -> {r.target(caps)}' for r in sensations)
        blocks.append("- Câu tả CẢM GIÁC thì suy ĐÚNG CHIỀU: người ta muốn THOÁT KHỎI "
                      f"trạng thái đang có.\n{lines}")

    situations = [r for r in kept if r.kind == "situations"]
    if situations:
        lines = "\n".join(f'    "{r.cue_text}" -> {r.target(caps)}' for r in situations)
        blocks.append(f"- Câu tả HOÀN CẢNH thì suy ra việc cần làm.\n{lines}")

    if rule_set.vague:
        words = ", ".join(f'"{w}"' for w in rule_set.vague)
        blocks.append(f"- Mấy chữ {words} là tham chiếu mơ hồ. Nếu ngữ cảnh không đủ "
                      "để biết đang nói tới thiết bị nào thì dùng ask, ĐỪNG đoán.")

    if rule_set.ambiguous:
        words = ", ".join(f'"{w}"' for w in rule_set.ambiguous)
        blocks.append(f"- Mấy chữ {words} là tên gọi chung cho nhiều thiết bị — dùng "
                      "ask để hỏi lại, KHÔNG tự chọn một cái.")

    if rule_set.route_to:
        blocks.append(f'- Câu KHÔNG phải lệnh điều khiển (hỏi kiến thức, tán gẫu) thì dùng '
                      f'route: "{rule_set.route_to}". ĐỪNG tự trả lời — đã có bên khác lo.')
    elif rule_set.answer_knowledge:
        blocks.append("- Câu KHÔNG phải lệnh điều khiển (hỏi kiến thức, tán gẫu) thì vẫn "
                      "trả lời bằng reply, ngắn gọn 1-2 câu. Đừng từ chối máy móc.")
    if rule_set.needs_live_data:
        topics = ", ".join(rule_set.needs_live_data)
        blocks.append(f"- NHƯNG mấy chủ đề cần số liệu cập nhật theo thời gian ({topics}) "
                      "thì bạn KHÔNG biết: nói rõ là chưa xem được, TUYỆT ĐỐI không bịa "
                      "số liệu. Trạng thái xe thì dùng action query, đừng đoán.")

    return "\n".join(blocks)
