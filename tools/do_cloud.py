"""Đo tầng [2] (cloud) vá được bao nhiêu phần tầng edge bỏ sót.

Cloud chỉ chạy khi edge bó tay. Tỉ lệ đó TỤT theo mỗi lần edge khá lên: ~36%
lúc mới gắn model, còn ~21,8% khi edge phủ 79,4%. Nên giá của một lần chạy hết
cũng tụt theo — đừng chép lại con số cũ, đo lại rồi hãy quyết.

`--mau` vừa là số mẫu cần gom, vừa định ngân sách quét (mau/0,30 + 200 câu).
Muốn chạy HẾT bộ thì cho mau đủ lớn để ngân sách quét phủ cả bộ: 8000 là đủ
cho 24.851 câu.

    python tools/do_cloud.py --mau 500             # mẫu, sai số ±4%
    python tools/do_cloud.py --mau 8000 --jobs 8   # chạy hết
    python tools/do_cloud.py --mau 50 --jobs 2     # thử nhẹ trước
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIELDS = ("device", "action", "zone", "value", "step", "item", "mode")
_CTX: dict = {}


def _setup(cloud: bool):
    """Dựng caps/lexicon một lần cho mỗi tiến trình con."""
    if _CTX:
        return _CTX
    from agentcar.caps import load_caps
    from agentcar.config import LLMSettings, settings
    from agentcar.lexicon import load_lexicon
    from agentcar.llm import build_cloud_path

    caps = load_caps(ROOT / "caps" / "vf9.yaml")
    lex = load_lexicon(caps)
    _CTX.update(caps=caps, lex=lex,
                llm=build_cloud_path(caps, lex, settings()) if cloud else None,
                tat=LLMSettings())
    return _CTX


def _chay(say: str, cloud: bool):
    from agentcar.agent import Agent
    from agentcar.evaluate import _actual

    c = _setup(cloud)
    t0 = time.time()
    agent = (Agent(c["caps"], c["lex"], llm=c["llm"]) if cloud
             else Agent(c["caps"], c["lex"], llm_settings=c["tat"]))
    turn = agent.handle(say)
    got = _actual(turn)
    got["_ms"] = (time.time() - t0) * 1000
    got["_cloud"] = any("tầng [2]" in tr for tr in turn.trace)
    # CẦU DAO MỞ KHÔNG PHẢI KẾT QUẢ ĐO. Cloud chưa hề được hỏi câu này — ghi nó
    # thành "cloud trả lời sai" là bịa. Trong xe cầu dao là đúng (mất mạng thì
    # đừng bắt người ta chờ hết deadline từng câu), nhưng ở đây mỗi tiến trình
    # con giữ CloudPath riêng, tức cầu dao riêng: hai lỗi mạng liên tiếp là nó
    # ngốn sạch phần việc còn lại trong vài mili giây, mỗi câu một lỗi tức thì.
    loi = turn.cloud_error or ""
    got["_khong_do"] = "tạm ngưng" in loi or "không gọi được" in loi
    return got


def _edge_truot(case) -> bool:
    """Edge KHÔNG xử lý được câu này.

    Dùng `commands` chứ không phải `sent`: `sent` cố ý loại lệnh `query` (câu hỏi
    trạng thái không xuống xe), nhưng edge TRẢ LỜI ĐƯỢC câu hỏi đó — coi nó là bó
    tay rồi đem đo cloud là sai. Lần đầu đo dính đúng lỗi này: 139/500 câu trong
    mẫu hoá ra là câu hỏi edge đã xử lý xong.
    """
    return not _chay(case["say"], cloud=False)["commands"]


def _voi_cloud(case):
    got = _chay(case["say"], cloud=True)
    exp = case["expect"]
    return {
        "say": case["say"],
        "khong_do": got["_khong_do"],
        "ra_lenh": bool(got["sent"]),
        "goi_cloud": got["_cloud"],
        "ms": got["_ms"],
        "marks": {f: bool(got.get(f) == exp[f]) for f in FIELDS if f in exp},
        "dung_het": all(got.get(f) == exp[f] for f in FIELDS if f in exp) and bool(got["sent"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mau", type=int, default=500)
    ap.add_argument("--jobs", type=int, default=4, help="ít luồng thôi — đang gọi API thật")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=ROOT / "logs" / "do_cloud.json")
    args = ap.parse_args()

    from agentcar.config import settings
    if not settings().api_key:
        print("không có key trong .env — bỏ"); return

    cases = [c for c in yaml.safe_load(
        (ROOT / "tests" / "golden_qc.vi.yaml").read_text(encoding="utf-8"))
        if isinstance(c, dict) and "expect" in c]
    random.Random(args.seed).shuffle(cases)

    import multiprocessing as mp
    # Quét bằng EDGE (không mạng, nhanh) cho tới khi gom đủ mẫu câu edge bó tay.
    can = int(args.mau / 0.30) + 200
    print(f"quét {min(can, len(cases))} câu bằng edge để gom {args.mau} câu edge bó tay…")
    with mp.Pool(8) as pool:
        co_truot = pool.map(_edge_truot, cases[:can], chunksize=32)
    truot = [c for c, t in zip(cases[:can], co_truot) if t][: args.mau]
    print(f"  gom được {len(truot)} câu\n")

    print(f"gọi cloud thật, {args.jobs} luồng…")
    t0 = time.time()
    with mp.Pool(args.jobs) as pool:
        rows = pool.map(_voi_cloud, truot, chunksize=4)
        # Câu nào cầu dao nuốt thì CHƯA ĐO, phải chờ hết nguội rồi hỏi lại.
        for vong in range(1, 4):
            lam_lai = [c for c, r in zip(truot, rows) if r["khong_do"]]
            if not lam_lai:
                break
            print(f"  vòng {vong}: {len(lam_lai)} câu cầu dao nuốt — chờ nguội 35s rồi hỏi lại…")
            time.sleep(35)
            moi = dict(zip((c["say"] for c in lam_lai),
                           pool.map(_voi_cloud, lam_lai, chunksize=4)))
            rows = [moi.get(r["say"], r) if r["khong_do"] else r for r in rows]
    giay = time.time() - t0

    n = len(rows)
    chua_do = sum(r["khong_do"] for r in rows)
    if chua_do:
        print(f"\n⚠ {chua_do}/{n} câu ({chua_do/n:.1%}) CHƯA ĐO ĐƯỢC — cầu dao vẫn mở sau 3 vòng.")
    # Dưới 2% thì loại ra rồi đo tiếp; trên thì mọi con số bên dưới đều vô nghĩa,
    # thà không in còn hơn in ra bảng trông như thật. Lần đầu dính: 8 luồng, 4.103
    # câu bị cầu dao nuốt, bảng hiện "cloud đúng 2,3%" y như một phát hiện.
    if chua_do > n * 0.02:
        print("  → GIẢM --jobs (thử 2–3) rồi chạy lại. KHÔNG dùng số của lần này.")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        raise SystemExit(1)
    rows = [r for r in rows if not r["khong_do"]]
    n = len(rows)
    ra = sum(r["ra_lenh"] for r in rows)
    dung = sum(r["dung_het"] for r in rows)
    goi = sum(r["goi_cloud"] for r in rows)
    ms = sorted(r["ms"] for r in rows if r["goi_cloud"])
    print(f"\n{n} câu edge bó tay · {giay:.0f}s · {args.jobs} luồng")
    print(f"  thật sự gọi cloud     {goi:5d}  ({goi/n:.1%})")
    print(f"  cloud RA ĐƯỢC lệnh    {ra:5d}  ({ra/n:.1%})")
    print(f"  ĐÚNG mọi trường       {dung:5d}  ({dung/n:.1%})   ← cloud vá được ngần này")
    if ms:
        print(f"  độ trễ  trung vị {ms[len(ms)//2]:.0f}ms · p90 {ms[int(len(ms)*.9)]:.0f}ms · max {ms[-1]:.0f}ms")

    f = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        for k, v in r["marks"].items():
            f[k][0] += v; f[k][1] += 1
    print("\n  theo trường (trên câu có expect trường đó):")
    for k in FIELDS:
        a, b = f[k]
        if b:
            print(f"    {k:<8}{a/b:6.1%}  ({a}/{b})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    try:
        duong = args.out.resolve().relative_to(ROOT)
    except ValueError:
        duong = args.out                      # --out trỏ ra ngoài repo: in nguyên
    print(f"\nchi tiết: {duong}")


if __name__ == "__main__":
    main()
