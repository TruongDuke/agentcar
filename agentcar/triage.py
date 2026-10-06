"""Phân loại LÝ DO tầng edge trượt — chạy TRƯỚC khi gọi cloud.

Hiện agent phân loại ở đầu ra: mọi câu trượt đều đi cùng một đường, cùng deadline,
cùng prompt 30 thiết bị, rồi mới để model quyết định đó là lệnh, câu hỏi lại, câu
từ chối hay chuyển tiếp. Nhưng lý do trượt thì khác hẳn nhau, và tín hiệu để biết
lý do thì tầng [1] đã trả về sẵn.

Module này CHỈ dán nhãn, không đổi luồng — để đo phân bố trước khi bàn chính sách.
"""
from __future__ import annotations

from dataclasses import dataclass

from .match import MatchResult


class Escalation:
    NONE = "none"              # tầng edge lo được
    SLOT = "slot"              # có nhắc thiết bị, grammar không ghép nổi
    DEVICE = "device"          # có động từ, không rõ thiết bị
    NOT_NOW = "not_now"        # điều kiện / hẹn giờ
    OFF_DOMAIN = "off_domain"  # không nhắc gì thuộc xe

    ALL = (NONE, SLOT, DEVICE, NOT_NOW, OFF_DOMAIN)


def classify(match: MatchResult) -> str:
    """Thuần tất định, chỉ đọc thứ tầng [1] đã tính.

    Thứ tự có chủ ý: NOT_NOW trước SLOT, vì "mở cửa sổ trời khi nào tới nhà" có
    nhắc thiết bị nhưng tuyệt đối không được chạy.
    """
    if match.commands:
        return Escalation.NONE
    if match.conditional:
        return Escalation.NOT_NOW
    if match.mentioned:
        return Escalation.SLOT
    if match.orphan_verb:
        return Escalation.DEVICE
    return Escalation.OFF_DOMAIN


@dataclass
class Tally:
    counts: dict[str, int]
    examples: dict[str, list[str]]

    def report(self, title: str) -> str:
        total = sum(self.counts.values()) or 1
        lines = [f"{title}: {total} câu"]
        for label in Escalation.ALL:
            n = self.counts.get(label, 0)
            if not n:
                continue
            sample = ", ".join(repr(x) for x in self.examples[label][:3])
            lines.append(f"  {label:11} {n:4}  {n / total:5.1%}   {sample}")
        return "\n".join(lines)


def tally(labelled: list[tuple[str, str]]) -> Tally:
    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    for text, label in labelled:
        counts[label] = counts.get(label, 0) + 1
        examples.setdefault(label, []).append(text)
    return Tally(counts, examples)
