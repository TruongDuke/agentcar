"""Tầng [1] — tầng edge: câu tiếng Việt → RawCommand, chạy ngoại tuyến.

Quy tắc đã chốt trong tầng này:
  M1. Longest match, quét từ trái sang; tầng có dấu thử trước, bỏ dấu là dự phòng.
  M2. Câu không nêu tên thiết bị thì suy từ mode/item/zone, miễn là suy ra duy nhất
      ("cắm trại" -> scene_mode, "spotify" -> app_control, "rèm" -> sunroof).
  M3. Phân biệt lệnh tuyệt đối và lệnh tương đối bằng từ nối, không bằng động từ:
      "giảm điều hoà xuống 20 độ" -> set_level(20)   (có giới từ đích)
      "giảm 2 độ"                 -> decrease(2)     (không có giới từ đích)
      "tăng thêm 5"               -> increase(5)     (có từ chỉ lượng thêm)
  M4. Câu nhiều lệnh tách ở từ nối NẰM NGOÀI mọi alias đã khớp, nên "thổi mặt và
      chân" không bị cắt đôi.
  M5. Lệnh sau trong câu thiếu thiết bị thì kế thừa thiết bị của lệnh trước.
Không đoán mò: thiếu thông tin thì trả về ít lệnh hơn, phần còn lại để tầng sau lo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .caps import Caps
from .lexicon import (ACTION, CUC_TRI, DEVICE, ITEM, MODE, UNIT, ZONE, Entry, Lexicon,
                       normalize, tone_key)
from .numbers import parse_number
from .resolve import AMBIGUOUS_ZONE
from .plan import RawCommand

def bare(text: str) -> str:
    """Dạng bỏ dấu, dùng để so mọi tập HƯ TỪ bên dưới.

    Nếu so bằng chuỗi có dấu thì câu ASR mất dấu đi qua hết: "len" không khớp
    "lên" nên mất giới từ đích, "voi" không khớp "với" nên mất từ nối, "nham"
    không khớp "nhầm" nên bỏ qua việc người ta sửa ý. Đã gặp thật cả ba.
    """
    return normalize(text)


def bare_set(words) -> set:
    return {normalize(w) for w in words}

CONNECTORS = bare_set({"rồi", "và", "xong", "đồng thời", "sau", "tiếp", "với", "kèm", "lẫn"})
TARGET_PREPS = bare_set({"xuống", "lên", "về", "còn", "tới", "đến", "thành"})
DELTA_MARKERS = bare_set({"thêm", "bớt", "nữa"})
# "lên 1 chút", "giảm 1 tí": con số ở đây thuộc về thành ngữ "một chút", không
# phải mức muốn tới. Bỏ số đi thì nudge của caps lo phần còn lại — đúng cái QC
# mong (step = nudge). Không bỏ thì "tăng rèm lên 1 chút" thành ĐẶT mức 1.
MO_HO_IT = bare_set({"chút", "tí", "xíu", "tẹo", "chút xíu", "tí xíu", "chút đỉnh"})
# "không/chưa/gì/nào" chỉ tính khi đứng CUỐI câu, vì còn nghĩa khác:
#   "mở cửa kính đi nào" là giục, "điều hoà đang bật không" mới là hỏi.
QUERY_TAILS = bare_set({"không", "chưa", "gì", "nào"})
# "mấy/sao" thì ở đâu trong câu cũng là hỏi: "điều hoà mấy độ rồi", "đèn viền sao rồi".
QUERY_WORDS = bare_set({"mấy", "sao"})
# Trợ từ giục. Đứng ngay trước "nào/gì" thì cả cụm là giục chứ không phải hỏi:
#   "mở cửa kính đi nào" (giục)  vs  "mở app nào" (hỏi)
URGING = bare_set({"đi", "lên", "thôi", "nhé", "nha", "coi"})
# Hư từ: không mang nội dung, nên KHÔNG tính là "chữ lạ" khi đếm ở M11.
# "sưởi ghế đang mức mấy" chỉ có mỗi "đang" là hư từ → vẫn là lệnh hỏi hợp lệ.
# M15: người ta đổi ý giữa câu. Sau mấy từ này thì phần TRƯỚC bị bỏ:
#   "bật điều hòa 24 độ à không 22 thôi"          -> 22
#   "mở cửa kính thôi đóng lại"                   -> đóng
#   "bật đèn viền màu đỏ à không màu xanh dương"  -> xanh dương
# "thôi" chỉ tính là sửa khi CÒN CHỮ ĐẰNG SAU: "mở cốp thôi" là giục, không phải sửa.
CORRECTION = bare_set({"à không", "à thôi", "à quên", "đổi lại", "sửa lại", "nhầm",
                       "ý là", "mà thôi", "không phải", "à sai", "lộn"})
CORRECTION_SOFT = bare_set({"thôi", "không"})

# M21: từ PHỦ ĐỊNH huỷ lệnh nằm SAU nó — ngược chiều CORRECTION (huỷ phần trước).
# BA chốt 29/09: "đừng bật sấy kính" là KHÔNG LÀM GÌ, không phải tắt sấy kính.
# Chỉ huỷ trong MỆNH ĐỀ của nó: "đừng đóng cổng sạc, mở nó ra" vẫn phải mở, nên
# kiểm tra chạy trên từng segment chứ không trên cả câu.
# Không nhận "thôi"/"khỏi" đứng một mình: "thôi" là từ giục (URGING — "mở cốp
# thôi"), "khỏi" hay đi với "thoát khỏi"/"ra khỏi" không mang nghĩa phủ định.
#
# Tập này so CÓ DẤU, khác mọi tập hư từ khác. Bỏ dấu thì "chớ" trùng "cho"
# ("cho mát hơn", "bật điều hòa cho cả xe"), "cấm" trùng "cam" (màu đèn viền),
# "đừng" trùng "dừng" (alias turn_off). Nuốt nhầm một lệnh THẬT tệ hơn bỏ sót một
# câu phủ định, nên ở đây chịu mất câu ASR không dấu để đổi lấy an toàn.
NEGATION = {"đừng", "chớ", "cấm", "khoan", "đừng có", "không cần",
            "chẳng cần", "khỏi cần", "không muốn", "chưa cần",
            "thôi khỏi", "khỏi phải", "không nên"}

# "MẶC KỆ": người ta nói rõ là ĐỪNG ĐỘNG VÀO, khác hẳn phủ định. "Đừng bật X"
# theo QC là TẮT X (NGUOC_CHIEU bên dưới), nhưng "chả cần biết X đang bật không"
# thì không có lệnh nào để đảo — chỉ là bảo thôi đi. Nên tập này CHẶN HẲN, và
# chặn ở cả hai chính sách qc/ba.
#
# Đo trên golden trước khi thêm: ba mẫu này bắt 22/137 câu phải im mà KHÔNG nuốt
# câu nào trong 24.623 câu phải ra lệnh. Hai mẫu họ hàng đã bị loại vì đắt:
# "cứ…vậy/thế" bắt 6 nhưng nuốt 2, "cứ để" bắt 12 nhưng nuốt 7 — "cứ" phần lớn
# là từ giục ("cứ bật lên đi") và "để" là alias set_level ("cứ để 22 độ").
# Nuốt một lệnh THẬT tệ hơn bỏ sót một câu phải im.
MAC_KE = {"kệ", "chả cần biết", "chẳng cần biết", "không cần biết", "bỏ qua việc"}
MAC_KE_NOTE = "mệnh đề bảo đừng động vào"

# Chữ nói thẳng "cái theo sau là một chế độ" (M22). Bản thân "chế độ" là alias
# thiết bị scene_mode, nên khi nó đứng trước một mode của thiết bị KHÁC thì phải
# nhường — xem chỗ dựng candidates.
DANH_DAU_MODE = {"chế độ", "kiểu", "mode", "chế độ của", "kiểu của"}

# Thiết bị mà "lên" nghĩa là ĐÓNG: tấm kính trượt LÊN để đóng. "Kéo kính lên"
# là đóng (QC 9 câu), nhưng cụm alias "kéo lên" không khớp nổi vì chữ "kính"
# chen vào giữa, còn mỗi "lên" -> increase, và xe hạ kính xuống thêm.
#
# CHỈ cửa kính. Mỗi thiết bị một chiều, không suy chung được — QC cho thấy:
#   cửa sổ trời  "lên"   = MỞ    ("độ mở cửa sổ trời tăng lên")
#   cốp          "xuống" = ĐÓNG  ("hạ cốp xe xuống")
# Quét cả ba thì sai hai. Thiết bị mới phải có câu QC làm chứng mới được thêm.
LEN_LA_DONG = {"window"}

# Hành động ngược chiều, dùng khi chính sách `phu_dinh` để "qc": "đừng bật X" là
# TẮT X chứ không phải không làm gì (QC defrost E268, foglight E55 — 684 câu).
# Chỉ đảo được cặp có nghĩa đối xứng; mode/item không có chiều nên bỏ qua.
NGUOC_CHIEU = {"turn_on": "turn_off", "turn_off": "turn_on",
               "open": "close", "close": "open",
               "fold": "unfold", "unfold": "fold",
               "increase": "decrease", "decrease": "increase"}

FUNCTION_WORDS = bare_set({"đang", "rồi", "thì", "là", "mà", "ạ", "à", "ơi", "cho",
                           "giúp", "hộ", "với", "cái", "của", "em", "anh", "chị",
                           "tôi", "mình", "được", "không", "chưa", "gì", "nào",
                           "mấy", "sao", "vậy", "thế", "để"})
# M9: câu có điều kiện hoặc hẹn giờ thì TUYỆT ĐỐI không chạy ngay. "Mở cửa sổ trời
# khi nào tới nhà" mà mở luôn là sai nguy hiểm — chuyển cho tầng suy luận từ chối.
# M20: động từ YẾU — chỉ tính là lệnh khi có CON SỐ ngay sau. "để 22 độ" là lệnh,
# "chỗ để đồ" / "để mình" / "để xem" thì không.
WEAK_VERBS = bare_set({"để"})

CONDITIONAL = ("khi nào", "lúc nào", "khi tới", "khi đến", "sau khi", "trước khi",
               "nếu", "hễ", "lát nữa", "phút nữa", "tiếng nữa", "hẹn giờ", "đúng giờ")

# "nếu được thì bạn hãy bật điều hòa giúp" KHÔNG phải câu điều kiện — "nếu" ở
# đây là nói lịch sự, giống "làm ơn". M9 bắt được chữ "nếu" rồi từ chối tại chỗ
# và CỐ Ý không gọi cloud, nên cả câu mất trắng.
#
# Đo trên golden: cả 30 câu có chữ "nếu" mà QC mong ra lệnh đều là dạng lịch sự
# này, và bộ phủ định không có câu "nếu" nào. Nên loại chúng ra là an toàn.
LICH_SU = ("nếu được", "nếu có thể", "nếu tiện", "nếu không phiền", "nếu rảnh",
           "nếu anh", "nếu chị", "nếu em", "nếu bạn", "nếu ok")

ALIAS, NUMBER, CONNECTOR, WORD = "alias", "number", "connector", "word"

# Action ẢO: không tồn tại trong caps, agent dịch lại thành lệnh thật trước khi
# xuống tầng resolve. "Bật tiếng lại" = đặt về mức trước khi tắt, mà mức đó là
# state của hội thoại chứ không phải năng lực của thiết bị (xem D4).
UNMUTE = "unmute"


@dataclass
class Span:
    start: int
    end: int
    kind: str
    entries: list[Entry] = field(default_factory=list)
    value: Optional[float] = None

    def targets(self, kind: str) -> list[Entry]:
        return [e for e in self.entries if e.kind == kind]


@dataclass
class MatchResult:
    commands: list[RawCommand] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    # M8: nghe rõ động từ nhưng không biết áp lên thiết bị nào ("bật", "tăng lên").
    # Hỏi lại tại chỗ tốt hơn đẩy lên LLM — model cũng không đoán được.
    orphan_verb: Optional[str] = None          # chữ người ta nói: "tắt"
    orphan_actions: list[str] = field(default_factory=list)   # action tương ứng
    orphan_hint: Optional[str] = None          # chữ chưa khớp đi kèm: "đèn"
    has_verb: bool = False                     # câu có động từ nào không
    conditional: bool = False
    vague: bool = False                        # có "cái kia", "cái đó"...
    # Mệnh đề có dấu hiệu MẶC KỆ ("chả cần biết", "kệ", "bỏ qua việc"). Tầng [1b]
    # KHÔNG được ghi đè: model không có lớp "đây không phải lệnh" nên câu nào nó
    # cũng gán nhãn. Khác hẳn M11 — M11 là suy đoán và nổ trên 49,3% số câu tầng
    # luật bỏ sót nên không dùng phủ quyết được; đây là dấu hiệu TỪ VỰNG tường
    # minh, đo được 0/24.623 câu phải-ra-lệnh bị nuốt.
    mac_ke: bool = False
    verbs: list[str] = field(default_factory=list)       # mọi action nghe được
    verb_words: list[str] = field(default_factory=list)  # đúng chữ người ta nói
    # Thiết bị/mục/chế độ nghe ra được, KỂ CẢ khi không ghép nổi thành lệnh.
    # Đây là tín hiệu để phân loại lý do trượt trước khi gọi cloud.
    mentioned: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.commands)


class Matcher:
    def __init__(self, caps: Caps, lex: Lexicon, vague: tuple[str, ...] = ()):
        self.caps = caps
        self.lex = lex
        self.vague = tuple(vague)
        self._folded: dict[tuple[str, ...], list[Entry]] = {}
        self._stripped: dict[tuple[str, ...], list[Entry]] = {}
        for e in lex.entries:
            self._folded.setdefault(tuple(e.folded.split()), []).append(e)
            self._stripped.setdefault(tuple(e.alias.split()), []).append(e)
        self._maxn = max((len(k) for k in self._folded), default=1)
        self._mode_owner: dict[str, set[str]] = {}
        for name, dev in caps.devices.items():
            for mode in dev.modes:
                self._mode_owner.setdefault(mode, set()).add(name)

    # ------------------------------------------------------------ quét span
    # Dấu phẩy ngăn lệnh: "bật điều hoà, mở nhạc". Nhưng "22,5 độ" là số thập phân
    # nên chỉ tách khi dấu phẩy KHÔNG nằm giữa hai chữ số.
    _COMMA = re.compile(r"(?<!\d)\s*[,;]\s*|\s*[,;]\s*(?!\d)")

    def scan(self, text: str) -> tuple[list[str], list[Span]]:
        text = self._COMMA.sub(" rồi ", text or "")
        tokens = normalize(text, keep_diacritics=True).split()
        folded = [tone_key(t) for t in tokens]
        stripped = [normalize(t) for t in tokens]
        # Tầng bỏ dấu CHỈ dành cho ASR mất dấu. Nếu chữ người ta nói vốn CÓ dấu mà
        # không khớp, thì đó là từ khác chứ không phải sai dấu: "đó" không được
        # khớp thành "đỏ", "cám" không được khớp thành "cam".
        undotted = [t == s_ for t, s_ in zip(tokens, stripped)]
        spans: list[Span] = []
        i = 0
        while i < len(tokens):
            hit = None
            # Longest-match chỉ tối đa hoá span ĐẦU TIÊN, không tối đa hoá tổng
            # phủ. "mở màn hình wifi hotspot": "màn hình wifi" (3 chữ, item wifi)
            # thắng tại chỗ, bỏ rơi "hotspot" — trong khi "màn hình" + "wifi
            # hotspot" phủ 4 chữ và ra đúng item wifi_hotspot. Nhìn trước MỘT
            # alias rồi chọn theo tổng. Duyệt từ dài xuống và so bằng `>` nên
            # hoà là giữ nguyên nết cũ: chỉ đổi khi cụm ngắn phủ được NHIỀU HƠN.
            dai, entries = self._alias_dai_nhat(i, folded, stripped, undotted,
                                                len(tokens))
            if entries:
                tiep, _ = self._alias_dai_nhat(i + dai, folded, stripped,
                                               undotted, len(tokens))
                # Cụm dài nhất mà VẪN nối được alias ngay sau thì không bỏ rơi chữ
                # nào — giữ nguyên, khỏi dò tiếp. Đây là đường đi của gần hết câu,
                # và tầng edge có ngân sách deadline_ms nên không được trả giá.
                if tiep == 0:
                    for size in range(dai - 1, 0, -1):
                        nho = self._folded.get(tuple(folded[i : i + size]))
                        if nho is None and all(undotted[i : i + size]):
                            nho = self._stripped.get(tuple(stripped[i : i + size]))
                        if not nho:
                            continue
                        sau, _ = self._alias_dai_nhat(i + size, folded, stripped,
                                                      undotted, len(tokens))
                        if size + sau > dai:
                            dai, entries = size, nho
                            break
                hit = Span(i, i + dai, ALIAS, list(entries))
            if hit is not None:
                spans.append(hit)
                i = hit.end
                continue

            value, used = parse_number(tokens, i)
            if value is not None:
                spans.append(Span(i, i + used, NUMBER, value=value))
                i += used
                continue

            kind = CONNECTOR if bare(tokens[i]) in CONNECTORS else WORD
            spans.append(Span(i, i + 1, kind))
            i += 1
        return tokens, self._demote_weak_verbs(spans)

    def _alias_dai_nhat(self, i: int, folded, stripped, undotted, ntok: int):
        """Cụm alias dài nhất bắt đầu tại i — (số chữ, entries), (0, None) nếu không có."""
        for size in range(min(self._maxn, ntok - i), 0, -1):
            entries = self._folded.get(tuple(folded[i : i + size]))
            if entries is None and all(undotted[i : i + size]):
                entries = self._stripped.get(tuple(stripped[i : i + size]))
            if entries:
                return size, entries
        return 0, None

    @staticmethod
    def _demote_weak_verbs(spans: list[Span]) -> list[Span]:
        """M20: động từ YẾU không có số đi kèm thì không phải lệnh.

        "để" là alias của set_level vì "để 22 độ" là lệnh thật. Nhưng phần lớn
        thời gian nó là liên từ mục đích hoặc nằm trong danh từ ghép: "chỗ để đồ",
        "để mình", "để xem", "mở màn hình để đặt lịch sạc". Trong 500 câu stress,
        "để" xuất hiện 41 lần và KHÔNG lần nào đứng trước một con số.

        Hại thật, không phải lo xa: "cái chỗ để đồ phía trước ấy, mở nó ra giùm"
        (xin mở cốp trước) — "để" làm tập ứng viên của vùng 'front' hẹp lại còn
        mỗi fan (defrost/fog_light không set_level được), qua được cả M18, và xe
        đi bật quạt.
        """
        out = []
        for idx, span in enumerate(spans):
            weak = (span.kind == ALIAS and span.entries
                    and all(e.kind == ACTION for e in span.entries)
                    and all(e.alias in WEAK_VERBS for e in span.entries))
            if weak:
                nxt = spans[idx + 1] if idx + 1 < len(spans) else None
                if nxt is None or nxt.kind != NUMBER:
                    out.append(Span(span.start, span.end, WORD))
                    continue
            out.append(span)
        return out

    def rescan(self, tokens: list[str], lo: int, hi: int, kind: str,
               keep=lambda e: True) -> Optional[Entry]:
        """M7: quét lại một đoạn để tìm alias BỊ alias dài hơn nuốt mất.

        Longest-match là đúng cho phần lớn câu, nhưng tiếng Việt hay lồng nhau:
        "tắt tiếng" nuốt "tiếng" (volume), "màn hình cài đặt" nuốt "cài đặt đèn".
        Bước này chỉ chạy khi thiếu thông tin bắt buộc, nên không phá longest-match.
        """
        folded = [tone_key(t) for t in tokens]
        stripped = [normalize(t) for t in tokens]
        undotted = [t == s_ for t, s_ in zip(tokens, stripped)]
        for size in range(min(self._maxn, hi - lo), 0, -1):
            for i in range(lo, hi - size + 1):
                entries = self._folded.get(tuple(folded[i : i + size])) or []
                if not entries and all(undotted[i : i + size]):
                    entries = self._stripped.get(tuple(stripped[i : i + size])) or []
                for e in entries:
                    if e.kind == kind and keep(e):
                        return e
        return None

    # ------------------------------------------------------------ ghép lệnh
    def match(self, text: str, previous_device: Optional[str] = None) -> MatchResult:
        """previous_device: thiết bị của lượt nói trước, để hiểu câu kiểu 'giảm 2 độ'."""
        tokens, spans = self.scan(text)
        result = MatchResult()
        flat = normalize(text, keep_diacritics=True)
        dieu_kien = [m for m in CONDITIONAL if m in flat]
        if dieu_kien == ["nếu"] and any(k in flat for k in LICH_SU):
            dieu_kien = []                      # chỉ là nói lịch sự
        if dieu_kien:
            result.conditional = True
            result.trace.append("có điều kiện/hẹn giờ — không chạy ngay (M9)")
            return result
        # Chỉ báo "bỏ qua" cho chữ MANG NỘI DUNG. Hư từ và từ sửa ý thực ra ĐƯỢC
        # dùng (cắt câu, phân biệt hỏi/giục) — báo là bỏ qua thì gây hiểu nhầm.
        ignorable = FUNCTION_WORDS | CORRECTION | CORRECTION_SOFT | URGING
        result.unmatched = [tokens[s.start] for s in spans
                            if s.kind == WORD and bare(tokens[s.start]) not in ignorable]

        for span in spans:
            for e in span.entries:
                if e.kind in (DEVICE, ITEM, MODE) and e.target not in result.mentioned:
                    result.mentioned.append(e.target)

        segments: list[list[Span]] = [[]]
        for span in spans:
            if span.kind == CONNECTOR:          # M4
                segments.append([])
            else:
                segments[-1].append(span)

        # M13: mảnh không có thiết bị VÀ không có động từ thì nó là THAM SỐ của mảnh
        # trước, không phải lệnh mới: "massage ghế với mức 2" là một lệnh.
        merged: list[list[Span]] = []
        for seg in segments:
            has_thing = any(sp.targets(DEVICE) or sp.targets(ITEM) or sp.targets(MODE)
                            for sp in seg)
            has_verb = any(sp.targets(ACTION) for sp in seg)
            if merged and seg and not has_thing and not has_verb:
                merged[-1].extend(seg)
            else:
                merged.append(seg)
        segments = merged

        result.has_verb = any(sp.targets(ACTION) for sp in spans if sp.kind == ALIAS)
        result.vague = any(w in flat or normalize(w) in normalize(text) for w in self.vague)
        result.verbs = [e.target for sp in spans for e in sp.targets(ACTION)]
        result.verb_words = [e.surface for sp in spans for e in sp.targets(ACTION)]
        previous: Optional[str] = previous_device   # M5
        carried: list[str] = []                    # M14
        for segment in segments:
            if not segment:
                continue
            raw, note = self._build(tokens, segment, previous, carried)
            found = [e.target for sp in segment for e in sp.targets(ACTION)]
            if found:
                carried = found
            if note:
                result.trace.append(note)
                if note.startswith(MAC_KE_NOTE):
                    result.mac_ke = True
            if raw is not None:
                result.commands.append(raw)
                previous = raw.device
            elif result.orphan_verb is None:
                # Dùng ĐÚNG CHỮ người ta nói: "mở" ánh xạ tới cả turn_on lẫn open,
                # hỏi lại bằng "bật" nghe như không nghe thấy gì.
                said = [e.surface for sp in segment for e in sp.targets(ACTION)]
                actions = [e.target for sp in segment for e in sp.targets(ACTION)]
                leftover = [tokens[sp.start] for sp in segment if sp.kind == WORD]
                # Chỉ hỏi lại khi câu GẦN NHƯ CHỈ CÓ mỗi động từ ("bật", "tắt đi").
                # Câu còn nhiều chữ lạ ("mở hết cỡ đi", "cho xe bay lên trời") thì
                # còn nội dung để suy — để tầng [2] thử, đừng cắt ngang.
                noise = sum(1 for sp in segment if sp.kind == WORD)
                has_number = any(sp.kind == NUMBER for sp in segment)
                if said and noise <= 1 and not has_number:
                    result.orphan_verb = said[0]
                    result.orphan_actions = actions
                    result.orphan_hint = leftover[0] if leftover else None
        return result

    def _pick_device(self, tokens: list[str], segment: list[Span],
                     previous: Optional[str]) -> tuple[Optional[str], str]:
        """Chọn thiết bị theo MỆNH ĐỀ CÓ ĐỘNG TỪ, không phải "alias nào thấy trước".

        M12. Câu thật hay lan man rồi mới ra lệnh ở cuối:
            "hôm nay tắc đường kinh khủng mà trời nóng nên bật điều hòa 22 độ đi"
        Chữ "kinh" trong "kinh khủng" là alias của cửa kính và đứng TRƯỚC, nên cách
        cũ cho nó thắng — hạ cửa kính khi người ta xin bật điều hoà.

        Thứ tự quyết định:
          1. ứng viên LÀM ĐƯỢC việc đang nói (động từ trong câu)
          2. trong số đó, ứng viên GẦN động từ nhất
          3. hoà nhau thì ưu tiên tên thiết bị > mục > chế độ > vùng
        """
        verbs = {e.target for sp in segment for e in sp.targets(ACTION)}
        verb_spans = [sp for sp in segment if sp.targets(ACTION)]

        # (thiết bị, ưu tiên theo loại, span, lý do)
        candidates: list[tuple[str, int, Span, str]] = []
        # M22: "chế độ X" / "kiểu X". Chữ đánh dấu nói thẳng X là một CHẾ ĐỘ, nên
        # X được quyền suy thiết bị dù chỉ có một chữ — M10 cấm vì "vàng", "nhảy",
        # "sóng" là từ thường ngày, nhưng "chế độ sóng" thì hết mơ hồ. Và chính
        # chữ đánh dấu ấy là alias thiết bị scene_mode: để nguyên thì nó thắng ở
        # ưu tiên 0 rồi nuốt mất thiết bị thật ("bật chế độ đấm vỗ ghế lái" ra
        # scene_mode, mode rơi mất vì msg_jump không thuộc scene_mode).
        bo_qua_ten: set[int] = set()
        for idx, span in enumerate(segment):
            def la_danh_dau(sp):
                return sp is not None and " ".join(tokens[sp.start:sp.end]) in DANH_DAU_MODE

            truoc = segment[idx - 1] if idx else None
            sau = segment[idx + 1] if idx + 1 < len(segment) else None
            # Tiếng Việt để chữ đánh dấu ĐẰNG TRƯỚC ("chế độ cắm trại"), tiếng Anh
            # để ĐẰNG SAU ("camp mode"). QC dùng cả hai.
            danh_dau = truoc if la_danh_dau(truoc) else (sau if la_danh_dau(sau) else None)
            if danh_dau is None:
                continue
            for e in span.targets(MODE):
                owners = self._mode_owner.get(e.target, set())
                if len(owners) == 1:
                    candidates.append((next(iter(owners)), 0, span, f"chế độ '{e.target}'"))
                    bo_qua_ten.add(id(danh_dau))
            # "chế độ sấy kính": chữ đánh dấu đứng trước một TÊN THIẾT BỊ thì nó
            # chỉ là chữ đệm, không phải scene_mode. Trước đây hai ứng viên cùng
            # ưu tiên 0 và "chế độ" gần động từ hơn nên thắng, ra MODE_REQUIRED.
            if any(e.target != "scene_mode" for e in span.targets(DEVICE)):
                bo_qua_ten.add(id(danh_dau))
        for span in segment:
            if id(span) not in bo_qua_ten:
                for e in span.targets(DEVICE):
                    candidates.append((e.target, 0, span, "tên"))
            for e in span.targets(ITEM):
                if e.device:
                    candidates.append((e.device, 1, span, f"mục '{e.target}'"))
            # M10: chế độ gọi bằng MỘT chữ không được dùng để suy thiết bị — "vàng",
            # "đỏ", "cam", "nhảy" đều là từ thường ngày.
            if span.end - span.start >= 2:
                for e in span.targets(MODE):
                    owners = self._mode_owner.get(e.target, set())
                    if len(owners) == 1:
                        candidates.append((next(iter(owners)), 2, span, f"chế độ '{e.target}'"))
            # M18: vùng chỉ được suy thiết bị khi ra DUY NHẤT — đúng như M2 nói,
            # nhưng trước đây chỉ MODE bị kiểm tra. "phía trước" thuộc cả fan,
            # defrost và fog_light nên thứ tự chèn quyết định: "mở chỗ để đồ phía
            # trước" (cốp trước) ra thành bật quạt. Nhập nhằng thì trả về không
            # biết, để tầng trên hỏi lại hoặc cloud suy — im lặng chọn bừa một
            # thiết bị rồi chạy luôn là kiểu sai tệ nhất.
            zoned = [e for e in span.targets(ZONE) if e.device]
            if zoned:
                owners = {e.device for e in zoned}
                fit = {d for d in owners if self._supports(d, verbs)} or owners
                if len(fit) == 1:
                    owner = next(iter(fit))
                    zone = next(e.target for e in zoned if e.device == owner)
                    candidates.append((owner, 3, span, f"vùng '{zone}'"))

        def distance(span: Span) -> int:
            if not verb_spans:
                return 0
            return min(min(abs(span.start - v.end), abs(v.start - span.end)) for v in verb_spans)

        if candidates:
            usable = [c for c in candidates if self._supports(c[0], verbs)]
            # Vùng chỉ được suy khi có động từ hợp lệ, nếu không "dẫn đường về nhà"
            # thành volume (vì 'dẫn đường' là một kênh âm lượng).
            pool = usable or [c for c in candidates if c[1] < 3]
            if pool:
                device, _, span, why = min(pool, key=lambda c: (distance(c[2]), c[1], c[2].start))
                near = " (cạnh động từ)" if usable and verb_spans else ""
                return device, f"thiết bị suy từ {why}{near}: {device}"

        # M5: chỉ kế thừa khi câu TRÔNG như mảnh lệnh, và thiết bị cũ làm được việc
        # đang nói. Sau "mở spotify", câu "tắt tiếng" không được gán vào app_control.
        has_number = any(sp.kind == NUMBER for sp in segment)
        if previous and (verbs or has_number):
            if not verbs or self._supports(previous, verbs):
                return previous, f"kế thừa thiết bị của lệnh trước: {previous}"
        return None, ""

    def _supports(self, device: str, verbs: set[str]) -> bool:
        return bool(verbs) and bool(verbs & set(self.caps.effective_actions(self.caps.devices[device])))

    @staticmethod
    def _corrected_at(tokens: list[str], lo: int, hi: int,
                      taken: Optional[set] = None) -> Optional[int]:
        """Vị trí từ sửa ý CUỐI CÙNG trong đoạn, nếu sau nó còn nội dung.

        Chỉ tính chữ LẺ: "nhăm" (số 5 trong "hai mươi nhăm") bỏ dấu trùng với
        "nhầm" (sửa ý), nên nếu không loại thì "bật điều hoà hai mươi nhăm độ"
        bị cắt mất số. Cùng họ bẫy máy/mấy, đỏ/độ.
        """
        taken = taken or set()
        window = [bare(t) if (lo + i) not in taken else "\x00"
                  for i, t in enumerate(tokens[lo:hi])]
        found = None
        for i in range(len(window)):
            two = " ".join(window[i:i + 2])
            one = window[i]
            if two in CORRECTION:           # "à không", "à quên"
                found = lo + i + 2
            elif one in CORRECTION:         # "nhầm", "lộn" — một chữ cũng tính
                found = lo + i + 1
            elif one in CORRECTION_SOFT and i + 1 < len(window):
                # M19: chữ sửa ý LẺ chỉ tính khi ngay sau nó là thứ CỤ THỂ thay cho
                # ý cũ — một alias hoặc một con số. "thôi đóng lại" là sửa thật,
                # nhưng "cho KHÔNG gian thêm hứng khởi" thì "không" chỉ là một nửa
                # của "không gian". Trước đây câu "mở ứng dụng nhạc lên cho không
                # gian thêm hứng khởi" bị cắt mất nửa đầu, nên "nhạc" rơi về nghĩa
                # thứ hai (kênh âm lượng) và agent đi tăng âm lượng thay vì mở app.
                if (lo + i + 1) in taken:
                    found = lo + i + 1
        return found if found is not None and found < hi else None

    @staticmethod
    def _negated(tokens: list[str], lo: int, hi: int, taken: set) -> set:
        """Chỉ số các chữ tạo nên từ phủ định trong mệnh đề. Rỗng = không phủ định.

        Chỉ tính chữ LẺ, y như `_corrected_at`: chữ đã khớp alias thì bỏ qua, nếu
        không "cấm" trong tên bài hát hay "khoan" (mũi khoan) sẽ nuốt mất lệnh.

        Trả về CHỈ SỐ chứ không phải bool: M11 đếm "chữ lạ" để biết câu có phải
        lệnh không, mà chính "không cần" lại bị đếm là lạ — "không cần sấy kính
        đâu" thành 2 chữ lạ và bị bỏ, trong khi QC mong nó ra lệnh tắt.
        """
        window = [t if (lo + i) not in taken else "\x00"
                  for i, t in enumerate(tokens[lo:hi])]
        for i in range(len(window)):
            if " ".join(window[i:i + 2]) in NEGATION:
                return {lo + i, lo + i + 1}
            if window[i] in NEGATION:
                return {lo + i}
        return set()

    @staticmethod
    def _mac_ke(tokens: list[str], lo: int, hi: int, taken: set) -> bool:
        """Mệnh đề có bảo "đừng động vào" không. Chỉ xét chữ LẺ, y như `_negated`:
        chữ đã khớp alias thì bỏ qua, không thì "kệ" trong tên bài hát nuốt lệnh."""
        window = [t if (lo + i) not in taken else "\x00"
                  for i, t in enumerate(tokens[lo:hi])]
        for i in range(len(window)):
            for size in (3, 2, 1):
                if " ".join(window[i:i + size]) in MAC_KE:
                    return True
        return False

    def _build(self, tokens, segment: list[Span], previous,
               carried: Optional[list[str]] = None) -> tuple[Optional[RawCommand], str]:
        lo, hi = segment[0].start, segment[-1].end
        # M15: có từ sửa ý thì chỉ xét phần SAU nó — phần trước là ý đã bị bỏ.
        taken = {i for sp in segment if sp.kind != WORD for i in range(sp.start, sp.end)}
        if self._mac_ke(tokens, lo, hi, taken):
            return None, MAC_KE_NOTE + " — không ra lệnh"
        phu_dinh_tai = self._negated(tokens, lo, hi, taken)
        negated = bool(phu_dinh_tai)
        if negated and self.caps.policy.get("phu_dinh", "qc") == "ba":
            return None, "mệnh đề có từ phủ định — không ra lệnh (theo BA)"
        cut = self._corrected_at(tokens, lo, hi, taken)
        if cut is not None:
            after = [sp for sp in segment if sp.start >= cut]
            if any(sp.kind in (ALIAS, NUMBER) for sp in after):
                # Chỉ giữ tên thiết bị ở phần đầu khi phần SAU không nêu thiết bị mới.
                # "bật sưởi ghế à không làm mát ghế" là đổi hẳn thiết bị.
                kept = [] if any(sp.targets(DEVICE) or sp.targets(ITEM) for sp in after) \
                    else [sp for sp in segment if sp.targets(DEVICE) or sp.targets(ITEM)]
                # Vùng cũng thuộc thiết bị, không thuộc tham số bị sửa: "sưởi ghế LÁI
                # mức 3 à nhầm mức 2" vẫn là ghế lái. Trừ khi phần sau nêu vùng mới.
                if not any(sp.targets(ZONE) for sp in after):
                    kept += [sp for sp in segment if sp.targets(ZONE)]
                # giữ lại tên thiết bị ở phần đầu ("điều hòa 24 độ à không 22" vẫn là hvac)
                segment = sorted({id(sp): sp for sp in kept + after}.values(),
                                 key=lambda sp: sp.start)
                lo, hi = segment[0].start, segment[-1].end

        # M11: nhắc tên thiết bị nhưng KHÔNG có động từ nào, mà câu lại còn nhiều chữ
        # lạ -> đây là đang nói VỀ thiết bị, không phải ra lệnh cho nó.
        #   "quạt"                     -> lệnh (default_action)
        #   "cái quạt ở nhà hỏng rồi"  -> KHÔNG phải lệnh
        #   "bạn có hiểu tiếng Việt không" -> "tiếng" là alias của volume, không phải lệnh
        # Một chữ lạ vẫn cho qua: "massage kiểu làn sóng", "quạt số 3".
        strays = sum(1 for sp in segment if sp.kind == WORD
                     # KHÔNG gộp URGING vào đây: "nhà" bỏ dấu thành "nha", trùng
                     # trợ từ "nha" → "cái quạt ở nhà hỏng rồi" hết bị chặn và bật quạt.
                     and bare(tokens[sp.start]) not in FUNCTION_WORDS
                     and sp.start not in phu_dinh_tai)
        # Ghi chú phải nói ĐÚNG chuyện đã xảy ra: M11 chạy TRƯỚC khi chốt thiết bị
        # và không hề kiểm tra có nhắc thiết bị hay không, nên "nóng quá" (không
        # một alias nào) cũng từng bị dán nhãn "nhắc tên thiết bị". Vết sai đường
        # thì người đọc vết đi sửa nhầm chỗ — cả buổi hôm nay em đọc vết này để
        # quyết định làm gì.
        if not any(sp.targets(ACTION) for sp in segment) and strays >= 2:
            co_ten = any(sp.targets(DEVICE) or sp.targets(ITEM) or sp.targets(MODE)
                         for sp in segment)
            return None, (
                "nhắc tên thiết bị nhưng không có động từ, nhiều chữ lạ — không coi là lệnh"
                if co_ten else
                "không động từ, không tên thiết bị, nhiều chữ lạ — không coi là lệnh")
        device, note = self._pick_device(tokens, segment, previous)
        if device is None:
            found = self.rescan(tokens, lo, hi, DEVICE)
            if found is not None:
                device, note = found.target, f"thiết bị tìm lại trong cụm đã khớp: {found.target}"
        if device is None:
            return None, "không xác định được thiết bị"
        dev = self.caps.devices[device]
        allowed = self.caps.effective_actions(dev)
        spec = self.caps.catalog.spec(dev.type)

        words = {bare(tokens[i]) for s in segment for i in range(s.start, s.end)}
        has_target_prep = bool(words & TARGET_PREPS)
        has_delta = bool(words & DELTA_MARKERS)

        # Mode bị exclude VẪN được nhận ra ở đây rồi để tầng resolve từ chối bằng
        # VA_MODE_EXCLUDED. Lọc im lặng ở đây sẽ biến "tắt hiệu ứng đèn viền" thành
        # lệnh bật đèn viền — sai và khó lần ra.
        mode = next(
            (e.target for s in segment for e in s.targets(MODE) if e.target in dev.modes),
            None,
        )
        # Vùng CỤ THỂ thắng vùng mơ hồ khi câu có cả hai. "ghế hành khách sau bên
        # trái" nêu rõ chỗ ngồi, nhưng "khách" đứng trước nên trước đây nó chiếm
        # chỗ, ra __mo_ho__ rồi cả lượt bị hỏi lại vô cớ. Mơ hồ chỉ dùng khi
        # KHÔNG còn gì rõ hơn.
        vung = [e.target for s in segment for e in s.targets(ZONE) if e.device == device]
        zone = next((z for z in vung if z != AMBIGUOUS_ZONE), None)
        if zone is None:
            zone = vung[0] if vung else None
        item = next((e.target for s in segment for e in s.targets(ITEM) if e.device == device), None)
        if item is None and dev.has_items:
            found = self.rescan(tokens, lo, hi, ITEM, keep=lambda e: e.device == device)
            item = found.target if found is not None else None
        unit = next(
            (e.target for s in segment for e in s.targets(UNIT)
             if dev.value is not None and e.target in dev.value.units),
            None,
        )
        number = next((s.value for s in segment if s.kind == NUMBER), None)
        it_mo_ho = False
        if number is not None:
            so_span = next(sp for sp in segment if sp.kind == NUMBER)
            if so_span.end < len(tokens) and bare(tokens[so_span.end]) in MO_HO_IT:
                number, it_mo_ho = None, True

        # Cực trị: giá trị nói bằng lời. Chỉ dùng khi KHÔNG có số và KHÔNG khớp
        # mode — "điều hòa tối đa" là mode max của hvac, phải nhường; "âm lượng
        # tối đa" thì volume không có mode đó nên mới quy ra biên.
        if number is None and mode is None and dev.value is not None:
            huong = next((e.target for sp in segment for e in sp.targets(CUC_TRI)), None)
            if huong is not None:
                spec = dev.value.unit(unit) if unit else dev.value.unit()
                if spec is not None:
                    number = spec.hi if huong == "max" else spec.lo

        # "23 độ rưỡi": chữ "rưỡi" đứng SAU đơn vị nên bộ đọc số không gộp được.
        # So trên dạng bỏ dấu để câu ASR không dấu ("do ruoi") cũng ăn.
        if number is not None and "ruoi" in words and float(number).is_integer():
            number += 0.5

        # "một nửa" -> 50% cho thiết bị đo bằng phần trăm
        if number is not None and 0 < number < 1:
            uname = unit or (dev.value.default_unit if dev.value else None)
            number = number * 100 if uname == "percent" else number

        verbs = [e.target for s in segment for e in s.targets(ACTION)]
        if not verbs and carried:
            # M14: động từ áp cho cả hai vế. "tắt đèn viền với cả đèn trần" — vế sau
            # không có động từ, dùng default_action là BẬT thì ngược hẳn ý người nói.
            verbs = list(carried)
        candidates = [v for v in verbs if v in allowed]
        relative = [v for v in candidates if v in ("increase", "decrease")]

        # M6: "…không / …chưa" ở cuối câu là hỏi trạng thái, thắng cả động từ đứng trước
        # ("điều hoà đang bật không" là câu hỏi, không phải lệnh bật).
        # Từ hỏi chỉ tính khi là CHỮ LẺ, không nằm trong alias nào: "máy" trong
        # "máy lạnh" bỏ dấu thành "may", trùng với "mấy" — cùng họ bẫy đỏ/độ.
        strays_bare = {bare(tokens[sp.start]) for sp in segment if sp.kind == WORD}
        last_is_stray = bool(spans_last_word := [sp for sp in segment
                                                 if sp.kind == WORD and sp.end == len(tokens)])
        trailing = last_is_stray and bare(tokens[-1]) in QUERY_TAILS
        if trailing and len(tokens) >= 2 and bare(tokens[-2]) in URGING:
            trailing = False
        # "bơm âm báo thêm 2 nấc xem sao": "sao" ở đây là chữ GIỤC, không phải chữ
        # hỏi. Câu đã có động từ rõ VÀ có số thì là lệnh. Không đụng tới `trailing`
        # (M6: "…không"/"…chưa" cuối câu vẫn thắng động từ đứng trước).
        ro_rang = number is not None and any(v != "query" for v in candidates)
        trailing_question = trailing or (bool(strays_bare & QUERY_WORDS) and not ro_rang)

        # LÊN/XUỐNG nói về TẤM KÍNH, không nói về con số độ mở — ngược mọi thiết
        # bị khác. "Kéo kính lên" là ĐÓNG (QC 9 câu), nhưng cụm alias "kéo lên"
        # không khớp được vì chữ "kính" chen vào giữa, còn lại mỗi "lên" →
        # increase, và xe hạ kính xuống thêm. Chỉ đảo khi KHÔNG có số: "chỉnh
        # cửa kính xuống còn 50%" thì con số mới là ý chính (QC 34 câu set_level).
        # Cửa kính: phần trăm là ĐỘ MỞ, nên kính trượt lên là GIẢM độ mở, trượt
        # xuống là TĂNG. Quy mọi chữ chỉ hướng về một trục rồi mới chọn hành
        # động, thay vì xét từng chữ — trước đây "kéo lên 1 chút" đóng hẳn cửa
        # kính còn "hạ xuống 1 tí" lại giảm độ mở, hai câu ngược nghĩa ra hai
        # kiểu sai khác nhau.
        #
        # Có lượng (dù mơ hồ như "1 chút") thì ra BƯỚC; không có lượng nào mới
        # đóng/mở hẳn. "Mở cốp sau lên" không dính vì "mở" không phải chữ hướng.
        if number is None and device in LEN_LA_DONG and {"close", "open"} <= set(allowed):
            chu = {e.surface for sp in segment for e in sp.targets(ACTION)}
            dong_bot = chu & {"lên", "kéo lên", "nâng"}
            mo_them = chu & {"xuống", "kéo xuống", "hạ", "hạ xuống"}
            if dong_bot and not mo_them:
                candidates = ["decrease"] if (it_mo_ho or has_delta) else ["close"]
            elif mo_them and not dong_bot:
                candidates = ["increase"] if (it_mo_ho or has_delta) else ["open"]

        action: Optional[str] = None
        if ("query" in candidates or trailing_question) and "query" in allowed:
            action = "query"
        elif mode is not None:
            # Ý định TẮT bắt từ động từ CHƯA lọc: "tắt chế độ thú cưng" khớp trọn cụm
            # "tắt chế độ" thành clear_mode, mà scene_mode lại không có clear_mode.
            off_intent = any(v in ("turn_off", "clear_mode") for v in verbs)
            if off_intent and spec.mode_as_action:
                action = "turn_off"                              # D3
            elif spec.mode_as_action and mode in allowed:
                action = mode
            elif "set_mode" in allowed:
                action = "set_mode"
        # D4: không có action mute. "Tắt tiếng" là đặt mức 0 — hợp lệ vì volume.lo=0.
        if action is None and "mute" in verbs and "set_level" in allowed and number is None:
            unit_spec = dev.value.unit(unit) if dev.value else None
            if unit_spec is not None and unit_spec.lo == 0:
                action, number = "set_level", 0

        if action is None and UNMUTE in verbs and "set_level" in allowed and number is None:
            unit_spec = dev.value.unit(unit) if dev.value else None
            if unit_spec is not None and unit_spec.lo == 0:
                action = UNMUTE

        if action is None and number is not None and "set_level" in allowed:
            # ĐÃ THỬ, HOÀ: cho giới từ đích đứng NGAY TRƯỚC số thắng chữ delta
            # ("bớt âm lượng về mức 5" là đặt 5, không phải giảm 5) — đúng luật mà
            # tools/qc_to_golden.py dùng để sửa 537 nhãn QC. Trên 24.851 câu:
            # value +1,5 nhưng step -2,9, còn "đúng cả câu" đứng nguyên 52,2% ở cả
            # hai. Chỉ đổi trường này lấy trường kia, không được gì. Đừng làm lại.
            # Có động từ tương đối mà con số KHÔNG THỂ là mức muốn tới thì nó là
            # BƯỚC. "tăng điều hòa lên 2 độ" — điều hòa chạy 16–32 — là tăng 2 độ,
            # không phải đặt 2 độ. Trước đây "lên" thắng và xe bị đặt xuống 2°C.
            #
            # QC không phân xử được chuyện này: cả 48 câu cùng dạng đều là
            # seat_massage nói phần trăm cho thiết bị đo bằng mức 1–3, và QC tự
            # gán 30 câu value / 18 câu step. hvac không có câu nào. Nên đây là
            # quyết định kỹ thuật: đặt điều hòa xuống 2°C vì người ta bảo TĂNG là
            # sai dù bộ test có nói gì.
            #
            # Chỉ chặn khi thật sự bất khả: 0 vẫn là mức hợp lệ ở thiết bị khai
            # zero_is_off ("về mức 0" = tắt), đừng biến nó thành bước 0.
            ngoai_dai = False
            if relative:
                spec_so = dev.value.unit(unit) if (dev.value and unit) else (
                    dev.value.unit() if dev.value else None)
                # CHỈ số dương. Số âm luôn nằm ngoài dải nên luật này sẽ nổ trên
                # toàn bộ lớp đó — lớp vừa mở ra khi normalize() thôi nuốt dấu
                # trừ (4c1c2d2). Đo A/B: để nguyên thì phá 204 câu, sửa 73; QC
                # gán "cài volume xuống level -10" là value=-10, nghiêng 3:1 về
                # mức chứ không phải bước. Bỏ số âm ra thì chỉ còn đúng ca cần.
                if (spec_so is not None and number > 0
                        and not (spec_so.lo <= number <= spec_so.hi)):
                    ngoai_dai = True
            action = (relative[0] if (relative and (ngoai_dai or has_delta
                                                    or not has_target_prep))
                      else "set_level")
        if action is None and candidates:
            action = next((c for c in candidates if c != "query"), candidates[0])
        # Thiết bị mở/đóng chứ không bật/tắt (màn hình, app): "tắt màn hình gương"
        # là ĐÓNG màn hình đó. Không có bước này thì turn_off bị loại khỏi
        # candidates rồi rơi xuống default_action = open — tức là làm NGƯỢC.
        if action is None:
            for v, thay in (("turn_off", "close"), ("turn_on", "open")):
                if v in verbs and thay in allowed:
                    action = thay
                    break
        if action is None and relative:
            action = relative[0]

        # Ý định TẮT mà thiết bị không có đúng động từ đó: "tắt chế độ sấy kính"
        # khớp trọn cụm "tắt chế độ" thành clear_mode, mà sấy kính không có
        # clear_mode nên bị loại sạch. Nhánh cứu off_intent ở trên CHỈ chạy cho
        # thiết bị mode_as_action. Cứu nốt ở đây, cho mọi thiết bị có turn_off.
        if action is None and "turn_off" in allowed \
                and any(v in ("turn_off", "clear_mode") for v in verbs):
            action = "turn_off"

        if action is None:
            # default_action CHỈ dành cho câu KHÔNG nói động từ nào ("quạt",
            # "điều hòa 22 độ"). Nghe thấy động từ mà không dùng được thì đó là
            # KHÔNG HIỂU — im lặng để tầng sau lo, chứ không được mặc định sang
            # chiều bật/mở.
            #
            # Trước đây rơi thẳng xuống default_action: "Close cổng sạc" ra MỞ
            # nắp sạc, "Chuyển khỏi ứng dụng nhạc" ra MỞ ứng dụng — xe làm NGƯỢC
            # lời người lái. Khoảng 300 câu trong bộ QC rơi vào lớp này. Không
            # hiểu thì người ta nói lại; làm ngược thì không.
            # `allowed` rỗng = thiết bị XE KHÔNG CÓ (đèn pha tự động, áp suất
            # lốp). Vẫn phải dựng lệnh để tầng resolve từ chối bằng đúng lý do
            # "xe mình không có X", thay vì hỏi lại "muốn bật cái gì".
            if verbs and allowed:
                return None, (f"nghe được '{verbs[0]}' nhưng {device} không làm được"
                              " — không đoán sang mặc định")
            action = dev.default_action

        value = number
        if action in ("turn_on", "turn_off", "open", "close") and value is not None \
                and not dev.has_number:
            value = None

        if negated:
            # Theo QC: phủ định ĐẢO CHIỀU lệnh. Hành động không có chiều ngược
            # (set_mode, set_level, query…) thì bỏ lệnh — đảo bừa còn tệ hơn.
            #
            # Câu không có động từ ("không cần sấy kính đâu") thì action còn None
            # ở đây — default_action mãi tới resolve mới điền. Lấy trước để có cái
            # mà đảo, nếu không thì mất luôn lệnh (QC defrost E273 mong turn_off).
            goc = action or (self.caps.devices[device].default_action
                             if device in self.caps.devices else None)
            nguoc = NGUOC_CHIEU.get(goc or "")
            if nguoc is None:
                return None, f"phủ định nhưng '{action}' không có chiều ngược — bỏ lệnh"
            note = (note + " · " if note else "") + f"phủ định: {goc} -> {nguoc}"
            action = nguoc

        raw = RawCommand(device=device, action=action, zone=zone, value=value,
                         unit=unit, mode=mode, item=item)
        return raw, note


def build_matcher(caps: Caps, lex: Lexicon) -> Matcher:
    return Matcher(caps, lex)
