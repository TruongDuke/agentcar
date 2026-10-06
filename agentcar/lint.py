"""Linter cho caps — bắt mâu thuẫn trước khi nó thành bug runtime.

Chạy lại mỗi lần sửa caps hoặc thêm dòng xe mới.
"""
from __future__ import annotations

from dataclasses import dataclass

from typing import Optional

from .caps import Caps, Device
from .catalog import QUERY
from .lexicon import Lexicon, coverage
from .reasoning import RuleSet, applicable, duplicates, load_rules
from .safety import parse_when

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"
_ORDER = {ERROR: 0, WARN: 1, INFO: 2}


@dataclass(frozen=True)
class Finding:
    level: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level:<5} {self.where:<18} {self.message}"


def _numeric_units(device: Device):
    if device.value is None or not device.value.is_number:
        return []
    return list(device.value.units.values())


def lint(caps: Caps, lex: Optional[Lexicon] = None,
         rules: Optional[RuleSet] = None) -> list[Finding]:
    out: list[Finding] = []
    add = lambda lvl, where, msg: out.append(Finding(lvl, where, msg))

    unnamed: list[str] = []
    no_default: list[str] = []
    unsupported: list[str] = []

    for name, dev in caps.devices.items():
        if dev.type not in caps.catalog.types:
            add(ERROR, name, f"type '{dev.type}' chưa có trong caps/actions.yaml")
            continue
        spec = caps.catalog.spec(dev.type)
        cat_actions = caps.catalog_actions(dev)

        if not dev.support:
            unsupported.append(name)
        if dev.cloud_only:
            add(INFO, name, "cloud_only → không resolve ở edge, escalate thẳng")
        if not dev.support and dev.query_only:
            add(WARN, name, "support:false + query_only → thiết bị không dùng được bằng đường nào")
        if not dev.names.get("vi"):
            unnamed.append(name)
        if dev.default_action is None and dev.support and not dev.cloud_only:
            no_default.append(name)

        # exclude
        for ex in dev.exclude:
            if ex in dev.modes:
                add(WARN, name, f"'{ex}' vừa nằm trong modes vừa nằm trong actions.exclude — "
                                f"theo D2 thì exclude thắng, trả VA_MODE_EXCLUDED")
            elif ex not in spec.actions:
                add(WARN, name, f"actions.exclude có '{ex}' nhưng type '{dev.type}' vốn không có action đó")

        # value ranges
        for unit in _numeric_units(dev):
            span = unit.hi - unit.lo
            if unit.resolution and span % unit.resolution != 0:
                add(WARN, name, f"{unit.name}: resolution={unit.resolution} không chia hết dải {unit.lo}..{unit.hi}")
            if unit.nudge and unit.nudge > span:
                add(WARN, name, f"{unit.name}: nudge={unit.nudge} lớn hơn cả dải giá trị")
            if unit.lo > 0:
                if "close" in cat_actions:
                    add(WARN, name, f"{unit.name}: lo={unit.lo} → set_level(0) không hợp lệ, 'đóng hẳn' phải dùng action close")
                elif "turn_off" in cat_actions:
                    add(INFO, name, f"{unit.name}: lo={unit.lo} → mức 0 phải map sang turn_off")

        # zone gộp và zone lẻ cùng tồn tại
        for agg in ("rear", "front"):
            if agg in dev.zones and any(z.startswith(agg + "_") for z in dev.zones):
                lanes = [z for z in dev.zones if z.startswith(agg + "_")]
                add(INFO, name, f"zone '{agg}' tồn tại cùng {lanes} — cần rule rõ khi người dùng nói chung chung")

        # action đề xuất chưa có bằng chứng trong caps
        for a in spec.proposed_actions:
            if a in cat_actions:
                add(INFO, name, f"action '{a}' là đề xuất của catalog, caps không có bằng chứng — cần xác nhận")

        # item trỏ tới thiết bị không hỗ trợ
        for item_key in dev.items:
            for other, odev in caps.devices.items():
                if odev.support:
                    continue
                if item_key == other or item_key.startswith(other + "_"):
                    add(WARN, name, f"item '{item_key}' trỏ tới thiết bị '{other}' đang support:false")

    # ---------------- safety
    modes_with_rule: dict[str, set[str]] = {}
    for rule in caps.safety:
        where = f"safety#{rule.index}"
        dev = caps.devices.get(rule.device)
        if dev is None:
            add(ERROR, where, f"rule trỏ tới thiết bị '{rule.device}' không có trong caps")
            continue
        try:
            parse_when(rule.when)
        except ValueError as e:
            add(ERROR, where, str(e))
        if rule.verdict not in ("DENY", "CONFIRM"):
            add(ERROR, where, f"verdict '{rule.verdict}' không hợp lệ")
        if not rule.reason:
            add(WARN, where, "rule không có reason → không có câu trả lời cho người dùng")

        actions = caps.effective_actions(dev)
        if rule.is_wildcard:
            add(INFO, where, f"action '*' expand thành {caps.wildcard_expansion(rule)} (query được bỏ qua)")
        elif rule.action not in actions:
            add(ERROR, where, f"{rule.device}: action '{rule.action}' không nằm trong {actions}")

        if rule.action in dev.modes:
            modes_with_rule.setdefault(rule.device, set()).add(rule.action)

    for dname, covered in modes_with_rule.items():
        dev = caps.devices[dname]
        missing = [m for m in dev.modes if m not in covered]
        if missing:
            add(WARN, dname, f"mode có rule an toàn: {sorted(covered)}; chưa có rule: {missing}")

    # ---------------- tổng hợp
    if unsupported:
        add(INFO, "caps", f"support:false ({len(unsupported)}): {unsupported} → mọi action trả VA_NOT_SUPPORT")
    if no_default:
        add(INFO, "caps", f"không có default_action ({len(no_default)}): {no_default} → câu nói phải nêu rõ action")
    if unnamed and lex is None:
        add(INFO, "lexicon", f"{len(unnamed)}/{len(caps.devices)} device không có names.vi trong caps "
                             f"— phải bù bằng caps/lexicon.vi.yaml: {unnamed}")

    out += _lint_reasoning(caps, rules if rules is not None else load_rules())

    for key, what in caps.catalog.provisional():
        add(INFO, "catalog", f"{key} còn tạm chốt: {what}")

    if lex is not None:
        out += _lint_lexicon(caps, lex)

    out.sort(key=lambda f: (_ORDER[f.level], f.where))
    return out


def _lint_reasoning(caps: Caps, rule_set: RuleSet) -> list[Finding]:
    """Luật suy luận trỏ tới thiết bị không có thì phải báo NGAY, đừng để nó nằm
    trong prompt dạy model làm việc xe không làm được."""
    out: list[Finding] = []
    kept, dropped = applicable(caps, rule_set)
    for rule, why in dropped:
        out.append(Finding(WARN, "reasoning", f"luật '{rule.cue_text}' bị loại khỏi prompt: {why}"))
    for clash in duplicates(caps, rule_set):
        out.append(Finding(ERROR, "reasoning", f"cue trùng nhau, đích khác nhau — {clash}"))
    out.append(Finding(INFO, "reasoning",
                       f"{len(kept)}/{len(rule_set.rules)} luật vào prompt của {caps.model}"))
    return out


def _lint_lexicon(caps: Caps, lex: Lexicon) -> list[Finding]:
    out: list[Finding] = []
    add = lambda lvl, where, msg: out.append(Finding(lvl, where, msg))

    gaps = coverage(caps, lex)
    if gaps.devices:
        add(WARN, "lexicon", f"device chưa có tên tiếng Việt: {gaps.devices}")
    if gaps.zones:
        add(WARN, "lexicon", f"zone chưa có tên: {gaps.zones}")
    if gaps.modes:
        add(WARN, "lexicon", f"mode chưa có tên: {gaps.modes}")
    if gaps.actions:
        add(WARN, "lexicon", f"action chưa có động từ: {gaps.actions}")
    if gaps.units:
        add(WARN, "lexicon", f"đơn vị chưa có tên: {gaps.units}")
    if gaps.complete:
        add(INFO, "lexicon", f"{len(lex.entries)} alias, phủ đủ device/zone/mode/action/unit")

    stripped = lex.ambiguous_only_stripped()
    for alias, group in stripped.items():
        pairs = ", ".join(f"{e.surface}={e.kind}:{e.target}" for e in group)
        add(WARN, "lexicon", f"bỏ dấu là trùng: '{alias}' ← {pairs} → phải khớp tầng có dấu trước")

    real = {a: g for a, g in lex.exact_collisions().items() if a not in stripped}
    for alias, group in real.items():
        pairs = ", ".join(f"{e.kind}:{e.target}" for e in group)
        add(INFO, "lexicon", f"'{alias}' trỏ tới nhiều đích ({pairs}) → matcher phân giải theo device/ngữ cảnh")

    pairs = lex.containments()
    if pairs:
        sample = "; ".join(f"{s.surface!r}⊂{l.surface!r}" for s, l in pairs[:3])
        add(INFO, "lexicon", f"{len(pairs)} cặp alias lồng nhau → BẮT BUỘC longest-match. Vd: {sample}")

    return out


def format_report(caps: Caps, findings: list[Finding]) -> str:
    head = f"{caps.path or caps.model}: {len(caps.devices)} devices, {len(caps.safety)} safety rules"
    lines = [head] + [str(f) for f in findings]
    counts = {lvl: sum(1 for f in findings if f.level == lvl) for lvl in (ERROR, WARN, INFO)}
    lines.append(f"{counts[ERROR]} errors, {counts[WARN]} warnings, {counts[INFO]} infos")
    return "\n".join(lines)
