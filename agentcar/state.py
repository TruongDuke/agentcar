"""Trạng thái từng thiết bị — thứ cần để trả lời câu hỏi, chứ không phải để ra lệnh.

VehicleState (trong safety.py) là 5 tín hiệu an toàn của cả xe: gear, speed, pin...
Còn đây là trạng thái của từng thiết bị: điều hoà đang mấy độ, cửa kính mở chưa.

MockStateProvider chỉ biết những gì CHÍNH AGENT đã đặt — người dùng vặn núm tay
thì nó không biết. Adapter thật sau này chỉ cần cài đúng giao diện StateProvider.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from .caps import Caps
from .plan import Command

DEFAULT_GROUP = ""  # thiết bị không chia nhóm mode
RELATIVE = ("increase", "decrease")


def relative_base(caps: Caps, command: Command, state: "DeviceState") -> Optional[float]:
    """Mốc để cộng/trừ cho increase/decrease, hoặc None nếu không có mốc nào.

    Ưu tiên mức đang biết. Chưa biết thì lấy comfort_default trong caps — dùng nó
    KHÔNG phải đoán bừa, mà là đọc đúng con số caps đã khai là mức dễ chịu.

    Đơn vị nào caps không khai comfort_default thì trả None, và người gọi phải nói
    ra là chưa biết. Báo thành công cho một lệnh không tính nổi kết quả là nói dối:
    "đã giảm 2 độ" trong khi không biết giảm từ đâu.
    """
    if state.value is not None:
        return state.value
    dev = caps.devices.get(command.device)
    unit = dev.value.unit(command.unit) if dev is not None and dev.value else None
    return unit.comfort_default if unit is not None else None


@dataclass
class DeviceState:
    """on mang nghĩa khác nhau tuỳ loại: bật/tắt, mở/đóng, hoặc mở/gập."""

    on: Optional[bool] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    modes: dict[str, str] = field(default_factory=dict)
    item: Optional[str] = None

    @property
    def known(self) -> bool:
        return not (self.on is None and self.value is None and not self.modes and self.item is None)


def da_dung_trang_thai(caps: Caps, command: Command, state: "DeviceState") -> bool:
    """Thiết bị đã ở đúng trạng thái lệnh xin chưa.

    Chỉ trả True khi CHẮC CHẮN: trạng thái phải đang biết, và lệnh không kèm thay
    đổi nào khác. Không biết thì trả False — thà gửi lại lệnh thừa còn hơn bỏ qua
    một lệnh người dùng thật sự muốn.
    """
    if not state.known:
        return False
    a = command.action
    if a in ("turn_on", "open", "unfold"):
        # "bật điều hòa" mang sẵn value=22 từ comfort_default, nên không thể đòi
        # command.value is None — phải so với mức đang có.
        if state.on is not True or command.mode is not None or command.item is not None:
            return False
        return command.value is None or state.value == command.value
    if a in ("turn_off", "close", "fold"):
        return state.on is False and command.item is None
    if a == "set_level":
        return state.on is not False and state.value == command.value
    if a == "set_mode" and command.mode:
        return state.modes.get(command.mode_group or DEFAULT_GROUP) == command.mode
    return False


def cham_bien(caps: Caps, command: Command, state: "DeviceState") -> Optional[str]:
    """Lệnh tương đối mà thiết bị đã ở biên: trả "max" / "min", không thì None.

    BA sheet 3.1 #4/#7: quạt đang 6/6 mà bảo "tăng 1 mức" thì phải nói "đang ở mức
    tối đa", chứ không phải đáp "đã tăng 1 mức" trong khi không có gì thay đổi —
    cùng lý do với `da_dung_trang_thai`: đừng báo một việc không xảy ra.

    Chưa chắc thì trả None: thà gửi lệnh thừa còn hơn nuốt lệnh người ta thật muốn.
    """
    if command.action not in ("increase", "decrease") or not state.known:
        return None
    if state.value is None or state.on is False:
        return None
    device = caps.devices.get(command.device)
    if device is None or device.value is None:
        return None
    unit = device.value.unit(command.unit) if command.unit else device.value.unit()
    if unit is None:
        return None
    # Bước ÂM đảo chiều lệnh: "tăng -3 nấc" thực chất là giảm 3. Không xét dấu
    # thì thiết bị đang ở max bị đáp "đang tối đa rồi, không tăng thêm được"
    # trong khi câu đó làm nó GIẢM. Phát hiện lúc demo trên trình duyệt.
    buoc = command.step
    len_xuong = command.action == "increase"
    if buoc is not None and buoc < 0:
        len_xuong = not len_xuong
    if len_xuong and state.value >= unit.hi:
        return "max"
    if not len_xuong and state.value <= unit.lo:
        return "min"
    return None


class StateProvider(Protocol):
    def get(self, device: str, zone: Optional[str] = None) -> DeviceState:
        ...

    def vung_dang_bat(self, device: str) -> Optional[bool]:
        ...


class MockStateProvider:
    """Lưu trong bộ nhớ, cập nhật theo đúng những lệnh đã chạy.

    `path` để ghi ra file cho trạng thái sống qua nhiều tiến trình: mỗi lần chạy
    `agentcar run` là một tiến trình mới, không có nó thì câu hỏi trạng thái luôn
    trả "chưa biết". CHỈ dùng cho giả lập — adapter CAN thật đọc trực tiếp từ xe.
    Mặc định KHÔNG ghi file, để test và thư viện không tự sinh rác.
    """

    def __init__(self, caps: Caps, path: Optional[Path | str] = None):
        self.caps = caps
        self.path = Path(path) if path else None
        self._store: dict[tuple[str, Optional[str]], DeviceState] = {}
        self._load()

    def get(self, device: str, zone: Optional[str] = None) -> DeviceState:
        exact = self._store.get((device, zone))
        if exact is not None:
            return exact
        # Hỏi chung chung ("sưởi ghế bật chưa") trong khi chỉ mới đặt đúng một vùng
        # thì trả vùng đó, thay vì nói không biết.
        known = [v for (d, _), v in self._store.items() if d == device]
        return known[0] if len(known) == 1 else DeviceState()

    def vung_dang_bat(self, device: str) -> Optional[bool]:
        """Có vùng nào của thiết bị đang BẬT không. None = chưa biết.

        KHÔNG dùng get(): get() có bước suy rộng "chỉ biết một vùng thì trả vùng
        đó" — đúng cho câu hỏi trạng thái, sai ở đây vì cần sự thật TỪNG VÙNG.
        Chưa biết thì trả None, để bên gọi chọn cách an toàn (BA sheet 3.2 #46
        chỉ áp dụng khi CHẮC CHẮN mọi vùng đang tắt).
        """
        rows = [v for (d, _), v in self._store.items() if d == device]
        if not rows:
            return None
        if any(v.on is True or (v.value or 0) > 0 for v in rows):
            return True
        if all(v.on is False for v in rows):
            return False
        return None

    def _slot(self, device: str, zone: Optional[str]) -> DeviceState:
        return self._store.setdefault((device, zone), DeviceState())

    # ------------------------------------------------------------- ghi/đọc file
    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for row in rows:
            self._store[(row["device"], row["zone"])] = DeviceState(
                on=row.get("on"), value=row.get("value"), unit=row.get("unit"),
                modes=dict(row.get("modes") or {}), item=row.get("item"))

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        except OSError:
            pass            # hỏng thì thôi, đừng làm sập agent

    def apply(self, command: Command) -> None:
        """Ghi lại hệ quả của một lệnh đã được phép chạy."""
        dev = self.caps.devices.get(command.device)
        if dev is None or command.action == "query":
            return
        spec = self.caps.catalog.spec(dev.type)
        state = self._slot(command.device, command.zone)
        action = command.action

        if spec.mode_as_action:
            if action == "turn_off":
                state.modes.pop(DEFAULT_GROUP, None)
                state.on = bool(state.modes)
            elif action in dev.modes:
                state.modes[DEFAULT_GROUP] = action
                state.on = True
            self._save()
            return

        if action in ("turn_on", "open", "unfold"):
            state.on = True
            if command.value is not None:
                state.value, state.unit = command.value, command.unit
            if command.item is not None:
                state.item = command.item
        elif action in ("turn_off", "close", "fold"):
            state.on = False
            if action == "close":
                state.value = None
            if command.item is not None and state.item == command.item:
                state.item = None
        elif action == "set_level":
            state.value, state.unit = command.value, command.unit
            unit = dev.value.unit(command.unit) if dev.value else None
            if unit is not None and unit.lo == 0:
                state.on = bool(command.value)      # volume: mức 0 là đang tắt tiếng
            else:
                state.on = True
        elif action in RELATIVE:
            base = relative_base(self.caps, command, state)
            if base is not None and command.step is not None:
                delta = command.step if action == "increase" else -command.step
                unit = dev.value.unit(state.unit or command.unit) if dev.value else None
                new = base + delta
                if unit is not None:
                    new = min(max(new, unit.lo), unit.hi)
                    state.unit = unit.name
                state.value = new
                # Bảo tăng/giảm tức là muốn thiết bị chạy, nên đang tắt thì bật lên.
                # Trừ loại có mức 0 nghĩa là tắt (âm lượng) — ở đó số mới quyết định.
                state.on = bool(new) if (unit is not None and unit.lo == 0) else True
        elif action == "set_mode" and command.mode:
            state.modes[command.mode_group or DEFAULT_GROUP] = command.mode
            if state.on is None:
                state.on = True
        elif action == "clear_mode" and command.mode:
            group = command.mode_group or DEFAULT_GROUP
            if state.modes.get(group) == command.mode:
                state.modes.pop(group)
        self._save()

    def seed(self, rows) -> None:
        """Nạp thẳng một mốc xuất phát, thay sạch những gì đang giữ.

        Ghi file MỘT lần chứ không mỗi thiết bị một lần — nạp cả xe là 30 lượt ghi.
        """
        self._store = {(device, zone): state for device, zone, state in rows}
        self._save()

    def snapshot(self) -> list[dict]:
        """Toàn bộ trạng thái đang biết, để giả lập vẽ ra màn hình."""
        return [
            {"device": device, "zone": zone, "on": st.on, "value": st.value,
             "unit": st.unit, "modes": dict(st.modes), "item": st.item}
            for (device, zone), st in sorted(self._store.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
        ]

    def reset(self) -> None:
        self._store.clear()
        self._save()
