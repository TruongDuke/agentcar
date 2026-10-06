"""Từ điển tiếng Việt: chữ người nói → id trong caps.

Chuẩn hoá trước khi so khớp (bỏ dấu, thường hoá) nên không cần liệt kê biến thể dấu.
Bảng alias xuất ra đã sắp theo độ dài giảm dần — matcher chỉ việc longest-match.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import yaml

from .caps import Caps

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "caps" / "lexicon.vi.yaml"

DEVICE, ITEM, ZONE, MODE, UNIT, ACTION = "device", "item", "zone", "mode", "unit", "action"
# "hết cỡ", "kịch trần" — không phải mode, không phải đơn vị: là GIÁ TRỊ nói bằng
# lời thay vì bằng số. Phân giải thành biên trên/dưới của đơn vị, nên phải biết
# thiết bị mới quy được, y như số.
CUC_TRI = "cuc_tri"

_PUNCT = re.compile(r"[^\w%\s\x00]", re.UNICODE)
# "50%" phải thành hai token: '%' là alias đơn vị, còn '50' là số. Dính liền thì
# '50%' không phải số (parser bỏ qua) mà cũng không phải alias — con số bốc hơi
# và "hạ kính 50%" thành MỞ TOANG cửa kính. '%' đứng riêng vẫn giữ nguyên.
_PCT_GLUED = re.compile(r"(?<=\w)%")
# Dấu TRỪ đứng ngay trước chữ số là DẤU CỦA SỐ, không phải dấu câu. Trước đây
# _PUNCT xoá nó nên "thêm -3 nấc" thành "thêm 3 nấc" — xe tăng 3 nấc trong khi
# người ta bảo giảm. Gạch nối trong chữ ("mát-xa") vẫn bị xoá như cũ vì phía
# trước nó là chữ cái.
_DAU_AM = re.compile(r"(?<![\w])-(?=\d)")
_SPACES = re.compile(r"\s+")


def normalize(text: str, keep_diacritics: bool = False) -> str:
    """'Điều Hoà!' -> 'dieu hoa' (hoặc 'điều hoà' nếu keep_diacritics).

    CẢNH BÁO: bỏ dấu làm mất phân biệt trong tiếng Việt — 'đỏ' và 'độ' cùng ra 'do',
    'cam' và 'câm' cùng ra 'cam'. Vì vậy matcher phải thử tầng CÓ DẤU trước, tầng bỏ
    dấu chỉ là fallback cho ASR sai dấu. Xem Lexicon.ambiguous_only_stripped().
    """
    text = unicodedata.normalize("NFC", text or "").lower()
    if not keep_diacritics:
        text = unicodedata.normalize("NFD", text)
        text = "".join(c for c in text if unicodedata.category(c) != "Mn")
        text = unicodedata.normalize("NFC", text).replace("đ", "d")
    text = _PCT_GLUED.sub(" %", text)
    text = _DAU_AM.sub("\x00", text)          # giữ tạm; _PUNCT có chừa \x00
    text = _PUNCT.sub(" ", text)
    text = text.replace("\x00", "-")
    return _SPACES.sub(" ", text).strip()


def tone_key(text: str) -> str:
    """Khoá gộp cách đặt dấu: 'hòa' và 'hoà' cùng một khoá, 'đó' và 'đỏ' thì không.

    Tiếng Việt có hai quy ước đặt dấu thanh ('hòa' kiểu cũ, 'hoà' kiểu mới) — cùng
    một chữ. Nhưng khác DẤU thì khác chữ. Nên khoá = chữ đã bỏ dấu + tập dấu thanh,
    bỏ qua dấu rơi vào nguyên âm nào.

    'đ' phải đếm riêng. Nó là CHỮ CÁI, không phải dấu: NFD không tách nó ra nên nó
    biến mất trong normalize(), khiến 'đừng' và 'dừng' cùng một khoá — hai từ NGƯỢC
    NGHĨA nhau, mà 'dừng' lại là alias của turn_off. Hậu quả: "đừng bật sấy kính"
    ra lệnh TẮT sấy kính. Tương tự 'đóng'/'dòng', 'đi'/'di'.
    """
    out = []
    for token in normalize(text, keep_diacritics=True).split():
        decomposed = unicodedata.normalize("NFD", token)
        marks = sorted(c for c in decomposed if unicodedata.category(c) == "Mn")
        stroke = "\u0111" * token.count("\u0111")
        out.append(normalize(token) + "\u0001" + "".join(marks) + stroke)
    return " ".join(out)


@dataclass(frozen=True)
class Entry:
    """Một alias đã chuẩn hoá, trỏ tới một id trong caps."""

    alias: str          # đã bỏ dấu — tầng khớp dự phòng cho ASR mất dấu
    accented: str       # giữ dấu, đã thường hoá — để hiển thị và so khớp chặt
    folded: str         # gộp cách đặt dấu — tầng khớp chính
    surface: str        # dạng gốc, để hiển thị
    kind: str           # device | item | zone | mode | unit | action
    target: str         # id trong caps
    device: Optional[str] = None  # item/zone chỉ có nghĩa trong 1 device


@dataclass
class Lexicon:
    entries: list[Entry] = field(default_factory=list)
    path: Optional[Path] = None
    yes_phrases: set[str] = field(default_factory=set)
    no_phrases: set[str] = field(default_factory=set)
    # Vùng XE KHÔNG CÓ (hàng ghế 3, ghế giữa) — khác hẳn vùng chỉ không hợp lệ
    # với MỘT thiết bị (quạt không nhận trái/phải, nhưng xe có trái phải). Hai
    # loại cùng ra mã VA_INVALID_ZONE nên phải phân biệt ở đây: từ chối "hàng
    # ghế 3" là câu trả lời ĐÚNG, còn "chân bên phải" thì nên hỏi cloud.
    vung_xe_khong_co: set[str] = field(default_factory=set)

    def answer(self, text: str) -> Optional[bool]:
        """True = đồng ý, False = từ chối, None = không phải câu trả lời.

        So khớp TRỌN câu: 'không' một mình là từ chối, nhưng 'cửa kính mở không'
        là câu hỏi nên phải trả None.
        """
        alias = tone_key(text)
        if alias in self.yes_phrases:
            return True
        if alias in self.no_phrases:
            return False
        return None

    # ------------------------------------------------------------- tra cứu
    def sorted_entries(self) -> list[Entry]:
        """Dài trước — longest match thắng."""
        return sorted(self.entries, key=lambda e: (-len(e.alias), e.alias))

    def lookup(self, text: str, kind: Optional[str] = None) -> list[Entry]:
        """Khớp có dấu trước; không có thì mới hạ chuẩn xuống tầng bỏ dấu."""
        pool = [e for e in self.entries if kind is None or e.kind == kind]
        hit = [e for e in pool if e.folded == tone_key(text)]
        return hit or [e for e in pool if e.alias == normalize(text)]

    def aliases_of(self, kind: str, target: str, device: Optional[str] = None) -> list[str]:
        return [
            e.surface
            for e in self.entries
            if e.kind == kind and e.target == target and (device is None or e.device in (None, device))
        ]

    def targets(self, kind: str) -> set[str]:
        return {e.target for e in self.entries if e.kind == kind}

    # ------------------------------------------------------------- chẩn đoán
    def ambiguous_only_stripped(self) -> dict[str, list[Entry]]:
        """Xung đột SINH RA do bỏ dấu — giữ dấu là hết nhập nhằng."""
        return {
            alias: group
            for alias, group in self.exact_collisions().items()
            if len({g.accented for g in group}) > 1
        }

    def exact_collisions(self) -> dict[str, list[Entry]]:
        """Cùng một chuỗi trỏ tới nhiều id khác nhau.

        Cùng một zone id dùng lại ở nhiều device KHÔNG phải xung đột.
        """
        buckets: dict[str, list[Entry]] = {}
        for e in self.entries:
            buckets.setdefault(e.alias, []).append(e)
        out = {}
        for alias, group in buckets.items():
            if len({(g.kind, g.target) for g in group}) > 1:
                first: dict[tuple, Entry] = {}
                for g in group:
                    first.setdefault((g.kind, g.target), g)
                out[alias] = list(first.values())
        return out

    def containments(self) -> list[tuple[Entry, Entry]]:
        """(ngắn, dài): alias ngắn nằm trong alias dài → bắt buộc longest-match."""
        seen: dict[tuple, tuple[Entry, Entry]] = {}
        by_len = self.sorted_entries()
        for long in by_len:
            for short in by_len:
                if len(short.alias) >= len(long.alias):
                    continue
                key = ((short.kind, short.target), (long.kind, long.target))
                if key[0] == key[1] or key in seen:
                    continue
                if re.search(rf"\b{re.escape(short.alias)}\b", long.alias):
                    seen[key] = (short, long)
        return list(seen.values())


def _add(entries: list[Entry], kind: str, target: str, surfaces: Iterable[str], device=None) -> None:
    seen = set()
    for s in surfaces or []:
        alias = normalize(s)
        if alias and alias not in seen:
            seen.add(alias)
            entries.append(Entry(alias=alias, accented=normalize(s, keep_diacritics=True),
                                 folded=tone_key(s), surface=s, kind=kind,
                                 target=target, device=device))


def load_lexicon(caps: Caps, path: Path | str = DEFAULT_PATH) -> Lexicon:
    """Hợp nhất names.vi trong caps với file lexicon; caps không bị ghi đè."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries: list[Entry] = []

    for name, dev in caps.devices.items():
        _add(entries, DEVICE, name, dev.names_for("vi"))
        for item_key, item in dev.items.items():
            _add(entries, ITEM, item_key, (item or {}).get("vi"), device=name)

    for name, surfaces in (raw.get("devices") or {}).items():
        if name in caps.devices:
            _add(entries, DEVICE, name, surfaces)

    zones = raw.get("zones") or {}
    shared = zones.get("shared") or {}
    per_device = zones.get("per_device") or {}
    unsupported = zones.get("unsupported") or {}
    vung_khong_co = set(unsupported)
    per_dev_unsup: dict[str, dict[str, list]] = {}
    for zname, spec in {**(zones.get("unsupported_per_device") or {}),
                        **(zones.get("ambiguous_per_device") or {})}.items():
        for dev_name in spec.get("devices") or []:
            per_dev_unsup.setdefault(dev_name, {})[zname] = spec.get("aliases") or []
    for name, dev in caps.devices.items():
        table = per_device.get(name) or {}
        for zone in dev.zones:
            # CỘNG per_device vào dùng chung, không thay thế. Khai riêng là để
            # THÊM chữ chỉ thiết bị đó mới hiểu ("kính hậu" của defrost, "trái"
            # của gương), chứ không phải để bỏ đi chữ ai cũng hiểu — trước đây
            # khai defrost.rear là mất luôn "sau"/"phía sau" của defrost.
            # Dùng chung đứng TRƯỚC để giữ nguyên tên hiển thị trong câu trả lời.
            _add(entries, ZONE, zone,
                 list(shared.get(zone) or []) + list(table.get(zone) or []), device=name)
        # Vùng xe không điều khiển tới vẫn phải vào từ điển: nhận ra rồi từ chối
        # thì người dùng biết vì sao, còn bỏ qua thì chữ số trong "hàng 3" trôi
        # xuống thành mức. resolve sẽ trả VA_INVALID_ZONE vì không nằm trong
        # dev.zones — đúng SUGGEST của BA.
        if dev.zones:
            for zone, surfaces in unsupported.items():
                _add(entries, ZONE, zone, surfaces, device=name)
            for zone, surfaces in (per_dev_unsup.get(name) or {}).items():
                _add(entries, ZONE, zone, surfaces, device=name)

    for huong, surfaces in (raw.get("cuc_tri") or {}).items():
        _add(entries, CUC_TRI, huong, surfaces)
    for mode, surfaces in (raw.get("modes") or {}).items():
        _add(entries, MODE, mode, surfaces)
    for unit, surfaces in (raw.get("units") or {}).items():
        _add(entries, UNIT, unit, surfaces)
    for action, surfaces in (raw.get("actions") or {}).items():
        _add(entries, ACTION, action, surfaces)

    # khử trùng lặp tuyệt đối (caps và lexicon khai cùng một chữ)
    unique: dict[tuple, Entry] = {}
    for e in entries:
        unique.setdefault((e.alias, e.kind, e.target, e.device), e)

    answers = raw.get("confirmations") or {}
    return Lexicon(
        entries=list(unique.values()),
        path=Path(path),
        yes_phrases={tone_key(t) for t in (answers.get(True) or answers.get("yes") or [])},
        no_phrases={tone_key(t) for t in (answers.get(False) or answers.get("no") or [])},
        vung_xe_khong_co=vung_khong_co,
    )


# ----------------------------------------------------------------- coverage
@dataclass
class Coverage:
    devices: list[str] = field(default_factory=list)
    zones: list[tuple[str, str]] = field(default_factory=list)
    modes: list[tuple[str, str]] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    units: list[tuple[str, str]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not (self.devices or self.zones or self.modes or self.actions or self.units)


def coverage(caps: Caps, lex: Lexicon) -> Coverage:
    """Cái gì trong caps mà chưa có chữ tiếng Việt nào gọi tên được."""
    gaps = Coverage()

    for name, dev in caps.devices.items():
        if dev.cloud_only:
            continue  # cloud_only cố tình không có grammar edge
        if not lex.aliases_of(DEVICE, name):
            gaps.devices.append(name)
        for zone in dev.zones:
            if not lex.aliases_of(ZONE, zone, device=name):
                gaps.zones.append((name, zone))
        for mode in dev.modes:
            if not lex.aliases_of(MODE, mode):
                gaps.modes.append((name, mode))
        if dev.value is not None and dev.value.is_number:
            for unit in dev.value.units:
                if not lex.aliases_of(UNIT, unit):
                    gaps.units.append((name, unit))

    used_actions = {a for d in caps.devices.values() for a in caps.effective_actions(d)}
    for action in sorted(used_actions):
        if action in {m for d in caps.devices.values() for m in d.modes}:
            continue  # mode_as_action: đã tính ở phần modes
        if not lex.aliases_of(ACTION, action):
            gaps.actions.append(action)

    return gaps
