"""Sinh dữ liệu huấn luyện cho model edge, nhãn có bằng CẤU TRÚC.

Cách làm ngược với gán nhãn thường: biết frame trước rồi mới dựng câu, nên nhãn
đúng theo định nghĩa, không cần người soát.

Hai lớp:
  sạch  — dựng từ alias trong lexicon theo mẫu câu. Grammar đọc được hết, nên
          phần này KHÔNG dạy model điều gì mới. Nó chỉ để model biết dạng chuẩn.
  nhiễu — thêm từ đệm, đổi trật tự, bỏ dấu, thêm chuyện ngoài lề. Grammar trượt
          nhiều mẫu ở đây, MÀ NHÃN VẪN ĐÚNG vì sinh ra từ cùng một frame. Đây mới
          là phần model học được cái grammar không làm nổi.

Mọi mẫu sạch đều phải qua kiểm khứ hồi: cho grammar đọc lại, ra đúng frame ban
đầu mới giữ. Câu nào grammar không đọc được thì chính mình vừa bịa ra tiếng Việt
sai — bỏ.
"""
from __future__ import annotations

import json
import random
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentcar.caps import Caps, load_caps
from agentcar.lexicon import ACTION, DEVICE, ITEM, MODE, UNIT, ZONE, load_lexicon
from agentcar.plan import RawCommand

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Sample:
    text: str
    device: str
    action: str
    zone: Optional[str] = None
    mode: Optional[str] = None
    item: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    lop: str = "sach"          # sạch | nhiễu
    nguon: str = "caps"


# Từ đệm người Việt hay chèn khi nói trong xe. Grammar bỏ qua được một phần,
# nhưng chồng nhiều lớp thì nó bắt đầu trượt.
MO_DAU = ["", "", "em ơi ", "anh ơi ", "cho anh ", "cho mình ", "này ", "ờ thì ",
          "à ", "giúp anh ", "làm ơn "]
KET = ["", "", " nhé", " nha", " đi", " với", " cái", " giùm anh", " hộ cái",
       " được không", " tí"]
CHEN = ["", "", "", " ờ ", " à ", " ừm ", " kiểu ", " tự dưng "]


def bo_dau(text: str) -> str:
    """ASR trong xe hay trả về câu không dấu — match.py coi đây là ca bắt buộc."""
    nfd = unicodedata.normalize("NFD", text)
    out = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return out.replace("đ", "d").replace("Đ", "D")


class Generator:
    def __init__(self, caps: Caps, seed: int = 0):
        self.caps = caps
        self.lex = load_lexicon(caps)
        self.rnd = random.Random(seed)

    def _alias(self, kind: str, target: str, device: Optional[str] = None) -> list[str]:
        return self.lex.aliases_of(kind, target, device=device) or []

    def _dong_tu(self, action: str) -> list[str]:
        return self._alias(ACTION, action)

    # ------------------------------------------------------------------ frame
    def frames(self) -> Iterator[RawCommand]:
        """Mọi frame hợp lệ caps cho phép. Đây là toàn bộ không gian đích."""
        for name, dev in self.caps.devices.items():
            acts = self.caps.effective_actions(dev)
            if not acts:
                continue
            zones = list(dev.zones) or [None]
            for action in acts:
                if action == "query":
                    continue                     # câu hỏi để riêng, dạng câu khác hẳn
                if action == "set_mode":
                    for mode in dev.modes:
                        if mode in dev.exclude:
                            continue
                        yield RawCommand(device=name, action=action,
                                         zone=self.rnd.choice(zones), mode=mode)
                elif action == "set_level" and dev.value and dev.value.is_number:
                    unit = dev.value.unit()
                    if unit is None:
                        continue
                    step = unit.resolution or 1
                    muc = [unit.lo, unit.hi, (unit.lo + unit.hi) / 2]
                    for v in muc:
                        v = round(round(v / step) * step, 3)
                        yield RawCommand(device=name, action=action,
                                         zone=self.rnd.choice(zones),
                                         value=v, unit=unit.name)
                elif action in ("open", "close") and dev.has_items:
                    for item in dev.items:
                        yield RawCommand(device=name, action=action, item=item)
                else:
                    for zone in zones:
                        yield RawCommand(device=name, action=action, zone=zone)

    # ------------------------------------------------------------------- câu
    def cau_sach(self, raw: RawCommand) -> list[str]:
        """Dạng chuẩn: động từ + thiết bị + vùng + lượng."""
        dev = self.caps.devices[raw.device]
        names = self._alias(DEVICE, raw.device)
        # Thiết bị kiểu mode_as_action (scene_mode): tên action CHÍNH LÀ tên mode,
        # nên phải tra alias MODE chứ không phải ACTION. "bật chế độ cắm trại".
        if self.caps.catalog.spec(dev.type).mode_as_action and raw.action in dev.modes:
            mode_names = self._alias(MODE, raw.action)
            bat = self._dong_tu("turn_on")
            if not mode_names or not bat or not names:
                return []
            return [f"{v} {n} {m}" for v in bat[:2] for n in names[:2] for m in mode_names[:2]]
        verbs = self._dong_tu(raw.action) or []
        if not verbs or not names:
            return []
        out = []
        for verb in verbs[:3]:
            for name in names[:3]:
                phan = [verb, name]
                if raw.zone and raw.zone != dev.default_zone:
                    z = self._alias(ZONE, raw.zone, device=raw.device)
                    if not z:
                        continue
                    phan.append(z[0])
                if raw.mode:
                    m = self._alias(MODE, raw.mode)
                    if not m:
                        continue
                    phan.append(m[0])
                if raw.item:
                    it = self._alias(ITEM, raw.item)
                    if not it:
                        continue
                    phan = [verb, it[0]]
                if raw.value is not None:
                    u = self._alias(UNIT, raw.unit)
                    so = f"{raw.value:g}"
                    phan.append(f"{u[0]} {so}" if u and u[0] == "mức" else f"{so} {u[0] if u else ''}")
                out.append(" ".join(p for p in phan if p).strip())
        return out

    def them_nhieu(self, cau: str) -> str:
        t = self.rnd.choice(MO_DAU) + cau + self.rnd.choice(KET)
        chen = self.rnd.choice(CHEN)
        if chen and " " in t:
            vi_tri = self.rnd.randrange(1, len(t.split()))
            tu = t.split()
            t = " ".join(tu[:vi_tri]) + chen + " ".join(tu[vi_tri:])
        return " ".join(t.split())

    # ------------------------------------------------------- kiểm khứ hồi
    def _khop(self, cau: str, raw: RawCommand) -> bool:
        """Grammar đọc lại câu vừa dựng có ra đúng frame ban đầu không.

        Đây là hàng rào chống chính mình: câu nào grammar không đọc được thì khả
        năng cao là mình vừa ghép ra tiếng Việt không ai nói.
        """
        from agentcar.match import Matcher
        from agentcar.reasoning import load_rules
        if not hasattr(self, "_m"):
            self._m = Matcher(self.caps, self.lex, vague=load_rules().vague)
        got = self._m.match(cau, previous_device=None).commands
        if len(got) != 1:
            return False
        g = got[0]
        if g.device != raw.device or g.action != raw.action:
            return False
        if raw.mode and g.mode != raw.mode:
            return False
        if raw.item and g.item != raw.item:
            return False
        if raw.value is not None and g.value != raw.value:
            return False
        return True

    def grammar_doc_duoc(self, cau: str, raw: RawCommand) -> bool:
        return self._khop(cau, raw)

    # ------------------------------------------------------------------ dựng
    def build(self, nhieu_moi_cau: int = 3, bo_dau_ty_le: float = 0.3) -> list[Sample]:
        mau: list[Sample] = []
        for raw in self.frames():
            for cau in self.cau_sach(raw):
                if not self._khop(cau, raw):
                    continue                      # mình vừa bịa sai, bỏ
                mau.append(Sample(text=cau, device=raw.device, action=raw.action,
                                  zone=raw.zone, mode=raw.mode, item=raw.item,
                                  value=raw.value, unit=raw.unit, lop="sach"))
                for _ in range(nhieu_moi_cau):
                    t = self.them_nhieu(cau)
                    if self.rnd.random() < bo_dau_ty_le:
                        t = bo_dau(t)
                    mau.append(Sample(text=t, device=raw.device, action=raw.action,
                                      zone=raw.zone, mode=raw.mode, item=raw.item,
                                      value=raw.value, unit=raw.unit, lop="nhieu"))
        return mau


def mau_am(massive: Path, so_luong: int, seed: int = 0) -> list[Sample]:
    """Câu KHÔNG phải lệnh xe — lấy từ MASSIVE, bỏ miền iot.

    Đây là mảnh thiếu lớn nhất của bản train đầu: 12.396 mẫu mà KHÔNG mẫu nào là
    câu ngoài miền. Model chưa bao giờ được phép nói "cái này không thuộc về tôi",
    nên mọi câu đưa vào nó buộc phải chọn một trong 25 thiết bị — và vẫn tự tin.
    Đó là lý do tin-khi-sai lên tới 0,64.

    Bỏ miền iot vì "tắt các bóng đèn" có thể là lệnh xe thật; xếp nó vào nhóm âm
    là dạy model sai.

    KHÔNG dùng golden_negative.vi.yaml làm dữ liệu train — đó là bộ chấm, train
    trên nó thì con số sau này vô nghĩa.
    """
    import random as _r
    rows = [json.loads(l) for l in massive.open(encoding="utf-8")]
    ngoai = [r["utt"] for r in rows if r.get("scenario") != "iot" and r.get("utt")]
    rnd = _r.Random(seed)
    rnd.shuffle(ngoai)
    out = []
    for cau in ngoai[:so_luong]:
        t = bo_dau(cau) if rnd.random() < 0.3 else cau
        out.append(Sample(text=t, device=None, action=None, lop="ngoai_mien",
                          nguon="massive"))
    return out


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "nlu" / "data" / "synth.jsonl"
    caps = load_caps(ROOT / "caps" / "vf9.yaml")
    gen = Generator(caps)
    mau = gen.build()

    # Mẫu âm: khoảng 1/4 tổng số. Nhiều quá thì model đâm ra hay từ chối; không
    # có thì nó không bao giờ học được cách nói không.
    am = []
    massive = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if massive and massive.exists():
        am = mau_am(massive, so_luong=len(mau) // 3)
        mau += am

    # Bao nhiêu mẫu nhiễu mà grammar TRƯỢT — đó chính là phần model có thể thêm.
    truot = sum(1 for s in mau if s.lop == "nhieu"
                and not gen.grammar_doc_duoc(s.text, RawCommand(
                    device=s.device, action=s.action, zone=s.zone,
                    mode=s.mode, item=s.item, value=s.value, unit=s.unit)))
    nhieu = sum(1 for s in mau if s.lop == "nhieu")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for s in mau:
            fh.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")

    frames = len({(s.device, s.action, s.zone, s.mode, s.item, s.value)
                  for s in mau if s.device})
    print(f"{len(mau)} mẫu  ({len(mau)-nhieu-len(am)} sạch, {nhieu} nhiễu, "
          f"{len(am)} ngoài miền)  phủ {frames} frame")
    print(f"trong phần nhiễu, grammar trượt {truot} ({truot/nhieu:.1%}) — đây là phần model học thêm được")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
