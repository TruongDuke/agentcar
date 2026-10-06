"""Mốc đo cho TẦNG CLOUD. Song song với tools/score_fields.py của tầng edge.

Vì sao không dùng tools/do_cloud.py: nó đo trên "câu tầng edge bỏ sót". Tập đó
ĐỔI mỗi lần edge khá lên — edge sửa xong thì câu dễ rời khỏi tập, tập còn lại
khó hơn, và điểm cloud TỤT dù cloud không đổi gì. Hai lần đo không so được.

Ở đây dùng tập CỐ ĐỊNH: 8.121 câu QC đánh dấu cần mạng (cột `Offline` để
trống trong file test của QC, mang sang golden thành `tren_xe: false`). Tập
này không nhúc nhích theo edge, nên con số của hôm nay so được với hôm sau.

Ba con số, đừng lẫn:

  tổng đúng       trên CẢ tập — hệ hai tầng làm đúng bao nhiêu
  edge tự lo      edge trả lời luôn, cloud không được gọi
  cloud khi gọi   chỉ trên câu THẬT SỰ lên cloud — đây mới là điểm của cloud

    python tools/score_cloud.py --mau 500            # ±4%, ~2 phút
    python tools/score_cloud.py --mau 500 --save tests/baseline_cloud.json
    python tools/score_cloud.py --mau 500 --compare tests/baseline_cloud.json
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIELDS = ("device", "action", "zone", "value", "step", "item", "mode")
_CTX: dict = {}


def _setup():
    """Dựng một lần cho mỗi tiến trình con — nạp caps và model tốn ~1s."""
    if _CTX:
        return _CTX
    from agentcar.caps import load_caps
    from agentcar.config import settings
    from agentcar.lexicon import load_lexicon
    from agentcar.llm import build_cloud_path
    caps = load_caps(ROOT / "caps" / "vf9.yaml")
    lex = load_lexicon(caps)
    _CTX.update(caps=caps, lex=lex, llm=build_cloud_path(caps, lex, settings()))
    return _CTX


def _prompt_that() -> str:
    """ĐÚNG chuỗi system gửi lên máy chủ, không phải khuôn SYSTEM thô.

    Prompt thật ghép từ BỐN nguồn: SYSTEM + digest (sinh từ caps/vf9.yaml và
    caps/lexicon.vi.yaml) + rules (sinh từ caps/reasoning.vi.yaml). Sửa bất kỳ
    nguồn nào cũng đổi kết quả đo, nên vân tay phải phủ hết.
    """
    from agentcar.llm import SYSTEM, MAX_COMMANDS, render_digest, render_rules, load_rules
    c = _setup()
    return SYSTEM.format(model=c["caps"].model,
                         digest=render_digest(c["caps"], c["lex"]),
                         max_commands=MAX_COMMANDS,
                         rules=render_rules(c["caps"], load_rules()))


def _one(case: dict) -> dict:
    """MỘT lượt gọi cloud cho mỗi câu, không phải hai.

    Bản trước gọi interpret() lấy raw rồi lại chạy agent — hai lượt KHÁC NHAU,
    mà cloud không tất định, nên "cloud có lệnh mà bị chặn" bị thổi lên gấp đôi.
    Bọc interpret để ghi lại đúng lượt agent đã dùng.
    """
    from agentcar.agent import Agent
    from agentcar.evaluate import _actual
    c = _setup()
    llm, ghi, goc = c["llm"], {}, c["llm"].interpret

    def bat(text, context=""):
        kq = goc(text, context=context)
        ghi.setdefault("out", kq)
        return kq

    llm.interpret = bat
    try:
        turn = Agent(c["caps"], c["lex"], llm=llm).handle(case["say"])
    finally:
        llm.interpret = goc

    out, got, exp = ghi.get("out"), _actual(turn), case["expect"]
    g = (got["commands"] or [{}])[0]
    dung = bool(got["commands"]) and all(
        g.get(k) == exp[k] for k in FIELDS if exp.get(k) is not None)
    loi = out.error if out is not None else None
    return {
        "say": case["say"],
        "goi_cloud": out is not None,
        # Cầu dao mở = CHƯA ĐO ĐƯỢC, không phải đo sai. Xem _bao_cao.
        "khong_do": bool(loi and ("tạm ngưng" in loi or "không gọi được" in loi)),
        "cloud_ra_lenh": bool(out is not None and out.commands),
        "ms": turn.cloud_ms or 0.0,
        "dung": dung,
        "marks": {f: bool(g.get(f) == exp[f]) for f in FIELDS if f in exp},
        "mong": {f: exp[f] for f in FIELDS if exp.get(f) is not None},
        "duoc": {f: g.get(f) for f in FIELDS if g.get(f) is not None},
        "ly_do": _ly_do(out, got, exp, g, dung),
    }


def _ly_do(out, got, exp, g, dung) -> str:
    if out is None:
        return "edge tự lo"
    if out.error and ("tạm ngưng" in out.error or "không gọi được" in out.error):
        return "chưa đo được"
    if dung:
        return "đúng"
    if not out.commands:
        return "cloud không ra lệnh"
    if not got["commands"]:
        return "cloud ra lệnh, tầng sau chặn"
    if g.get("device") != exp.get("device"):
        return "sai thiết bị"
    if exp.get("action") is not None and g.get("action") != exp["action"]:
        return "sai hành động"
    return "sai tham số"


# Cầu dao mở thì CHỜ rồi gọi lại, đừng bỏ câu. Ba lượt đo 3.000+ câu đã chết
# vì mỗi lần máy chủ chặn hạn mức là mất luôn vài trăm câu. Ở xe thì bỏ là
# đúng (người ta không chờ 30 giây), nhưng ở đây mình đo chứ không lái.
def _kien_nhan(case: dict, lan: int = 4) -> dict:
    import time
    for i in range(lan):
        r = _one(case)
        if not r["khong_do"]:
            return r
        if i < lan - 1:
            time.sleep(8 * (i + 1))
    return r


def _run(cases, jobs):
    if jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs) as pool:
            return pool.map(_kien_nhan, cases, chunksize=2)
    return [_kien_nhan(c) for c in cases]


def do(mau: int, jobs: int, seed: int, bo_qua: int = 0) -> dict:
    from agentcar.config import settings
    from agentcar.evaluate import load_cases
    from agentcar.llm import SYSTEM

    cases = [c for c in load_cases(ROOT / "tests" / "golden_qc.vi.yaml")
             if c.get("expect", {}).get("device") and not c.get("tren_xe")]
    random.Random(seed).shuffle(cases)
    # --bo-qua N bỏ N câu ĐẦU của cùng thứ tự xáo. Dùng để lấy tập CHƯA ĐỘNG
    # VÀO: luật trong prompt viết ra sau khi soi câu sai của mẫu nào thì số đo
    # trên chính mẫu đó là số ĐẸP HƠN THẬT. Đo lại trên phần còn lại mới biết
    # luật có tổng quát hay chỉ vá đúng mấy câu mình đã nhìn.
    chon = cases[bo_qua:bo_qua + mau]
    nguon = f"trong {len(cases):,} câu QC đánh dấu CẦN MẠNG"
    if bo_qua:
        nguon = f"CHƯA ĐỘNG VÀO — bỏ {bo_qua:,} câu đầu, còn {len(cases) - bo_qua:,}"
    print(f"{len(chon)} câu (mẫu seed={seed} {nguon}) · {jobs} luồng…\n")
    rows = _run(chon, jobs)

    chua_do = [r for r in rows if r["khong_do"]]
    if len(chua_do) > len(rows) * 0.02:
        print(f"⚠ {len(chua_do)}/{len(rows)} câu CHƯA ĐO ĐƯỢC — cầu dao mở.")
        print("  → GIẢM --jobs (thử 2) rồi chạy lại. KHÔNG dùng số của lần này.")
        sys.exit(1)
    rows = [r for r in rows if not r["khong_do"]]

    goi = [r for r in rows if r["goi_cloud"]]
    ms = sorted(r["ms"] for r in goi if r["ms"])
    f = collections.defaultdict(lambda: [0, 0])
    for r in goi:
        for k, v in r["marks"].items():
            f[k][0] += v
            f[k][1] += 1
    st = settings()
    return {
        "khi": dt.datetime.now().isoformat(timespec="seconds"),
        "cau_hinh": {
            "model": st.model,
            # Đổi prompt là đổi kết quả. Ghi vân tay để lần sau biết hai mốc có
            # cùng prompt không, khỏi tưởng cloud khá lên trong khi chỉ sửa chữ.
            #
            # Băm PROMPT THẬT - gồm cả digest. Bản trước băm mỗi SYSTEM thô, mà
            # digest mới là chỗ mang danh sách thiết bị/zone/mode. Sửa digest
            # thôi thì vân tay không đổi, hai mốc khác hẳn nhau trông như cùng
            # cấu hình, và cảnh báo bên dưới im lặng. Lần vừa rồi nó bắt được
            # chỉ vì tình cờ sửa cả hai thứ cùng lúc.
            "prompt_sha": hashlib.sha256(_prompt_that().encode()).hexdigest()[:12],
            "seed": seed, "mau": mau, "bo_qua": bo_qua,
        },
        "bo_cau": "tests/golden_qc.vi.yaml (tren_xe=false)",
        "so_cau": len(rows),
        "tong_dung": round(sum(r["dung"] for r in rows) / len(rows), 4),
        "edge_tu_lo": round(1 - len(goi) / len(rows), 4),
        "cloud_khi_goi": round(sum(r["dung"] for r in goi) / len(goi), 4) if goi else 0.0,
        "so_lan_goi": len(goi),
        "do_tre_ms": {"trung_vi": ms[len(ms) // 2] if ms else None,
                      "p90": ms[int(len(ms) * 0.9)] if ms else None,
                      "max": ms[-1] if ms else None},
        "truong_khi_goi": {k: round(a / b, 4) for k, (a, b) in sorted(f.items()) if b},
        "ly_do": dict(collections.Counter(r["ly_do"] for r in rows).most_common()),
        # Giữ từng câu LÊN CLOUD mà sai, kèm cái cloud trả về và cái QC mong.
        # Không giữ thì mỗi lần muốn biết "sai ở đâu" lại phải gọi API lại.
        "sai": [{"say": r["say"], "ly_do": r["ly_do"], "mong": r["mong"], "duoc": r["duoc"]}
                for r in rows if r["goi_cloud"] and not r["dung"]],
    }


def _in(m: dict, cu: dict | None) -> None:
    def d(x, *path):
        if not cu:
            return ""
        o = cu
        for p in path:
            o = (o or {}).get(p) if isinstance(o, dict) else None
        return f"   ({x - o:+.1%} so mốc)" if isinstance(o, (int, float)) else ""

    c = m["cau_hinh"]
    print(f"{m['so_cau']} câu · {m['bo_cau']}")
    print(f"cấu hình: {c['model']} · prompt {c['prompt_sha']} · seed {c['seed']}")
    if cu and cu["cau_hinh"].get("prompt_sha") != c["prompt_sha"]:
        print("  ⚠ MỐC CŨ KHÁC PROMPT — chênh lệch bên dưới trộn cả thay đổi prompt.")
    print()
    print(f"  tổng đúng        {m['tong_dung']:6.1%}{d(m['tong_dung'], 'tong_dung')}")
    print(f"  edge tự lo       {m['edge_tu_lo']:6.1%}{d(m['edge_tu_lo'], 'edge_tu_lo')}")
    print(f"  CLOUD KHI GỌI    {m['cloud_khi_goi']:6.1%}{d(m['cloud_khi_goi'], 'cloud_khi_goi')}"
          f"   ({m['so_lan_goi']} lượt)")
    t = m["do_tre_ms"]
    print(f"  độ trễ           trung vị {t['trung_vi']:.0f}ms · p90 {t['p90']:.0f}ms"
          f" · max {t['max']:.0f}ms")
    print("\ntheo trường, chỉ trên câu ĐÃ LÊN CLOUD:")
    print("  " + "  ".join(f"{k} {v:.1%}" for k, v in m["truong_khi_goi"].items()))
    print("\nlý do:")
    for k, v in m["ly_do"].items():
        print(f"  {v:5d}  ({v / m['so_cau']:5.1%})  {k}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mau", type=int, default=500)
    ap.add_argument("--jobs", type=int, default=3, help="ít thôi — gọi API thật, nhiều là dính cầu dao")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--bo-qua", type=int, default=0, dest="bo_qua",
                    help="bỏ N câu đầu — lấy tập CHƯA dùng để chỉnh prompt")
    ap.add_argument("--lan", type=int, default=1,
                    help="chạy N lượt rồi lấy trung bình. CHỈ khử tính bất định "
                         "của model, KHÔNG khử sai số mẫu — muốn thế thì tăng --mau")
    ap.add_argument("--save", type=Path)
    ap.add_argument("--compare", type=Path)
    a = ap.parse_args()

    from agentcar.config import settings
    if not settings().api_key:
        sys.exit("chưa có API key trong .env")

    if a.lan > 1:
        # Cùng cấu hình, ba lượt đo ra 64,2 / 66,4 / 65,7 — cloud không tất định.
        #
        # NHƯNG trung bình nhiều lượt CHỈ khử được chuyện đó. Sai số MẪU vẫn
        # nguyên: 137 câu là cố định, chạy lại vẫn đúng 137 câu ấy, và ở n=137
        # biên là ±4%. Muốn thấy hiệu ứng 1-2 điểm thì phải TĂNG --mau cho
        # nhiều câu lên cloud hơn, chạy thêm lượt không giúp gì.
        ds = [do(a.mau, a.jobs, a.seed, a.bo_qua) for _ in range(a.lan)]
        xs = [x["cloud_khi_goi"] for x in ds]
        m = ds[-1]
        m["cloud_khi_goi"] = round(sum(xs) / len(xs), 4)
        m["cloud_khi_goi_cac_lan"] = xs
        m["cau_hinh"]["lan"] = a.lan
        print(f"\n{a.lan} lượt: " + " · ".join(f"{x:.1%}" for x in xs)
              + f"   trung bình {m['cloud_khi_goi']:.1%}"
              + f"   biên ±{(max(xs) - min(xs)) / 2:.1%}\n")
    else:
        m = do(a.mau, a.jobs, a.seed, a.bo_qua)
    cu = json.loads(a.compare.read_text(encoding="utf-8")) if a.compare and a.compare.exists() else None
    _in(m, cu)
    if a.save:
        a.save.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            duong = a.save.resolve().relative_to(ROOT)
        except ValueError:
            duong = a.save            # --save trỏ ra ngoài repo: in nguyên
        print(f"\nđã ghi mốc: {duong}")


if __name__ == "__main__":
    main()
