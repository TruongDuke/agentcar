"""Ranh giới với xe, chiều đi LÊN: ai đọc tín hiệu an toàn của cả xe.

Ba ranh giới với xe, mỗi cái một file:
    runner.py  — chiều đi xuống: gửi lệnh, nhận ACK.
    state.py   — trạng thái TỪNG THIẾT BỊ: điều hoà mấy độ, kính mở chưa.
    monitor.py — 5 tín hiệu của CẢ XE mà tầng [4] dựa vào để chặn.

Hai file kia đều có sẵn cặp Protocol + Mock. Riêng tín hiệu xe thì trước file này
không có gì: VehicleState luôn do người gọi dựng sẵn rồi đứng yên suốt phiên. Hệ
quả là lời hứa ở Agent._apply_pending — "xe có thể đã chuyển số trong lúc chờ, lúc
đó lệnh phải bị từ chối" — không kiểm chứng được, vì trạng thái lúc hỏi và lúc
người dùng đồng ý luôn là cùng một object.

MockSignalMonitor phát lại một kịch bản lái theo mốc thời gian, nên cùng một câu
nói ở hai thời điểm cho hai kết quả khác nhau. Adapter CAN thật sau này chỉ cần
cài đúng read().
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol

import yaml

from .safety import DEFAULT_STATE_FIELDS, VehicleState

# Tên viết ngắn trong kịch bản, trùng với cờ CLI --speed/--battery cho khỏi phải nhớ hai kiểu.
ALIASES = {"speed": "speed_kmh", "battery": "battery_pct", "brake": "parking_brake"}
_FLOATS = ("speed_kmh", "battery_pct")
_BOOLS = ("charging",)
_TRUE = ("1", "true", "yes", "on", "có")


class SignalMonitor(Protocol):
    def read(self) -> VehicleState:
        """Trạng thái xe TẠI THỜI ĐIỂM GỌI.

        Phải rẻ và không được ném: mỗi lượt nói gọi ít nhất một lần, và gọi lại
        lần nữa khi người dùng xác nhận lệnh đang chờ.
        """
        ...


@dataclass
class FixedMonitor:
    """Một trạng thái đứng yên — đúng hành vi trước khi có file này.

    Trả về chính object đang giữ chứ không phải bản sao: repl sửa tại chỗ bằng
    `:set gear=D` rồi lượt sau đọc ra giá trị mới.
    """

    state: VehicleState = field(default_factory=VehicleState)

    def read(self) -> VehicleState:
        return self.state


@dataclass(frozen=True)
class Frame:
    at_s: float
    state: VehicleState


@dataclass
class MockSignalMonitor:
    """Phát lại kịch bản lái: tới mốc nào thì lấy nguyên trạng thái mốc đó.

    Bậc thang chứ KHÔNG nội suy. Nội suy nghe hợp lý với speed_kmh nhưng vô nghĩa
    với gear, và luật an toàn so theo ngưỡng ("speed_kmh >= 16") nên thứ cần dựng
    được là hai bên ngưỡng, không phải đường đi giữa chúng.

    Đồng hồ bắt đầu ở lần read() ĐẦU TIÊN chứ không phải lúc dựng object: dựng
    monitor lúc khởi động rồi vài giây sau mới có người nói thì kịch bản vẫn chạy
    từ giây 0, không mất mấy mốc đầu.
    """

    frames: list[Frame]
    clock: Callable[[], float] = time.monotonic
    # Bao lâu thì quay lại đầu. Để trống = chạy một lần rồi đứng ở mốc cuối.
    # KHÔNG mặc định bằng duration: chu kỳ đúng bằng mốc cuối thì mốc cuối rơi
    # ngay vào điểm wrap và không bao giờ được phát.
    period: Optional[float] = None
    started_at: Optional[float] = None

    def __post_init__(self) -> None:
        self.frames = sorted(self.frames, key=lambda f: f.at_s)
        # Chưa tới mốc đầu tiên thì coi như xe đỗ — không lấy ngược trạng thái của
        # mốc sau, vì như thế là đoán tương lai.
        if not self.frames or self.frames[0].at_s > 0:
            self.frames.insert(0, Frame(0.0, VehicleState()))

    @property
    def duration(self) -> float:
        """Mốc cuối cùng. Kịch bản còn chạy tiếp sau đó, chỉ là không đổi gì nữa."""
        return self.frames[-1].at_s

    @property
    def loops(self) -> bool:
        return bool(self.period and self.period > 0)

    def elapsed(self) -> float:
        now = self.clock()
        if self.started_at is None:
            self.started_at = now
        span = now - self.started_at
        if self.period and self.period > 0:
            span %= self.period
        return span

    def at(self, second: float) -> VehicleState:
        """Trạng thái ở giây thứ `second` của kịch bản, không đụng tới đồng hồ."""
        chosen = self.frames[0]
        for frame in self.frames:
            if frame.at_s > second:
                break
            chosen = frame
        return chosen.state

    def read(self) -> VehicleState:
        return self.at(self.elapsed())

    def restart(self) -> None:
        self.started_at = None

    def timeline(self) -> list[str]:
        """Để CLI in ra cho người chạy biết kịch bản sắp diễn ra thế nào."""
        return [f"{f.at_s:>5.1f}s  {f.state.describe()}" for f in self.frames]

    # ------------------------------------------------------------------ nạp
    @classmethod
    def from_rows(cls, rows: Iterable[dict], **kw) -> "MockSignalMonitor":
        """Mỗi hàng là một mốc: {at: 3, gear: D, speed: 60}.

        Trường không khai thì GIỮ NGUYÊN của mốc trước — kịch bản chỉ ghi cái gì
        đổi, khỏi phải chép lại cả 5 tín hiệu ở từng dòng.
        """
        frames: list[Frame] = []
        carry = VehicleState()
        for row in rows:
            row = dict(row or {})
            at = row.pop("at_s", 0.0)
            at = float(row.pop("at", at))
            carry = _merge(carry, row)
            frames.append(Frame(at, carry))
        return cls(frames=frames, **kw)

    @classmethod
    def from_yaml(cls, path: Path | str, **kw) -> "MockSignalMonitor":
        """File kịch bản: một list các mốc, hoặc {period: 60, frames: [...]}."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
        if isinstance(raw, dict):
            if raw.get("period") is not None:
                kw.setdefault("period", float(raw["period"]))
            raw = raw.get("frames") or []
        return cls.from_rows(raw, **kw)


def _merge(base: VehicleState, row: dict[str, Any]) -> VehicleState:
    """Chồng những gì mốc này khai lên trạng thái của mốc trước."""
    state = VehicleState(
        gear=base.gear, speed_kmh=base.speed_kmh, battery_pct=base.battery_pct,
        charging=base.charging, parking_brake=base.parking_brake,
        extra=dict(base.extra))
    for key, value in row.items():
        key = ALIASES.get(key, key)
        if key in _FLOATS:
            setattr(state, key, float(value))
        elif key in _BOOLS:
            setattr(state, key, _truthy(value))
        elif key in DEFAULT_STATE_FIELDS:
            setattr(state, key, str(value))
        else:
            # Tín hiệu ngoài 5 cái mặc định: caps được phép khai `when` theo tên
            # khác, safety đọc chúng qua VehicleState.extra.
            state.extra[key] = value
    return state


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE
