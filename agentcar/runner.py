"""Ranh giới với xe: ai thực sự thực thi plan.

Trước khi có file này, agent tự cập nhật trạng thái thiết bị ngay khi tầng an toàn
cho phép — tức là TIN rằng lệnh đã chạy, trong khi chưa ai gửi nó xuống xe. Với xe
thật thì lệnh có thể bị CAN từ chối hoặc ACK muộn, lúc đó agent đã nói "đã bật" và
đã ghi vào trạng thái: sai hai lần.

Giờ agent phải đi qua PlanRunner và chỉ cập nhật trạng thái khi có xác nhận.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from .plan import Command


@dataclass
class ExecResult:
    command: Command
    ok: bool
    code: Optional[str] = None      # mã lỗi từ phía dưới, nếu có
    detail: str = ""


class PlanRunner(Protocol):
    def execute(self, commands: list[Command]) -> list[ExecResult]:
        """Trả về ĐÚNG một kết quả cho mỗi lệnh, theo đúng thứ tự nhận vào."""
        ...


@dataclass
class MockPlanRunner:
    """Ghi lại lệnh và trả thành công. `reject` để giả lập xe từ chối."""

    reject: Callable[[Command], Optional[str]] = lambda cmd: None
    log: list[Command] = field(default_factory=list)

    def execute(self, commands: list[Command]) -> list[ExecResult]:
        out = []
        for command in commands:
            why = self.reject(command)
            if why is None:
                self.log.append(command)
                out.append(ExecResult(command=command, ok=True))
            else:
                out.append(ExecResult(command=command, ok=False, detail=why))
        return out

    def reset(self) -> None:
        self.log.clear()
