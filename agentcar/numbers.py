"""Đọc số tiếng Việt: 'hai mươi ba' -> 23, 'hai ba' -> 23, '22' -> 22."""
from __future__ import annotations

from typing import Optional

from .lexicon import normalize

# CỐ Ý không có "không"=0: trong câu lệnh xe nó gần như luôn là từ hỏi
# ("điều hoà đang bật không"), đọc thành số 0 sẽ biến câu hỏi thành lệnh đặt mức 0.
DIGITS = {
    "một": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4,
    "năm": 5, "lăm": 5, "nhăm": 5, "sáu": 6, "bảy": 7, "bẩy": 7,
    "tám": 8, "chín": 9, "mốt": 1,
}
TEN = "mười"
TENS_MARK = "mươi"
HUNDRED = "trăm"
HALF = "rưỡi"

# "hạ kính một nửa" -> 50%
FRACTIONS = {("một", "nửa"): 0.5, ("nửa",): 0.5}


# ASR hay trả câu không dấu ("hai muoi ba do"), nên so khớp trên dạng đã bỏ dấu.
# "mười" và "mươi" bỏ dấu đều thành "muoi" — không sao, VỊ TRÍ phân biệt được:
# "muoi lam" thì muoi đứng đầu (= 10), "hai muoi" thì muoi đứng sau chữ số (= chục).
_DIGITS_BARE = {normalize(k): v for k, v in DIGITS.items()}
_TEN_BARE = normalize(TEN)
_TENS_BARE = normalize(TENS_MARK)
_HUNDRED_BARE = normalize(HUNDRED)
_HALF_BARE = normalize(HALF)
_FRACTIONS_BARE = {tuple(normalize(w) for w in span): r for span, r in FRACTIONS.items()}


# Dạng KẾT HỢP: chỉ có nghĩa khi đứng ngay sau "mười"/"mươi" ("hai mươi lăm",
# "hai mươi tư"). Đứng một mình thì không phải số — và quan trọng hơn: "nhăm" bỏ
# dấu trùng với "nhầm", nên "điều hoà nhầm rồi" từng bị đọc thành đặt mức 5.
# KHÔNG có "mot": "một" (số 1, đứng một mình được) và "mốt" bỏ dấu cùng thành "mot".
COMBINING = {"lam", "nham", "tu"}


def _key(tok: str) -> str:
    return normalize(tok)


def _digit(tok: str) -> Optional[int]:
    if tok.isdigit():
        return int(tok)
    return _DIGITS_BARE.get(_key(tok))


def parse_number(tokens: list[str], i: int) -> tuple[Optional[float], int]:
    """Trả (giá trị, số token đã dùng) tại vị trí i. Không khớp thì (None, 0)."""
    value, used = _core(tokens, i)
    if value is not None and i + used < len(tokens) and _key(tokens[i + used]) == _HALF_BARE:
        return value + 0.5, used + 1          # "hai mươi ba độ rưỡi"
    return value, used


def _core(tokens: list[str], i: int) -> tuple[Optional[float], int]:
    for span, ratio in _FRACTIONS_BARE.items():
        if tuple(_key(t) for t in tokens[i : i + len(span)]) == span:
            return ratio, len(span)

    tok = tokens[i]
    # "-3": dấu do normalize giữ lại. Đọc phần số rồi đảo dấu.
    if len(tok) > 1 and tok[0] == "-":
        value, used = _core([tok[1:]] + list(tokens[i + 1:]), 0)
        return (None, 0) if value is None else (-value, used)
    if _key(tok) in COMBINING:
        return None, 0
    nxt = _key(tokens[i + 1]) if i + 1 < len(tokens) else ""
    nxt2 = _key(tokens[i + 2]) if i + 2 < len(tokens) else ""

    # số viết bằng chữ số: "22", "22.5"
    if tok.replace(".", "", 1).isdigit() and tok.count(".") <= 1:
        value = float(tok) if "." in tok else int(tok)
        if nxt == HALF:
            return value + 0.5, 2
        return value, 1

    # "mười", "mười lăm"
    if _key(tok) == _TEN_BARE:
        d = _digit(nxt)
        if d is not None:
            return 10 + d, 2
        return 10, 1

    # "một trăm"
    d1 = _digit(tok)
    if d1 is None:
        return None, 0
    if nxt == _HUNDRED_BARE:
        rest, used = _core(tokens, i + 2) if i + 2 < len(tokens) else (None, 0)
        if rest is not None and rest < 100:
            return d1 * 100 + rest, 2 + used
        return d1 * 100, 2

    # "hai mươi", "hai mươi ba", "hai mươi mốt"
    if nxt == _TENS_BARE:
        d2 = _digit(nxt2)
        if d2 is not None:
            return d1 * 10 + d2, 3
        return d1 * 10, 2

    # "hai ba" = 23 — cách đọc tắt rất phổ biến khi nói nhiệt độ
    d2 = _digit(nxt)
    if d2 is not None and 1 <= d1 <= 9 and nxt in _DIGITS_BARE \
            and nxt not in (_TEN_BARE, _TENS_BARE):
        return d1 * 10 + d2, 2

    if nxt == _HALF_BARE:
        return d1 + 0.5, 2
    return d1, 1
