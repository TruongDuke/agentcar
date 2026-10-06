"""Chấm bộ câu chuẩn theo TỪNG TRƯỜNG, và ghi/so mốc.

Vì sao không dùng thẳng `agentcar eval`: nó trả đúng/sai nguyên câu, nên sai zone
rớt y như sai device. Trên 24k câu thì con số đó không chỉ được phải sửa gì.

CHỈ SỐ CHÍNH LÀ MẪU SỐ ĐẦY ĐỦ (/ mọi câu), không phải mẫu số "câu đã ra lệnh".
Lý do: chỉ số có điều kiện tự chọn mẫu cho mình — tầng matching chỉ trả lời câu
dễ nên đạt device 94%, nhưng thêm tầng NLU vào là tụt ngay, KỂ CẢ khi hệ thống
tốt lên thật, vì mẫu số phình thêm toàn câu khó. Mẫu số đầy đủ không có bẫy đó:
thêm tầng thì nó chỉ có thể tăng.

Chỉ số phụ `_khi_ra_lệnh` vẫn in ra, nhưng để đọc kèm độ phủ, không đứng một mình.

`oan` (ra lệnh khi đáng lẽ phải im) là CỔNG CHẶN, không phải chỉ số để tối ưu:
trong xe, ra lệnh oan tệ hơn không hiểu.

    python tools/score_fields.py tests/golden_qc.vi.yaml \
        --negative tests/golden_qc_negative.vi.yaml --save tests/baseline_qc.json
    python tools/score_fields.py tests/golden_qc.vi.yaml \
        --negative tests/golden_qc_negative.vi.yaml --compare tests/baseline_qc.json
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIELDS = ("device", "action", "zone", "value", "step", "item", "mode")
_CAPS = None
_NGUONG: float | None = None          # ép ngưỡng tầng NLU, để so hai ngưỡng


def _caps():
    global _CAPS
    if _CAPS is None:
        from dataclasses import replace

        from agentcar.caps import load_caps
        _CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
        if _NGUONG is not None:
            _CAPS = replace(_CAPS, nlu={**_CAPS.nlu, "nguong": _NGUONG})
    return _CAPS


def _dat_nguong(x):
    """Chạy trong tiến trình con TRƯỚC khi caps được dựng."""
    global _NGUONG
    _NGUONG = x


_TAT_NLU = False


def _dat_tat_nlu(x: bool) -> None:
    global _TAT_NLU
    _TAT_NLU = x


def _nlu_bat() -> bool:
    from agentcar.nlu import co_model
    return co_model() and not _TAT_NLU


def _one(case: dict) -> dict:
    """Chạy 1 câu. `commanded` = CÓ LỆNH THẬT SỰ XUỐNG XE, không phải có object lệnh.

    `turn.results` liệt kê cả lệnh `query` (chỉ hỏi trạng thái) và lệnh trùng
    trạng thái hiện tại (`da_dung`, bị lọc khỏi `runnable` nên không gửi). Đếm
    hai loại đó là "đã ra lệnh" làm chỉ số ra-lệnh-oan phồng lên ~60 câu.
    """
    from agentcar.evaluate import run_case

    r = run_case(_caps(), case, nlu=False if _TAT_NLU else None)
    exp, got = case["expect"], r.got
    return {
        "say": r.say,
        "device": exp.get("device"),
        "passed": r.passed,
        "commanded": bool(got.get("commands")),   # có lệnh trong plan
        "sent": bool(got.get("sent")),            # thật sự xuống xe
        "marks": {f: bool(got.get(f) == exp[f]) for f in FIELDS if f in exp},
    }


def _khoi_dong(nguong, tat_nlu) -> None:
    _dat_nguong(nguong)
    _dat_tat_nlu(tat_nlu)


def _run(cases: list[dict], jobs: int) -> list[dict]:
    if jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs, initializer=_khoi_dong,
                     initargs=(_NGUONG, _TAT_NLU)) as pool:
            return pool.map(_one, cases, chunksize=64)
    return [_one(c) for c in cases]


def _load(path: Path) -> list[dict]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    # Tập "phải im" viết dạng danh sách chuỗi cho gọn.
    return [r if isinstance(r, dict) else {"say": r, "expect": {"no_command": True}}
            for r in rows]


def _rel(p: Path) -> str:
    """Tên ngắn để ghi vào mốc, dù người dùng gõ đường dẫn tương đối hay tuyệt đối."""
    p = p.resolve()
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def measure(golden: Path, negative: Path | None, jobs: int,
            limit: int | None = None) -> dict:
    cases = _load(golden)
    if limit:
        import random
        random.Random(5).shuffle(cases)          # hạt cố định: hai lần chạy cùng mẫu
        cases = cases[:limit]
    rows = _run(cases, jobs)
    n = len(rows)
    spoke = [r for r in rows if r["commanded"]]

    full, cond = {}, {}
    per_dev: dict = collections.defaultdict(lambda: [0, 0])
    for f in FIELDS:
        ok = sum(r["marks"].get(f, False) for r in rows)
        tot = sum(f in r["marks"] for r in rows)
        ok_s = sum(r["marks"].get(f, False) for r in spoke)
        tot_s = sum(f in r["marks"] for r in spoke)
        if tot:
            full[f] = round(ok / tot, 4)
        if tot_s:
            cond[f] = round(ok_s / tot_s, 4)
    for r in rows:
        if "device" in r["marks"]:
            per_dev[r["device"]][0] += r["marks"]["device"]
            per_dev[r["device"]][1] += 1

    out = {
        "khi": dt.datetime.now().isoformat(timespec="seconds"),
        # Cấu hình PHẢI ghi cùng số đo. Cùng một bộ câu mà đổi chính sách hay tắt
        # tầng NLU là ra số khác hẳn — không ghi thì lần sau so hai mốc khác cấu
        # hình mà tưởng là hồi quy.
        "cau_hinh": {
            "policy": dict(_caps().policy),
            "tang_nlu": _nlu_bat(),
            "nguong_nlu": _caps().nlu.get("nguong"),
        },
        "bo_cau": _rel(golden),
        "so_cau": n,
        "do_phu": round(len(spoke) / n, 4) if n else 0.0,
        "dung_ca_cau": round(sum(r["passed"] for r in rows) / n, 4) if n else 0.0,
        "truong": full,
        "truong_khi_ra_lenh": cond,
        # CHỈ đếm trường `device` đúng hay sai — KHÔNG phải "câu về thiết bị này
        # đúng bao nhiêu phần trăm". Tên cũ `theo_thiet_bi` làm chính tôi đọc
        # nhầm: window ở đây 92,2% trong khi chấm trọn vẹn câu cửa kính chỉ
        # 24,9%. Dùng để biết thiết bị nào hay bị NHẬN NHẦM, chỉ vậy.
        # auto_highbeam/hud = 0% là ĐÚNG: VF9 không có, không bao giờ nhận ra.
        "nhan_dung_thiet_bi": {d: round(a / b, 4)
                               for d, (a, b) in sorted(per_dev.items()) if b},
    }

    if negative:
        nrows = _run(_load(negative), jobs)
        oan = sum(r["commanded"] for r in nrows)
        oan_that = sum(r["sent"] for r in nrows)
        out["im_lang"] = {
            "bo_cau": _rel(negative),
            "so_cau": len(nrows),
            "ra_lenh_oan": oan,                    # có lệnh trong plan (định nghĩa chặt của repo)
            "ty_le_oan": round(oan / len(nrows), 4) if nrows else 0.0,
            "gui_xuong_xe": oan_that,              # xe thật sự làm gì đó
            "ty_le_gui": round(oan_that / len(nrows), 4) if nrows else 0.0,
        }

    # precision / recall / F1 — cùng một số liệu, gọi bằng tên mà người ngoài
    # dự án quen đọc. recall CHÍNH LÀ dung_ca_cau; precision là phần đúng trong
    # những câu đã ra lệnh. Tính exact match: sai một trường, kể cả mỗi vùng,
    # là tính sai cả câu — nghiêm hơn P/R thường gặp.
    #
    # Mẫu rất lệch (24.851 câu dương so với 137 câu âm) nên mấy câu ra lệnh oan
    # gần như không kéo được precision xuống. Vì vậy precision ở đây đo "ra lệnh
    # có ĐÚNG không", KHÔNG đo "có NÊN ra lệnh không" — chuyện thứ hai nằm ở
    # im_lang.ty_le_gui, và trong xe nó quan trọng hơn.
    tp = sum(r["passed"] for r in rows)
    da_ra = len(spoke) + (out.get("im_lang", {}).get("gui_xuong_xe") or 0)
    pre = tp / da_ra if da_ra else 0.0
    rec = out["dung_ca_cau"]
    out["pr"] = {
        "precision": round(pre, 4),
        "recall": round(rec, 4),
        "f1": round(2 * pre * rec / (pre + rec), 4) if (pre + rec) else 0.0,
        "ghi_chu": "exact match; mẫu lệch nên xem kèm im_lang.ty_le_gui",
    }
    return out


def _pct(x) -> str:
    return f"{x:6.1%}" if isinstance(x, (int, float)) else "     —"


def report(m: dict, old: dict | None = None) -> None:
    def delta(new, path):
        if not old:
            return ""
        cur = old
        for k in path:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        if not isinstance(cur, (int, float)) or not isinstance(new, (int, float)):
            return ""
        d = new - cur
        return f"   ({d:+.1%} so mốc)" if abs(d) >= 0.0005 else "   (không đổi)"

    cfg = m.get("cau_hinh") or {}
    if cfg:
        pol = " ".join(f"{k}={v}" for k, v in (cfg.get("policy") or {}).items())
        print(f"\ncấu hình: tầng NLU {'BẬT' if cfg.get('tang_nlu') else 'TẮT'}"
              f" (ngưỡng {cfg.get('nguong_nlu')}) · {pol}")
        if old is not None:
            cu = old.get("cau_hinh")
            if cu is None:
                print("  ⚠ MỐC CŨ KHÔNG GHI CẤU HÌNH — không biết nó đo ở cấu hình nào, "
                      "chênh lệch bên dưới chỉ để tham khảo.")
            elif cu != cfg:
                print("  ⚠ MỐC CŨ KHÁC CẤU HÌNH — chênh lệch bên dưới trộn cả thay đổi cấu hình.")
    print(f"\n{m['so_cau']} câu · {m['bo_cau']}")
    print(f"  độ phủ (có ra lệnh)   {_pct(m['do_phu'])}{delta(m['do_phu'], ['do_phu'])}")
    print(f"  đúng cả câu           {_pct(m['dung_ca_cau'])}{delta(m['dung_ca_cau'], ['dung_ca_cau'])}")
    if "pr" in m:
        pr = m["pr"]
        print(f"  precision {_pct(pr['precision']).strip()} · recall {_pct(pr['recall']).strip()}"
              f" · F1 {_pct(pr['f1']).strip()}   (exact match)")

    print("\nCHỈ SỐ CHÍNH — trên TẤT CẢ câu")
    for f in FIELDS:
        if f in m["truong"]:
            print(f"  {f:<8}{_pct(m['truong'][f])}{delta(m['truong'][f], ['truong', f])}")

    print("\nphụ — chỉ trên câu đã ra lệnh (đọc KÈM độ phủ, đừng đứng một mình)")
    print("  " + "  ".join(f"{f} {_pct(m['truong_khi_ra_lenh'][f]).strip()}"
                           for f in FIELDS if f in m["truong_khi_ra_lenh"]))

    if "im_lang" in m:
        s = m["im_lang"]
        print(f"\nCỔNG CHẶN — {s['so_cau']} câu phải im")
        print(f"  có lệnh trong plan   {s['ra_lenh_oan']}  ({_pct(s['ty_le_oan'])})"
              f"{delta(s['ty_le_oan'], ['im_lang', 'ty_le_oan'])}")
        if "gui_xuong_xe" in s:
            print(f"  → THẬT SỰ xuống xe   {s['gui_xuong_xe']}  ({_pct(s['ty_le_gui'])})"
                  f"{delta(s['ty_le_gui'], ['im_lang', 'ty_le_gui'])}")
        if old and s["ty_le_oan"] > (old.get("im_lang") or {}).get("ty_le_oan", 1):
            print("  ⚠ OAN TĂNG SO VỚI MỐC — không đánh đổi lấy độ phủ.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("golden", type=Path)
    ap.add_argument("--negative", type=Path)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--limit", type=int, help="lấy mẫu N câu thay vì chạy hết")
    ap.add_argument("--nguong", type=float, help="ép ngưỡng tầng NLU, để so hai ngưỡng")
    ap.add_argument("--tat-nlu", action="store_true",
                    help="tắt tầng [1b] để đo riêng đóng góp của tầng luật")
    ap.add_argument("--save", type=Path, help="ghi kết quả làm mốc")
    ap.add_argument("--compare", type=Path, help="so với mốc đã ghi")
    args = ap.parse_args()

    global _NGUONG, _TAT_NLU
    _NGUONG = args.nguong
    _TAT_NLU = args.tat_nlu
    m = measure(args.golden, args.negative, args.jobs, args.limit)
    old = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    report(m, old)

    if args.save:
        args.save.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nđã ghi mốc: {_rel(args.save)}")


if __name__ == "__main__":
    main()
