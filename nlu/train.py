"""Train model NLU cho edge — ba giai đoạn.

  1. massive    PhoBERT học văn phong RA LỆNH tiếng Việt trên MASSIVE vi-VN.
                Nhãn của MASSIVE (60 intent) không phải nhãn của mình; dùng xong
                vứt đầu, chỉ giữ THÂN. Thân là thứ mang hiểu biết ngôn ngữ.
  2. mien       Nạp thân đó, gắn đầu 6 trường của mình, train trên dữ liệu sinh
                từ caps. Đây là lúc model học VF9 có 30 thiết bị nào.
  3. chung-cat  Trò 4 lớp/312 học theo đầu ra của thầy ở bước 2. Đây mới là thứ
                đóng gói lên xe. Thầy 135M ở lại máy train.

Chia việc có chủ ý: MODEL lo ngữ nghĩa, agentcar.numbers lo con số. Model bé luôn
yếu ở số, mà bộ đọc số thì đúng tuyệt đối — đừng bắt model học lại.

Mỗi câu ra MỘT frame (v0). Câu nhiều lệnh để tầng sau lo.
"""
from __future__ import annotations

import argparse, json, random, re, sys, time
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from transformers import AutoConfig, AutoModel, AutoTokenizer, BertConfig, BertModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TRUONG = ["device", "action", "zone", "mode", "item", "unit"]
NEN = "vinai/phobert-base"
MAX_LEN = 48


def thiet_bi() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ------------------------------------------------------------------ nhãn
class Bang:
    """Nhãn ↔ số, sinh từ chính dữ liệu nên thêm thiết bị vào caps là tự có."""

    def __init__(self, nguoc: dict[str, list[str]]):
        self.nguoc = nguoc
        self.map = {t: {v: i for i, v in enumerate(vs)} for t, vs in nguoc.items()}

    @classmethod
    def tu_mau(cls, mau: list[dict], truong: list[str]) -> "Bang":
        return cls({t: sorted({str(m.get(t)) for m in mau}) for t in truong})

    @classmethod
    def doc(cls, p: Path) -> "Bang":
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def luu(self, p: Path) -> None:
        p.write_text(json.dumps(self.nguoc, ensure_ascii=False, indent=1), encoding="utf-8")

    def so(self, t: str, v) -> int:
        return self.map[t][str(v)]

    def co(self, t: str, v) -> bool:
        return str(v) in self.map[t]

    def cd(self, t: str) -> int:
        return len(self.nguoc[t])


# ------------------------------------------------------------------ dữ liệu
class BoMau(Dataset):
    def __init__(self, mau, tok, bang, truong):
        self.mau, self.tok, self.bang, self.truong = mau, tok, bang, truong

    def __len__(self):
        return len(self.mau)

    def __getitem__(self, i):
        m = self.mau[i]
        enc = self.tok(m["text"], truncation=True, max_length=MAX_LEN,
                       padding="max_length", return_tensors="pt")
        item = {k: v.squeeze(0) for k, v in enc.items()}
        for t in self.truong:
            item[t] = torch.tensor(self.bang.so(t, m.get(t)))
        return item


def doc_massive(p: Path) -> list[dict]:
    rows = [json.loads(l) for l in p.open(encoding="utf-8")]
    return [{"text": r["utt"], "intent": r["intent"]} for r in rows if r.get("utt")]


def doc_mien(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8")]


def doc_golden() -> tuple[list[dict], list[dict]]:
    """Bộ chấm THẬT, tách hai nhóm.

    DUONG  — câu phải ra frame. Gồm cả ca DENY/CONFIRM: safety chặn là việc của
             tầng sau, model vẫn phải hiểu đúng câu.
    IM     — câu model nên nói "không phải lệnh xe": ESCALATE_UNKNOWN trong golden
             + toàn bộ golden_negative.

    Bản chấm cũ vứt cả 98 ca không-OK, nên không đo được model có biết im lặng
    không — mà với bảng định tuyến thì đó là thứ quan trọng nhất. Cũng bỏ luôn 50
    ca `verdict: None`: chúng test định tuyến (checkpoint/path), không test frame.
    """
    import yaml
    duong, im = [], []
    for f in ("golden.vi.yaml", "golden_hard.vi.yaml"):
        fp = ROOT / "tests" / f
        if not fp.exists():
            continue
        for c in yaml.safe_load(fp.read_text(encoding="utf-8")):
            e = (c or {}).get("expect") or {}
            v = e.get("verdict")
            if e.get("device") and v in ("OK", "DENY", "CONFIRM"):
                duong.append({"text": c["say"], **{t: e.get(t) for t in TRUONG}})
            elif v == "ESCALATE_UNKNOWN":
                im.append({"text": c["say"]})
    fp = ROOT / "tests" / "golden_negative.vi.yaml"
    if fp.exists():
        for c in yaml.safe_load(fp.read_text(encoding="utf-8")):
            im.append({"text": c if isinstance(c, str) else c["say"]})
    return duong, im


# ------------------------------------------------------------------ model
class NhungPhanRa(nn.Module):
    """Bảng nhúng phân rã kiểu ALBERT: V×k rồi chiếu k→H.

    Vocab PhoBERT 64k × 312 = 20M tham số, chiếm 81% một model 4 lớp. Phân rã qua
    128 chiều còn 8,2M mà KHÔNG mất token nào (UNK vẫn 0%). Bảng nhúng chỉ là tra
    bảng nên đổi cái này gần như không đụng tới tốc độ — nó ăn dung lượng, không
    ăn tính toán.
    """

    def __init__(self, V: int, k: int, H: int, pad: int):
        super().__init__()
        self.nhung = nn.Embedding(V, k, padding_idx=pad)
        self.chieu = nn.Linear(k, H, bias=False)

    def forward(self, ids):
        return self.chieu(self.nhung(ids))


def dung_than(nho: bool = False, phan_ra: int = 0):
    """nho=False → PhoBERT-base 12 lớp (thầy). nho=True → 4 lớp/312 (trò)."""
    if not nho:
        return AutoModel.from_pretrained(NEN)
    cfg = AutoConfig.from_pretrained(NEN).to_dict()
    cfg.pop("architectures", None)
    cfg.update(model_type="bert", num_hidden_layers=4, hidden_size=312,
               num_attention_heads=12, intermediate_size=1200)
    than = BertModel(BertConfig(**cfg))
    if phan_ra:
        e = than.embeddings
        e.word_embeddings = NhungPhanRa(than.config.vocab_size, phan_ra,
                                        than.config.hidden_size, than.config.pad_token_id)
    return than


class ModelFrame(nn.Module):
    """Một thân, nhiều đầu phân loại.

    Confidence = softmax NHỎ NHẤT trong các đầu, không phải trung bình: sai một
    trường là hỏng cả lệnh, nên phải lấy mắt xích yếu nhất.
    """

    def __init__(self, than, bang: Bang, truong: list[str]):
        super().__init__()
        self.than, self.truong = than, truong
        H = than.config.hidden_size
        self.dau = nn.ModuleDict({t: nn.Linear(H, bang.cd(t)) for t in truong})
        self.drop = nn.Dropout(0.1)

    def forward(self, input_ids, attention_mask, **_):
        v = self.than(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state[:, 0]
        v = self.drop(v)
        return {t: self.dau[t](v) for t in self.truong}


@torch.no_grad()
def cham(model, tok, bang, mau, dev, truong, bo_qua_none=False, quyet=("device", "action")):
    """bo_qua_none: golden chỉ khai trường nó quan tâm — 100% ca không khai `unit`,
    84% không khai `zone`. Chấm model sai vì nó đoán một trường mà bộ chuẩn KHÔNG
    khẳng định gì là đo nhầm, không phải model kém."""
    model.eval()
    dung = {t: 0 for t in truong}
    dem: dict[str, int] = {}
    tron_frame = 0
    tin_dung, tin_sai = [], []
    for i in range(0, len(mau), 64):
        lo = mau[i:i + 64]
        enc = tok([m["text"] for m in lo], truncation=True, max_length=MAX_LEN,
                  padding=True, return_tensors="pt").to(dev)
        lg = model(**enc)
        prob = {t: torch.softmax(lg[t].float(), -1) for t in truong}
        doan = {t: prob[t].argmax(-1).cpu() for t in truong}
        tin = torch.stack([prob[t].max(-1).values for t in truong]).min(0).values.cpu()
        for j, m in enumerate(lo):
            het = True
            for t in truong:
                if bo_qua_none and m.get(t) is None:
                    continue
                dem[t] = dem.get(t, 0) + 1
                if not bang.co(t, m.get(t)):
                    het = False
                    continue
                if doan[t][j].item() == bang.so(t, m.get(t)):
                    dung[t] += 1
                elif t in quyet:
                    het = False
            tron_frame += het
            (tin_dung if het else tin_sai).append(tin[j].item())
    n = max(len(mau), 1)
    return {"n": len(mau), "frame": tron_frame / n,
            **{t: dung[t] / max(dem.get(t, n), 1) for t in truong},
            "tin_dung": sum(tin_dung) / max(len(tin_dung), 1),
            "tin_sai": sum(tin_sai) / max(len(tin_sai), 1)}


KHONG = "None"      # lớp "không phải lệnh xe" — device rỗng


@torch.no_grad()
def cham_golden(model, tok, bang, duong, im, dev, nguong=(0.5, 0.6, 0.7, 0.8, 0.9)):
    """Phép chấm thật. Khác bản cũ ba điểm:

    1. CHẶT  — frame đúng nghĩa là MỌI trường bộ chuẩn khai đều khớp, không phải
               chỉ device+action. Bản cũ cho "mở cửa kính ghế lái" ra zone=all vẫn
               tính đúng.
    2. ĐO CẢ SỰ IM LẶNG — 109 câu model nên từ chối. Bản cũ vứt hết, nên một model
               luôn đoán bừa và một model biết nhường cho cloud cho cùng con số.
    3. ĐƯỜNG CONG NGƯỠNG — precision/coverage theo từng mức tin, thay vì hai số
               trung bình. Đây mới là thứ nói được có đặt ngưỡng được hay không.

    Trường bộ chuẩn không khai thì bỏ qua, KHÔNG tính là sai (golden không khai
    `unit` ở ca nào; chấm model sai vì nó đoán một thứ không ai khẳng định là đo nhầm).
    """
    model.eval()

    def doan(mau):
        ra = []
        for i in range(0, len(mau), 64):
            lo = mau[i:i + 64]
            enc = tok([m["text"] for m in lo], truncation=True, max_length=MAX_LEN,
                      padding=True, return_tensors="pt").to(dev)
            lg = model(**enc)
            prob = {t: torch.softmax(lg[t].float(), -1) for t in TRUONG}
            tin = torch.stack([prob[t].max(-1).values for t in TRUONG]).min(0).values.cpu()
            arg = {t: prob[t].argmax(-1).cpu() for t in TRUONG}
            for j in range(len(lo)):
                ra.append(({t: bang.nguoc[t][arg[t][j].item()] for t in TRUONG},
                           tin[j].item()))
        return ra

    # ----- nhóm phải ra frame
    dung = {t: 0 for t in TRUONG}
    dem = {t: 0 for t in TRUONG}
    chat = da = 0
    ghi = []
    for m, (d, tin) in zip(duong, doan(duong)):
        het_chat = het_da = True
        for t in TRUONG:
            if m.get(t) is None:
                continue
            dem[t] += 1
            if d[t] == str(m[t]):
                dung[t] += 1
            else:
                het_chat = False
                if t in ("device", "action"):
                    het_da = False
        chat += het_chat
        da += het_da
        ghi.append((tin, het_chat))

    # ----- nhóm phải im lặng
    im_dung = 0
    for _, (d, tin) in zip(im, doan(im)):
        ok = d["device"] == KHONG
        im_dung += ok
        ghi.append((tin, ok))

    kq = {"n_duong": len(duong), "n_im": len(im),
          "frame_chat": chat / max(len(duong), 1),
          "frame_device_action": da / max(len(duong), 1),
          "tu_choi_dung": im_dung / max(len(im), 1)}
    for t in TRUONG:
        kq[t] = dung[t] / dem[t] if dem[t] else None      # None = bộ chuẩn không khai

    # ----- đường cong ngưỡng
    kq["nguong"] = []
    for ng in nguong:
        giu = [ok for tin, ok in ghi if tin >= ng]
        kq["nguong"].append({
            "nguong": ng,
            "phu": len(giu) / max(len(ghi), 1),                       # còn giữ lại bao nhiêu
            "dung": (sum(giu) / len(giu)) if giu else None,           # trong số giữ lại, đúng bao nhiêu
        })
    return kq


def in_golden(kq: dict, ten: str = "GOLDEN") -> None:
    print(f"  {ten}  frame chặt {kq['frame_chat']:.1%}  "
          f"(device+action {kq['frame_device_action']:.1%})  "
          f"từ chối đúng {kq['tu_choi_dung']:.1%} trên {kq['n_im']} câu")
    truong = "  ".join(f"{t} {kq[t]:.0%}" if kq[t] is not None else f"{t} n/a"
                       for t in TRUONG)
    print(f"        {truong}")
    duong = "  ".join(f"≥{n['nguong']:.1f}: phủ {n['phu']:.0%} đúng "
                      + (f"{n['dung']:.0%}" if n["dung"] is not None else "n/a")
                      for n in kq["nguong"])
    print(f"        {duong}")


# ------------------------------------------------------------------ vòng train
def chay(model, dl, opt, dev, truong, amp, buoc=None):
    model.train()
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    tong = 0.0
    for b in dl:
        b = {k: v.to(dev) for k, v in b.items()}
        with torch.amp.autocast("cuda", enabled=amp):
            lg = model(**b)
            loss = buoc(lg, b) if buoc else sum(F.cross_entropy(lg[t], b[t]) for t in truong)
        opt.zero_grad()
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
        tong += loss.item()
    return tong / max(len(dl), 1)


def gd_massive(a, tok, dev):
    """Bước 1 — thân làm quen văn phong ra lệnh tiếng Việt."""
    mau = doc_massive(Path(a.massive))
    random.Random(0).shuffle(mau)
    cat = int(len(mau) * 0.95)
    bang = Bang.tu_mau(mau, ["intent"])
    model = ModelFrame(dung_than(nho=False), bang, ["intent"]).to(dev)
    print(f"[1/3] MASSIVE  {len(mau)} câu, {bang.cd('intent')} intent  "
          f"({sum(p.numel() for p in model.parameters())/1e6:.0f}M)")

    dl = DataLoader(BoMau(mau[:cat], tok, bang, ["intent"]), batch_size=a.bs, shuffle=True)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr or 2e-5)
    bd = time.monotonic()
    for ep in range(1, a.epochs + 1):
        loss = chay(model, dl, opt, dev, ["intent"], a.amp)
        v = cham(model, tok, bang, mau[cat:], dev, ["intent"], quyet=("intent",))
        print(f"  epoch {ep}  loss {loss:6.3f}  val intent {v['intent']:.1%}  "
              f"{time.monotonic()-bd:.0f}s", flush=True)

    out = Path(a.out) / "massive"
    out.mkdir(parents=True, exist_ok=True)
    # CHỈ lưu thân. Đầu intent của MASSIVE vô dụng với bài của mình.
    torch.save(model.than.state_dict(), out / "than.pt")
    print(f"-> {out/'than.pt'}  (chỉ thân, đầu intent bỏ đi)")


def gd_mien(a, tok, dev):
    """Bước 2 — gắn đầu của mình, học 30 thiết bị VF9."""
    mau = doc_mien(Path(a.data))
    random.Random(0).shuffle(mau)
    cat = int(len(mau) * 0.9)
    bang = Bang.tu_mau(mau, TRUONG)
    than = dung_than(nho=False)
    if a.tu_than:
        thieu = than.load_state_dict(torch.load(a.tu_than, map_location="cpu"), strict=False)
        print(f"[2/3] nạp thân từ bước 1 ({len(thieu.missing_keys)} khoá thiếu)")
    else:
        print("[2/3] KHÔNG nạp thân bước 1 — dùng PhoBERT gốc")
    model = ModelFrame(than, bang, TRUONG).to(dev)
    g_duong, g_im = doc_golden()
    print(f"      train {cat}  val {len(mau)-cat}  "
          f"golden {len(g_duong)} dương / {len(g_im)} phải im  "
          f"nhãn: " + ", ".join(f"{t}={bang.cd(t)}" for t in TRUONG))

    dl = DataLoader(BoMau(mau[:cat], tok, bang, TRUONG), batch_size=a.bs, shuffle=True)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr or 3e-5)
    bd = time.monotonic()
    for ep in range(1, a.epochs + 1):
        loss = chay(model, dl, opt, dev, TRUONG, a.amp)
        v = cham(model, tok, bang, mau[cat:], dev, TRUONG)
        print(f"  epoch {ep}  loss {loss:6.3f}  val {v['frame']:.1%}  "
              f"{time.monotonic()-bd:.0f}s", flush=True)
        in_golden(cham_golden(model, tok, bang, g_duong, g_im, dev))

    out = Path(a.out) / "mien"
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "model.pt")
    bang.luu(out / "labels.json")
    g = cham_golden(model, tok, bang, g_duong, g_im, dev)
    (out / "ket_qua.json").write_text(json.dumps({"golden": g}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    print(f"-> {out}")
    in_golden(g, "GOLDEN cuối")


def gd_chung_cat(a, tok, dev):
    """Bước 3 — trò 4 lớp học theo thầy. Đây mới là thứ lên xe.

    Trò học hai nguồn cùng lúc:
      - dữ liệu miền, có nhãn thật  -> cross-entropy
      - đầu ra mềm của thầy         -> KL, mang theo cả những gì thầy "lưỡng lự"
    Cộng câu MASSIVE không nhãn, thầy tự dán nhãn mềm: trò được nhìn tiếng Việt
    thật chứ không chỉ câu mình sinh ra.
    """
    thu_muc = Path(a.thay).parent
    bang = Bang.doc(thu_muc / "labels.json")
    thay = ModelFrame(dung_than(nho=False), bang, TRUONG)
    thay.load_state_dict(torch.load(a.thay, map_location="cpu"))
    thay.to(dev).eval()
    for p in thay.parameters():
        p.requires_grad = False

    tro = ModelFrame(dung_than(nho=True, phan_ra=a.phan_ra), bang, TRUONG).to(dev)
    n_thay = sum(p.numel() for p in thay.parameters())
    n_tro = sum(p.numel() for p in tro.parameters())
    print(f"[3/3] thầy {n_thay/1e6:.0f}M -> trò {n_tro/1e6:.1f}M "
          f"({n_tro/1e6:.0f}MB int8, phân rã nhúng {a.phan_ra or 'tắt'})")

    mau = doc_mien(Path(a.data))
    random.Random(0).shuffle(mau)
    cat = int(len(mau) * 0.9)
    hoc = list(mau[:cat])
    if a.massive and Path(a.massive).exists():
        them = doc_massive(Path(a.massive))
        # Nhãn để tạm; thầy sẽ dán nhãn mềm, phần cứng bị tắt bằng trong_so.
        hoc += [{"text": m["text"], **{t: None for t in TRUONG}, "chi_mem": True} for m in them]
        print(f"      + {len(them)} câu MASSIVE, thầy dán nhãn mềm")
    hoc = [m for m in hoc if all(bang.co(t, m.get(t)) for t in TRUONG) or m.get("chi_mem")]
    for m in hoc:
        for t in TRUONG:
            if not bang.co(t, m.get(t)):
                m[t] = bang.nguoc[t][0]      # chỗ giữ chỗ, bị tắt bằng mặt nạ
    random.Random(1).shuffle(hoc)
    g_duong, g_im = doc_golden()
    print(f"      học {len(hoc)}  golden {len(g_duong)} dương / {len(g_im)} phải im")

    class Bo(BoMau):
        def __getitem__(self, i):
            it = super().__getitem__(i)
            it["cung"] = torch.tensor(0.0 if self.mau[i].get("chi_mem") else 1.0)
            return it

    dl = DataLoader(Bo(hoc, tok, bang, TRUONG), batch_size=a.bs, shuffle=True)
    opt = torch.optim.AdamW(tro.parameters(), lr=a.lr or 5e-4)
    T, alpha = a.nhiet, a.alpha

    def buoc(lg_tro, b):
        with torch.no_grad():
            lg_thay = thay(input_ids=b["input_ids"], attention_mask=b["attention_mask"])
        mat = 0.0
        for t in TRUONG:
            ce = F.cross_entropy(lg_tro[t], b[t], reduction="none")
            kl = F.kl_div(F.log_softmax(lg_tro[t].float() / T, -1),
                          F.softmax(lg_thay[t].float() / T, -1),
                          reduction="none").sum(-1) * (T * T)
            mat = mat + (alpha * ce * b["cung"] + (1 - alpha) * kl).mean()
        return mat

    bd = time.monotonic()
    for ep in range(1, a.epochs + 1):
        loss = chay(tro, dl, opt, dev, TRUONG, a.amp, buoc=buoc)
        v = cham(tro, tok, bang, mau[cat:], dev, TRUONG)
        print(f"  epoch {ep}  loss {loss:7.3f}  val {v['frame']:.1%}  "
              f"{time.monotonic()-bd:.0f}s", flush=True)
        in_golden(cham_golden(tro, tok, bang, g_duong, g_im, dev), "  trò")

    out = Path(a.out) / "chung-cat"
    out.mkdir(parents=True, exist_ok=True)
    torch.save(tro.state_dict(), out / "tro.pt")
    bang.luu(out / "labels.json")
    g = cham_golden(tro, tok, bang, g_duong, g_im, dev)
    t_thay = cham_golden(thay, tok, bang, g_duong, g_im, dev)
    (out / "ket_qua.json").write_text(json.dumps(
        {"tham_so_tro": n_tro, "golden_tro": g, "golden_thay": t_thay},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {out}")
    in_golden(t_thay, "thầy")
    in_golden(g, "trò ")
    print(f"   trò {n_tro/1e6:.1f}M tham số — giữ lại "
          f"{g['frame_chat']/max(t_thay['frame_chat'],1e-9):.0%} của thầy")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--giai-doan", required=True, choices=["massive", "mien", "chung-cat"])
    ap.add_argument("--data", default=str(ROOT / "nlu" / "data" / "synth.jsonl"))
    ap.add_argument("--massive", default="")
    ap.add_argument("--tu-than", default="")
    ap.add_argument("--thay", default="")
    ap.add_argument("--out", default=str(ROOT / "nlu" / "runs"))
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--lr", type=float, default=0.0)
    ap.add_argument("--phan-ra", type=int, default=128, help="0 = tắt phân rã bảng nhúng")
    ap.add_argument("--nhiet", type=float, default=2.0)
    ap.add_argument("--alpha", type=float, default=0.5)
    a = ap.parse_args()

    dev = thiet_bi()
    a.amp = dev == "cuda"
    torch.manual_seed(0)
    tok = AutoTokenizer.from_pretrained(NEN)
    print(f"thiết bị {dev}{' + fp16' if a.amp else ''}")
    {"massive": gd_massive, "mien": gd_mien, "chung-cat": gd_chung_cat}[a.giai_doan](a, tok, dev)


if __name__ == "__main__":
    main()
