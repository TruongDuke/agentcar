"""Tầng [1b] — model NLU chạy trên xe, đứng giữa tầng luật và tầng cloud.

Vì sao cần: tầng luật (match.py) chỉ trả lời câu nó khớp được từ điển, câu nào
không khớp thì trả ESCALATE_UNKNOWN. Trên bộ 24k câu thật của QC, khoảng một nửa
rơi vào đó — và phần lớn là câu nói tự nhiên, tiếng lóng, trộn Anh-Việt. Đối
chiếu với hệ S6 cho thấy chính họ giao ~52% traffic cho tầng NLU. Không có tầng
này thì repo đang đo có nửa hệ thống.

Model: `joint-nlu-trained/` — BERT 4 tầng hidden 312, hai đầu gán nhãn THEO TOKEN:
  cmd_head  293 nhãn BIO dạng `B-hvac.turn_on`  -> mỗi đoạn là một lệnh
  slot_head  51 nhãn BIO dạng `B-zone`, `B-value` -> tham số của lệnh
KHÔNG có đầu intent riêng: intent nằm luôn trong nhãn cmd.

Trọng số bị .gitignore (*.pt) nên máy khác có thể không có. Thiếu file thì module
tự tắt, agent chạy y như trước — KHÔNG được sập.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "joint-nlu-trained"

# Model đặt tên action theo quy ước của nó; caps đặt tên khác. Chỉ map khi CHẮC
# CHẮN cùng nghĩa — không map thì bỏ lệnh, đoán bừa tệ hơn.
#
# `set` là một cái tên cho HAI việc: đặt MỨC ("đèn viền mức 80") và đặt CHẾ ĐỘ
# ("đèn viền màu xanh dương"). Model không phân biệt, phải nhìn SLOT mới biết —
# xử lý trong sang_raw chứ không map cứng ở đây.
ACTION_ALIAS = {"set": "set_level"}

# Tên miền model biết mà caps không có (dẫn đường, gọi điện, nhạc, hỏi đáp, đối
# thoại). Không dựng lệnh được, để tầng trên lo.
NGOAI_CAPS_DEFAULT = frozenset({
    "nav", "call", "message", "media", "info", "vehicle_status",
    "dialog", "assist", "chitchat", "oos", "reject",
})


@dataclass
class NluCommand:
    """Một lệnh model đọc ra, còn ở dạng thô — chưa đối chiếu caps."""

    device: str
    action: str
    slots: dict[str, str] = field(default_factory=dict)
    score: float = 0.0


# Model 57MB: nạp mỗi lần dựng Agent là hỏng — bộ chấm tạo một Agent cho MỖI CÂU.
# Chia sẻ theo đường dẫn, nạp đúng một lần cho cả tiến trình.
_DUNG_CHUNG: dict[str, "JointNlu"] = {}


def dung_chung(path: Path | str = DEFAULT_DIR) -> "JointNlu":
    key = str(Path(path).resolve())
    if key not in _DUNG_CHUNG:
        _DUNG_CHUNG[key] = JointNlu(path)
    return _DUNG_CHUNG[key]


def co_model(path: Path | str = DEFAULT_DIR) -> bool:
    """Có đủ file để chạy không — trọng số bị gitignore nên máy khác có thể thiếu."""
    d = Path(path)
    return all((d / f).exists() for f in ("best_model.pt", "label_maps.json", "tokenizer.json"))


class JointNlu:
    """Nạp model một lần, suy luận tại chỗ. Không chạm mạng."""

    def __init__(self, path: Path | str = DEFAULT_DIR):
        self.path = Path(path)
        self._ready = False
        self._err: Optional[str] = None

    # ------------------------------------------------------------------ nạp
    def load(self) -> bool:
        if self._ready or self._err:
            return self._ready
        try:
            import torch
            from tokenizers import Tokenizer
            from transformers import BertConfig, BertModel
        except ImportError as exc:
            self._err = f"thiếu thư viện: {exc}"
            return False

        ckpt = self.path / "best_model.pt"
        maps = self.path / "label_maps.json"
        toks = self.path / "tokenizer.json"
        if not (ckpt.exists() and maps.exists() and toks.exists()):
            self._err = f"thiếu file trong {self.path}"
            return False

        try:
            state = torch.load(ckpt, map_location="cpu", weights_only=True)
            lm = json.loads(maps.read_text(encoding="utf-8"))
            # Kích thước lấy THẲNG từ trọng số, không khai cứng: đổi model là
            # đổi theo, không phải sửa code.
            vocab, hidden = state["encoder.embeddings.word_embeddings.weight"].shape
            inter = state["encoder.encoder.layer.0.intermediate.dense.weight"].shape[0]
            layers = 1 + max(int(k.split(".")[3]) for k in state
                             if k.startswith("encoder.encoder.layer."))
            cfg = BertConfig(vocab_size=vocab, hidden_size=hidden,
                             num_hidden_layers=layers, num_attention_heads=12,
                             intermediate_size=inter, max_position_embeddings=512)
            enc = BertModel(cfg)
            enc.load_state_dict({k[len("encoder."):]: v for k, v in state.items()
                                 if k.startswith("encoder.")}, strict=False)
            cmd = torch.nn.Linear(hidden, state["cmd_head.weight"].shape[0])
            cmd.load_state_dict({"weight": state["cmd_head.weight"], "bias": state["cmd_head.bias"]})
            slot = torch.nn.Linear(hidden, state["slot_head.weight"].shape[0])
            slot.load_state_dict({"weight": state["slot_head.weight"], "bias": state["slot_head.bias"]})
            for m in (enc, cmd, slot):
                m.eval()
        except Exception as exc:                      # nạp hỏng thì tắt, đừng sập
            self._err = f"nạp model hỏng: {exc}"
            return False

        self._torch = torch
        self._enc, self._cmd, self._slot = enc, cmd, slot
        self._tok = Tokenizer.from_file(str(toks))
        self._cmd_tag = _dao(lm["cmd_tags"])
        self._slot_tag = _dao(lm["slot_tags"])
        self._ready = True
        return True

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def error(self) -> Optional[str]:
        return self._err

    # ------------------------------------------------------------- suy luận
    def read(self, text: str, nguong: float = 0.0) -> list[NluCommand]:
        """Câu -> danh sách lệnh thô. Chưa đối chiếu caps, chưa dựng RawCommand."""
        if not self.load() or not (text or "").strip():
            return []
        torch = self._torch
        enc = self._tok.encode(text)
        ids = torch.tensor([enc.ids])
        with torch.no_grad():
            h = self._enc(ids, attention_mask=torch.ones_like(ids)).last_hidden_state
            cmd_p = torch.softmax(self._cmd(h)[0], dim=-1)
            slot_p = torch.softmax(self._slot(h)[0], dim=-1)
        cmd_s, cmd_i = cmd_p.max(-1)
        slot_i = slot_p.argmax(-1)

        # Bỏ [CLS]/[SEP]: chúng cũng được gán nhãn nhưng không mang chữ nào.
        keep = [i for i, t in enumerate(enc.tokens) if t not in ("[CLS]", "[SEP]")]
        # word_ids: mảnh con của CÙNG một chữ dùng chung id. Cần nó vì model phát
        # B- cả trên mảnh con ("spot" và "##ify" đều B-item) — cắt theo B- không
        # thôi thì "spotify" thành "spot".
        wid = enc.word_ids
        cmds = _gom([(self._cmd_tag.get(int(cmd_i[i]), "O"), float(cmd_s[i]), i, wid[i])
                     for i in keep])
        slots = _gom_slot([(self._slot_tag.get(int(slot_i[i]), "O"), i, wid[i])
                           for i in keep], enc, text)

        out: list[NluCommand] = []
        for intent, score, lo, hi in cmds:
            if score < nguong:
                continue
            device, _, action = intent.partition(".")
            # Giữ NGUYÊN tên action của model; đổi tên ở sang_raw, nơi biết cả
            # slot lẫn caps. `set` là một tên cho hai việc (mức / chế độ).
            out.append(NluCommand(device=device, action=action,
                                  slots=_slots_trong(slots, lo, hi), score=score))
        return out


def _dao(m) -> dict[int, str]:
    """label_maps ghi {nhãn: id}; suy luận cần chiều ngược."""
    return {v: k for k, v in m.items()} if isinstance(m, dict) else dict(enumerate(m))


def _gom(tags: list[tuple[str, float, int, Optional[int]]]) -> list[tuple[str, float, int, int]]:
    """BIO -> các đoạn lệnh (intent, điểm, token đầu, token cuối).

    Nhãn model trả ra lẫn lộn trong cùng một đoạn ("window.set" xen "window.decrease"),
    nên KHÔNG cắt đoạn mỗi lần nhãn đổi — cắt ở B-, rồi trong đoạn lấy intent có
    tổng điểm cao nhất. Cắt theo từng token thì một câu ra bốn lệnh.

    Và KHÔNG cắt giữa một chữ: B- rơi vào mảnh con thì vẫn là chữ cũ.
    """
    spans: list[list] = []
    truoc: Optional[int] = None
    for tag, score, idx, word in tags:
        if tag == "O":
            truoc = word
            continue
        intent = tag[2:]
        cung_chu = word is not None and word == truoc
        if (tag.startswith("B-") and not cung_chu) or not spans:
            spans.append([{}, idx, idx])
        spans[-1][0][intent] = spans[-1][0].get(intent, 0.0) + score
        spans[-1][2] = idx
        truoc = word
    out = []
    for diem, lo, hi in spans:
        if not diem:
            continue
        intent = max(diem, key=diem.get)
        out.append((intent, diem[intent] / max(hi - lo + 1, 1), lo, hi))
    return out


def _gom_slot(tags: list[tuple[str, int]], enc, text: str) -> list[tuple[str, str, int, int]]:
    """BIO slot -> (tên slot, chữ, token đầu, token cuối)."""
    out: list[list] = []
    truoc: Optional[int] = None
    for tag, idx, word in tags:
        if tag == "O":
            truoc = word
            continue
        name = tag[2:]
        cung_chu = word is not None and word == truoc
        moi = (tag.startswith("B-") and not cung_chu) or not out or out[-1][0] != name
        if moi:
            out.append([name, [idx], idx])
        else:
            out[-1][1].append(idx)
            out[-1][2] = idx
        truoc = word
    res = []
    for name, idxs, hi in out:
        lo = idxs[0]
        # Model hay gán nhãn HẾT MỘT PHẦN của chữ: "kính xe" chỉ tag tới "kính x",
        # tra từ điển không ra rồi mất cả lệnh. Kéo hai đầu ra trọn chữ.
        lo, hi = _tron_chu(tags, lo, hi)
        chu = _chu(enc, text, lo, hi)
        if chu:
            res.append((name, chu, lo, hi))
    return res


def _tron_chu(tags, lo: int, hi: int) -> tuple[int, int]:
    """Nới [lo, hi] ra cho hết chữ ở hai đầu, theo word_ids."""
    wid = {idx: word for _, idx, word in tags}
    dau, cuoi = wid.get(lo), wid.get(hi)
    for _, idx, word in tags:
        if dau is not None and word == dau:
            lo = min(lo, idx)
        if cuoi is not None and word == cuoi:
            hi = max(hi, idx)
    return lo, hi


def _chu(enc, text: str, lo: int, hi: int) -> str:
    """Chữ GỐC của khoảng token, cắt từ câu ban đầu theo offset.

    Không ghép enc.tokens lại được: tokenizer bỏ dấu và cắt thành ##mảnh, ghép ra
    "ben lai" chứ không phải "bên lái" — mà tầng sau tra từ điển bằng chữ có dấu.
    """
    offs = [o for o in enc.offsets[lo:hi + 1] if o != (0, 0)]
    return text[offs[0][0]:offs[-1][1]] if offs else ""


def _slots_trong(slots, lo: int, hi: int) -> dict[str, str]:
    """Slot nằm trong khoảng của lệnh. Trùng tên thì lấy đoạn DÀI NHẤT.

    Không lấy đoạn đầu: model hay gán nhầm đuôi chữ liền trước ("##u" của "màu"
    thành B-mode), sinh ra một đoạn rác một ký tự đứng trước đoạn thật. Lấy đầu
    thì "màu xanh dương" ra mode="u".
    """
    dai: dict[str, int] = {}
    out: dict[str, str] = {}
    for name, chu, s_lo, s_hi in slots:
        if not (s_lo >= lo and s_hi <= hi):
            continue
        n = s_hi - s_lo + 1
        if n > dai.get(name, 0):
            dai[name], out[name] = n, chu
    return out


# ---------------------------------------------------------------- sang caps
def sang_raw(caps, lex, cmd: NluCommand):
    """NluCommand (chữ tiếng Việt) -> RawCommand (id của caps). None = không dựng được.

    Model nói "ghế sau bên trái", caps gọi vùng đó là `rear_left`. Tra bằng chính
    từ điển của tầng luật, KHÔNG dựng bảng riêng — hai bên phải luôn cùng một
    cách hiểu, nếu không thì sửa lexicon một chỗ mà chỗ kia vẫn sai.

    Trả None khi không chắc: thiết bị ngoài caps, action không hợp lệ, hoặc slot
    tra không ra. Thà để tầng trên lo còn hơn dựng một lệnh sai.
    """
    from .lexicon import ITEM, MODE, ZONE
    from .plan import RawCommand

    device = caps.devices.get(cmd.device)
    if device is None or not device.support or device.cloud_only:
        return None

    modes = [m for m in device.modes if m not in device.exclude]
    action = ACTION_ALIAS.get(cmd.action, cmd.action)
    # `set` kèm slot MODE mà không kèm số: đó là đặt CHẾ ĐỘ, không phải đặt mức.
    # Map cứng set->set_level thì "đèn viền màu xanh dương" thành lệnh đặt mức
    # thiếu giá trị, agent hỏi "mức bao nhiêu ạ?" trong khi người ta nói màu.
    if (cmd.action == "set" and cmd.slots.get("mode") and not cmd.slots.get("value")
            and "set_mode" in caps.effective_actions(device)):
        action = "set_mode"
    if action not in caps.effective_actions(device) and action not in modes:
        return None

    def tra(kind: str, text: str, hop_le) -> Optional[str]:
        hits = {e.target for e in lex.lookup(text, kind)
                if e.device in (None, device.name) and e.target in hop_le}
        return next(iter(hits)) if len(hits) == 1 else None

    zone = mode = item = None
    if cmd.slots.get("zone") and device.zones:
        zone = tra(ZONE, cmd.slots["zone"], set(device.zones))
        # Tra không ra thì BỎ VÙNG, vẫn dựng lệnh với vùng mặc định. Trước đây bỏ
        # cả lệnh: mất 280/1200 câu trong khi device+action model đọc đúng. Chữ
        # slot model trả về hay cụt ("kính x"), vứt cả lệnh vì thế là quá tay.
    if cmd.slots.get("mode"):
        mode = tra(MODE, cmd.slots["mode"], set(modes))
    if cmd.slots.get("item") and device.items:
        item = tra(ITEM, cmd.slots["item"], set(device.items))
        if item is None:
            return None

    # Giá trị: để nguyên chuỗi cho tầng số của matcher đọc ("22 độ", "50 phần
    # trăm", "mức 3") — nó đã biết đọc số viết chữ lẫn đơn vị, đừng làm lại.
    value = unit = None
    if cmd.slots.get("value"):
        value, unit = _doc_so(lex, cmd.slots["value"])
        if value is None:
            return None

    return RawCommand(device=device.name, action=action, zone=zone,
                      value=value, unit=unit, mode=mode, item=item)


def _doc_so(lex, text: str) -> tuple[Optional[float], Optional[str]]:
    """'22 độ' -> (22, 'celsius'), '50 phần trăm' -> (50, 'percent').

    Dùng lại `parse_number` của tầng luật (biết đọc cả số viết chữ) và từ điển
    đơn vị của chính lexicon — đừng viết bảng đơn vị thứ hai.
    """
    from .lexicon import UNIT, normalize
    from .match import parse_number

    toks = normalize(text, keep_diacritics=True).split()
    value = used = None
    for i in range(len(toks)):
        value, used = parse_number(toks, i)
        if value is not None:
            toks = toks[i:]
            break
    if value is None:
        return None, None

    for n in range(len(toks) - used, 0, -1):          # cụm dài trước: "độ f" ≠ "độ"
        hits = {e.target for e in lex.lookup(" ".join(toks[used:used + n]), UNIT)}
        if len(hits) == 1:
            return value, next(iter(hits))
    return value, None
