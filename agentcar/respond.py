"""Tầng [5] — sinh câu trả lời tiếng Việt.

Ghép từ template, KHÔNG dùng mô hình sinh: câu phải giống nhau mọi lần, số liệu
phải lấy thẳng từ command (không có cửa cho việc nói một đằng làm một nẻo), và
phải xong trong vài micro giây để không đụng tới deadline.

Câu cho DENY/CONFIRM lấy nguyên `reason` trong caps — do bên định nghĩa xe viết.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from .caps import Caps, Device
from .lexicon import ACTION, DEVICE, ITEM, MODE, ZONE, Lexicon
from .plan import Code, Command, Result, Verdict
from .state import DeviceState

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "caps" / "lexicon.vi.yaml"


MAX_OPTIONS = 4


@dataclass
class Speech:
    """text rỗng + needs_state=True nghĩa là phải đọc trạng thái thiết bị mới nói được."""

    text: str = ""
    needs_state: bool = False

    def __bool__(self) -> bool:
        return bool(self.text)


def _tidy(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}".replace(".", ",")      # 22.5 -> "22,5"


def _capitalize(sentence: str) -> str:
    return sentence[:1].upper() + sentence[1:] if sentence else sentence


def _clean(sentence: str) -> str:
    out = re.sub(r"\s+", " ", sentence).replace(" ạ", " ạ").strip()
    # Tên thiết bị trong từ điển viết thường ("điều hòa"); khi nó rơi vào đầu câu
    # thì phải hoa lên, nếu không nghe thì không sao mà đọc log thì chướng.
    return out[:1].upper() + out[1:] if out else out


class Responder:
    def __init__(self, caps: Caps, lex: Lexicon, path: Path | str = DEFAULT_PATH):
        raw = (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("responses") or {}
        self.caps = caps
        self.lex = lex
        self.actions: dict[str, str] = raw.get("actions") or {}
        self.errors: dict[str, str] = raw.get("errors") or {}
        self.units: dict[str, dict[str, str]] = raw.get("units") or {}
        self.cancelled: str = raw.get("cancelled") or ""
        self.zone_as_subject: set[str] = set(raw.get("zone_as_subject") or [])
        self.set_level_zero: str = raw.get("set_level_zero") or ""
        self.query: dict[str, str] = raw.get("query") or {}
        self.bien: dict[str, str] = raw.get("bien") or {}
        self.hoi_vung: str = raw.get("hoi_vung") or ""

    # ------------------------------------------------------------- tên hiển thị
    def name_of(self, kind: str, target: str, device: Optional[str] = None) -> str:
        """Alias ĐẦU TIÊN trong từ điển là tên hiển thị — nên thứ tự khai có ý nghĩa."""
        names = self.lex.aliases_of(kind, target, device=device)
        return names[0] if names else target

    def _amount(self, command: Command, delta: bool) -> str:
        value = command.step if delta else command.value
        if value is None:
            return ""
        table = self.units.get("delta" if delta else "absolute", {})
        template = table.get(command.unit or "", "{value}")
        return template.format(value=_tidy(value))

    def _range(self, result) -> str:
        """Dải hợp lệ kèm đơn vị, đọc xuôi tai theo kiểu mẫu của từng đơn vị.

        Đơn vị ĐỨNG SAU số ("{value} độ") thì chỉ cần gắn vào đầu kia:
        "16 đến 32 độ". Đơn vị ĐỨNG TRƯỚC ("mức {value}") thì phải lặp cả hai,
        vì "1 đến mức 6" là câu hỏng: "mức 1 đến mức 6".
        """
        if not result.range_spec:
            return ""
        lo, hi, unit = result.range_spec
        template = self.units.get("absolute", {}).get(unit, "{value}")
        hi_text = template.format(value=_tidy(hi))
        lo_text = _tidy(lo) if template.startswith("{value}") else template.format(value=_tidy(lo))
        return f"{lo_text} đến {hi_text}"

    @staticmethod
    def _merge(device_name: str, zone_name: str) -> str:
        """Bỏ chữ lặp ở chỗ nối: 'sưởi ghế' + 'ghế lái' -> 'sưởi ghế lái'."""
        tail = device_name.split()[-1]
        words = zone_name.split()
        if words and words[0] == tail:
            return " ".join(words[1:])
        return zone_name

    def _slots(self, command: Command) -> dict[str, Any]:
        dev = self.caps.devices[command.device]
        device_name = self.name_of(DEVICE, command.device)
        item_name = self.name_of(ITEM, command.item, device=command.device) if command.item else ""

        # Zone mặc định thì không đọc ra: "Đã mở cửa kính ạ." nghe tự nhiên hơn
        # "Đã mở cửa kính tất cả ạ."
        zone = ""
        if command.zone and command.zone != dev.default_zone:
            zone_name = self.name_of(ZONE, command.zone, device=command.device)
            if command.device in self.zone_as_subject:
                device_name = zone_name          # "đóng rèm", không phải "đóng cửa sổ trời rèm"
            else:
                merged = self._merge(device_name, zone_name)
                zone = f" {merged}" if merged else ""

        delta = command.action in ("increase", "decrease")
        amount = self._amount(command, delta)
        return {
            "device": device_name,
            "target": item_name or device_name,
            "zone": zone,
            "value": f" {amount}" if amount else "",
            "mode": self.name_of(MODE, command.mode) if command.mode else "",
            "item": item_name,
        }

    # ------------------------------------------------------------- điểm vào
    # ------------------------------------------------------------- câu hỏi
    def state_kind(self, dev: Device) -> str:
        """Suy loại câu trả lời từ catalog, không khai tay cho từng thiết bị."""
        if self.caps.catalog.spec(dev.type).mode_as_action:
            return "scene"
        actions = set(self.caps.catalog_actions(dev))
        if "fold" in actions:
            return "fold"
        if dev.has_items:
            return "item"
        if "open" in actions:
            return "aperture"
        if "set_level" in actions:
            return "level"
        return "switch"

    def _answer(self, command: Command, state: DeviceState) -> str:
        dev = self.caps.devices[command.device]
        slots = self._slots(command)
        label = f"{slots['device']}{slots['zone']}"
        modes = ", ".join(self.name_of(MODE, m) for m in state.modes.values())
        amount = ""
        if state.value is not None:
            table = self.units.get("absolute", {})
            amount = table.get(state.unit or "", "{value}").format(value=_tidy(state.value))

        kind = self.state_kind(dev)
        pick = lambda key, **kw: _clean(self.query.get(key, "").format(
            device=label, value=amount, mode=modes, item=slots["item"], **kw))

        if not state.known:
            return pick("unknown")
        if kind == "scene":
            return pick("scene_on") if state.modes else pick("scene_off")
        if kind == "fold":
            return pick("fold_folded") if state.on is False else pick("fold_open")
        if kind == "item":
            if not state.item:
                return pick("unknown")
            opened = self.name_of(ITEM, state.item, device=command.device)
            return _clean(self.query.get("item_open", "").format(
                device=label, value=amount, mode=modes, item=opened))
        if kind == "aperture":
            if state.on is False:
                return pick("aperture_closed")
            return _clean(self.query.get("aperture_open", "").format(
                device=label, value=f" {amount}" if amount else "", mode=modes, item=slots["item"]))
        if state.on is False and kind == "level":
            return pick("level_off")
        if state.value is not None:
            return pick("level_with_mode") if modes else pick("level")
        if modes:
            return pick("mode")
        return pick("switch_on") if state.on else pick("switch_off")

    def say(self, result: Result, state: Optional[DeviceState] = None) -> Speech:
        if result.verdict in (Verdict.DENY, Verdict.CONFIRM):
            # Luật an toàn trong caps tự mang câu hỏi; CONFIRM sinh trong resolve
            # thì không, lấy mẫu chung từ từ điển.
            return Speech(result.reason or self._error(result))
        if result.verdict == Verdict.REPLY and result.code == Code.NO_ANSWER:
            return Speech(self._error(result))
        if result.verdict in (Verdict.ASK, Verdict.REPLY):
            if result.code == Code.DEVICE_REQUIRED and not result.reason.endswith("phải không ạ?"):
                return Speech(self._error(result))   # hỏi lại tại chỗ, theo mẫu
            return Speech(result.reason)             # câu do tầng [2] soạn
        if result.verdict == Verdict.CANCELLED:
            return Speech(self.cancelled or result.reason)
        if Verdict.is_escalate(result.verdict):
            # Mất mạng và quá hạn đều phải báo. Chỉ im khi có tầng trên lo tiếp.
            if result.code in (Code.LLM_UNAVAILABLE, Code.LLM_TIMEOUT):
                return Speech(self._error(result))
            return Speech()
        if result.verdict != Verdict.OK or result.command is None:
            return Speech(self._error(result))

        command = result.command
        # Hỏi lại vùng: không gửi lệnh, hỏi người dùng muốn vùng nào.
        if result.hoi_vung and self.hoi_vung:
            return Speech(_clean(self.hoi_vung.format(
                device=self.name_of(DEVICE, command.device))))
        # Chạm biên: nói rõ đang ở đâu, đừng đáp "đã tăng" khi không tăng được.
        if result.cham_bien:
            if state is None:
                return Speech(needs_state=True)
            # cham_bien() tính trên MỘT lần đọc trạng thái, còn câu trả lời dựng
            # trên lần đọc THỨ HAI (agent._voice gọi lại devices.get). Hai lần đọc
            # có thể lệch nhau — khác vùng, hoặc xe vừa đổi trạng thái. Không có
            # số thì đừng khẳng định "đang ở mức tối đa": rơi xuống câu thường,
            # thà đáp nhạt còn hơn đáp sai. (Trước đây chỗ này nổ TypeError.)
            template = self.bien.get(result.cham_bien, "") if state.value is not None else ""
            if template:
                unit_tmpl = self.units.get("absolute", {}).get(command.unit or "", "{value}")
                return Speech(_clean(template.format(
                    device=self.name_of(DEVICE, command.device),
                    value=unit_tmpl.format(value=_tidy(state.value)))))
        # Đã đúng trạng thái: trả lời y như câu hỏi trạng thái. Nói "đã bật" cho một
        # thứ đang bật là báo một việc không xảy ra.
        if result.da_dung or command.action == "query":
            if state is None:
                return Speech(needs_state=True)
            return Speech(_capitalize(self._answer(command, state)))

        spec = self.caps.catalog.spec(self.caps.devices[command.device].type)
        key = command.action
        if spec.mode_as_action:
            key = "scene_off" if command.action == "turn_off" else "scene_on"
        if key == "set_level" and self.set_level_zero and command.value == 0:
            unit = dev_value.unit(command.unit) if (dev_value := self.caps.devices[command.device].value) else None
            if unit is not None and unit.lo == 0:
                return Speech(self.set_level_zero)

        template = self.actions.get(key)
        if template is None:
            return Speech(self._error(result))
        return Speech(_clean(template.format(**self._slots(command))))

    def options_for(self, hint: Optional[str], actions: list[str]) -> list[str]:
        """Thiết bị có tên chứa chữ chưa khớp VÀ làm được việc người ta muốn.

        "bật đèn" -> đèn viền, đèn trần, đèn sương mù. Sinh từ caps + từ điển nên
        không bao giờ nhắc tới thứ xe không có.
        """
        if not hint:
            return []
        out = []
        for name, dev in self.caps.devices.items():
            allowed = self.caps.effective_actions(dev)
            if actions and not any(a in allowed for a in actions):
                continue
            for alias in self.lex.aliases_of(DEVICE, name):
                if hint in alias.split() and alias not in out:
                    out.append(alias)
                    break
        return out[:MAX_OPTIONS]

    def _choices(self, device_id: Optional[str]) -> str:
        """Gợi ý động từ hợp lệ, sinh từ caps: 'mở hay đóng', 'gập hay mở'."""
        if not device_id or device_id not in self.caps.devices:
            return ""
        label = self.name_of(DEVICE, device_id)
        verbs: list[str] = []
        for action in self.caps.effective_actions(self.caps.devices[device_id]):
            if action == "query":
                continue
            # "mở gương" đã chứa sẵn tên thiết bị -> chọn alias ngắn gọn hơn,
            # nếu không câu sẽ thành "gập hay mở gương gương".
            names = [n for n in self.lex.aliases_of(ACTION, action) if label not in n]
            if names and names[0] not in verbs:
                verbs.append(names[0])
            if len(verbs) == 2:
                break
        return " hay ".join(verbs)

    def _error(self, result: Result) -> str:
        template = self.errors.get(result.code or "") or self.errors.get("default", "")
        device_id = result.device or (result.command.device if result.command else None)
        device = self.name_of(DEVICE, device_id) if device_id else ""
        mode = ""
        if result.command is not None and result.command.mode:
            mode = self.name_of(MODE, result.command.mode)
        elif result.command is None:
            match = re.search(r"'([^']+)'", result.reason or "")
            if match:
                mode = self.name_of(MODE, match.group(1))
        verb = result.verb or ""
        sentence = _clean(template.format(device=device, mode=mode, verb=verb,
                                          choices=self._choices(device_id),
                                          range=self._range(result)))
        options = self.options_for(result.hint, result.actions)
        if options and result.code == Code.DEVICE_REQUIRED:
            listed = ", ".join(options[:-1]) + " hay " + options[-1] if len(options) > 1 else options[0]
            sentence = _clean(f"Anh/chị muốn {verb} {result.hint} nào ạ? {listed.capitalize()}?")
        return sentence
