"""Kiểu dữ liệu chung: command, verdict, error code.

TODO(chốt với PlanRunner): tên field trong Command là giả định. Khi biết schema
thật của PlanRunner thì chỉ cần sửa Command.to_dict(), không đụng logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class Verdict:
    OK = "OK"
    CONFIRM = "CONFIRM"
    DENY = "DENY"
    NOT_SUPPORT = "NOT_SUPPORT"
    # Hai kiểu escalate khác nhau về ĐÍCH ĐẾN, router phía trên không phải đoán:
    ESCALATE_ROUTED = "ESCALATE_ROUTED"    # caps chỉ rõ ai xử lý (cloud_only), kèm target
    ESCALATE_UNKNOWN = "ESCALATE_UNKNOWN"  # chưa biết ai xử lý, cần tầng suy luận
    INVALID = "INVALID"
    CANCELLED = "CANCELLED"
    ASK = "ASK"        # cloud thiếu thông tin, hỏi lại người dùng
    REPLY = "REPLY"    # cloud trả lời bằng lời, không có lệnh nào

    ESCALATES = (ESCALATE_ROUTED, ESCALATE_UNKNOWN)

    @staticmethod
    def is_escalate(verdict: str) -> bool:
        return verdict in Verdict.ESCALATES


class Code:
    NOT_SUPPORT = "VA_NOT_SUPPORT"
    UNKNOWN_DEVICE = "VA_UNKNOWN_DEVICE"
    INVALID_ACTION = "VA_INVALID_ACTION"
    NOT_READABLE = "VA_NOT_READABLE"
    INVALID_ZONE = "VA_INVALID_ZONE"
    INVALID_MODE = "VA_INVALID_MODE"
    MODE_EXCLUDED = "VA_MODE_EXCLUDED"
    MODE_REQUIRED = "VA_MODE_REQUIRED"
    VALUE_REQUIRED = "VA_VALUE_REQUIRED"
    INVALID_UNIT = "VA_INVALID_UNIT"
    OUT_OF_RANGE = "VA_OUT_OF_RANGE"
    ZONE_AMBIGUOUS = "VA_ZONE_AMBIGUOUS"
    INVALID_ITEM = "VA_INVALID_ITEM"
    ITEM_REQUIRED = "VA_ITEM_REQUIRED"
    NO_DEFAULT_ACTION = "VA_NO_DEFAULT_ACTION"
    NO_PREVIOUS_VALUE = "VA_NO_PREVIOUS_VALUE"
    DEVICE_REQUIRED = "VA_DEVICE_REQUIRED"
    VAGUE_REFERENCE = "VA_VAGUE_REFERENCE"
    TOO_SHORT = "VA_TOO_SHORT"
    ASK = "VA_ASK"
    REPLY = "VA_REPLY"
    NO_ANSWER = "VA_NO_ANSWER"
    EXEC_FAILED = "VA_EXEC_FAILED"
    ESCALATE_ROUTED = "VA_ESCALATE_ROUTED"
    ESCALATE_UNKNOWN = "VA_ESCALATE_UNKNOWN"
    LLM_UNAVAILABLE = "VA_LLM_UNAVAILABLE"
    LLM_TIMEOUT = "VA_LLM_TIMEOUT"
    NOT_SCHEDULABLE = "VA_NOT_SCHEDULABLE"
    SAFETY_DENY = "VA_SAFETY_DENY"
    NEED_CONFIRM = "VA_NEED_CONFIRM"


@dataclass
class RawCommand:
    """Đầu ra của tầng hiểu (grammar hoặc LLM), chưa được caps xác nhận."""

    device: str
    action: Optional[str] = None
    zone: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    mode: Optional[str] = None
    item: Optional[str] = None


@dataclass
class Command:
    """Command đã chuẩn hoá theo caps — thứ duy nhất được phép xuống PlanRunner."""

    device: str
    action: str
    zone: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    mode: Optional[str] = None
    mode_group: Optional[str] = None  # D1: chỉ ghi đè mode trong cùng nhóm
    item: Optional[str] = None
    step: Optional[float] = None  # increase/decrease: bước thay đổi

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"device": self.device, "action": self.action}
        for k in ("zone", "value", "unit", "mode", "mode_group", "item", "step"):
            v = getattr(self, k)
            if v is not None:
                out[k] = v
        return out


@dataclass
class Result:
    verdict: str
    command: Optional[Command] = None
    code: Optional[str] = None
    reason: str = ""
    target: Optional[str] = None  # ESCALATE_ROUTED: ai sẽ xử lý câu này
    device: Optional[str] = None  # thiết bị liên quan, kể cả khi lệnh bị từ chối
    verb: Optional[str] = None    # động từ nghe được nhưng chưa biết áp lên cái gì
    hint: Optional[str] = None    # chữ đi kèm chưa khớp được: "đèn"
    # OUT_OF_RANGE: (lo, hi, tên đơn vị) — để responder tự dựng "16 đến 32 độ"
    # bằng từ điển, thay vì resolve phải biết tiếng Việt.
    range_spec: Optional[tuple] = None
    actions: list[str] = field(default_factory=list)   # action tương ứng với verb
    notes: list[str] = field(default_factory=list)
    # Thiết bị ĐÃ ở đúng trạng thái xin: không gửi lệnh, chỉ nói ra cho biết.
    da_dung: bool = False
    # Lệnh tương đối mà đã ở biên: "max" / "min". Cũng không gửi, cũng chỉ nói ra.
    cham_bien: Optional[str] = None
    # Vùng do caps điền mặc định, KHÔNG phải người dùng nêu. Cần phân biệt để biết
    # lúc nào được phép hỏi lại "vùng nào" (BA sheet 3.2 #46).
    zone_mac_dinh: bool = False
    # Đã hỏi lại "vùng nào?" thay vì gửi lệnh (BA sheet 3.2 #46/#47).
    hoi_vung: bool = False
    # Lệnh còn dở, chỉ thiếu vùng — giữ nguyên để lượt sau điền vào rồi chạy.
    cho_vung: Optional["RawCommand"] = None

    @property
    def ok(self) -> bool:
        return self.verdict == Verdict.OK

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"verdict": self.verdict}
        if self.command is not None:
            out["plan"] = [self.command.to_dict()]
        if self.code:
            out["code"] = self.code
        if self.target:
            out["target"] = self.target
        if self.reason:
            out["reason"] = self.reason
        if self.notes:
            out["notes"] = self.notes
        return out
