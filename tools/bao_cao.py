"""Gom mọi số đo thành MỘT file để báo cáo, không phải tính tay.

Vì sao cần: số nằm rải ba chỗ — mốc chính trong tests/, kết quả cloud trong
logs/ (đang bị gitignore nên máy khác clone về là mất), luật UC thì phải chạy
tools/check_uc.py mới có. Mỗi lần báo cáo lại đi nhặt và nhân chia bằng tay là
một lần sai được.

    python tools/bao_cao.py                 # in ra màn hình
    python tools/bao_cao.py --ghi           # ghi tests/bao_cao.json + .md
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _doc(duong: Path):
    try:
        return json.loads(duong.read_text(encoding="utf-8"))
    except Exception:
        return None


def _uc() -> dict | None:
    """Chạy check_uc.py lấy số luật UC của BA. Không chạy được thì bỏ qua."""
    try:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_uc.py")],
                           capture_output=True, text=True, timeout=600)
    except Exception:
        return None
    for dong in r.stdout.splitlines():
        if "luật ·" in dong and "đạt" in dong:
            import re
            so = re.findall(r"\d+", dong)
            if len(so) >= 3:
                return {"tong": int(so[0]), "dat": int(so[1]), "truot": int(so[-1]), "dong": dong.strip()}
    return None


def gom() -> dict:
    moc = _doc(ROOT / "tests" / "baseline_qc_nlu.json")
    if moc is None:
        sys.exit("chưa có tests/baseline_qc_nlu.json — chạy tools/score_fields.py --save trước")
    truoc = _doc(ROOT / "tests" / "baseline_qc.json")
    # Mốc đo khi TẮT tầng [1b] — để tách được đóng góp của model trên xe. Không
    # có thì bảng tầng rút về hai dòng edge/cloud như cũ.
    chi_luat = _doc(ROOT / "tests" / "baseline_chi_luat.json")

    # Mốc SẠCH của tầng cloud: đo trên tập QC chưa hề dùng để chỉnh prompt
    # (score_cloud.py --bo-qua). Ưu tiên nó hơn mọi thứ trong logs/, vì số đo
    # trên chính tập đã dùng để soi lỗi bao giờ cũng đẹp hơn thật.
    cloud = None
    sach = _doc(ROOT / "tests" / "baseline_cloud_sach.json")
    if sach:
        dt = sach.get("do_tre_ms") or {}
        cloud = {
            "nguon": "tests/baseline_cloud_sach.json",
            "giu_sach": True,
            "so_cau_edge_bo_tay": sach["so_lan_goi"],
            "cloud_va_duoc": sach["cloud_khi_goi"],
            "do_tre_trung_vi_ms": dt.get("trung_vi"),
            "do_tre_p90_ms": dt.get("p90"),
            "bo_cau": f'{sach["so_cau"]:,} câu QC cần mạng, chưa dùng để chỉnh prompt',
            "truong_khi_goi": sach.get("truong_khi_goi"),
            "ly_do": sach.get("ly_do"),
        }

    for ten in () if cloud else ("do_cloud_500.json", "do_cloud.json"):
        rows = _doc(ROOT / "logs" / ten)
        if not rows:
            continue
        do = [r for r in rows if not r.get("khong_do")]
        if len(do) < 100:          # mẫu quá nhỏ thì không đáng đưa vào báo cáo
            continue
        ms = sorted(r["ms"] for r in do if r.get("goi_cloud"))
        cloud = {
            "nguon": f"logs/{ten}",
            "so_cau_edge_bo_tay": len(do),
            "cloud_va_duoc": round(sum(r["dung_het"] for r in do) / len(do), 4),
            "do_tre_trung_vi_ms": ms[len(ms) // 2] if ms else None,
            "do_tre_p90_ms": ms[int(len(ms) * 0.9)] if ms else None,
        }
        break

    pr = moc.get("pr") or {}
    im = moc.get("im_lang") or {}
    ghep = None
    if cloud:
        ghep = round(moc["dung_ca_cau"] + (1 - moc["do_phu"]) * cloud["cloud_va_duoc"], 4)

    return {
        "khi": datetime.now().isoformat(timespec="seconds"),
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.strip(),
        "bo_cau": {"duong": moc["bo_cau"], "so_cau": moc["so_cau"],
                   "bo_am": im.get("bo_cau"), "so_cau_am": im.get("so_cau")},
        "cau_hinh": moc.get("cau_hinh"),
        "chinh": {
            "dung_ca_cau": moc["dung_ca_cau"],
            "do_phu": moc["do_phu"],
            "precision": pr.get("precision"),
            "recall": pr.get("recall"),
            "f1": pr.get("f1"),
        },
        "truong": moc["truong"],
        "cong_chan": {
            "so_cau": im.get("so_cau"),
            "lenh_that_su_xuong_xe": im.get("gui_xuong_xe"),
            "ty_le": im.get("ty_le_gui"),
        },
        "chi_tang_luat": {"dung_ca_cau": chi_luat["dung_ca_cau"],
                          "do_phu": chi_luat["do_phu"]} if chi_luat else None,
        "cloud": cloud,
        "edge_cong_cloud": ghep,
        "moc_xuat_phat": {"dung_ca_cau": truoc["dung_ca_cau"],
                          "ghi_chu": "trước khi gắn model on-edge"} if truoc else None,
        "luat_uc_cua_ba": _uc(),
        # Lịch sử đo: trước đây chỉ nằm trong commit message, dò lại thì dễ
        # nối nhầm hai lượt khác cỡ mẫu thành một mức tăng không có thật.
        "lich_su_cloud": _doc(ROOT / "tests" / "lich_su_cloud.json"),
    }


def ra_markdown(d: dict) -> str:
    c, t, g = d["chinh"], d["truong"], d["cong_chan"]
    o = ["# AgentCar — số đo\n",
         f"`{d['commit']}` · {d['khi']} · {d['bo_cau']['so_cau']:,} câu "
         f"({d['bo_cau']['duong']})\n"]

    # Số chốt lên ĐẦU. Trước đây báo cáo mở bằng 54,0% của tầng trên xe còn
    # số tầng cloud nằm tít cuối — người đọc lướt hai dòng đầu là lấy nhầm.
    cl0 = d.get("cloud") or {}
    if cl0.get("giu_sach"):
        import math as _m
        n0, p0 = cl0["so_cau_edge_bo_tay"], cl0["cloud_va_duoc"]
        b0 = 1.96 * _m.sqrt(p0 * (1 - p0) / n0) if n0 else 0.0
        o += ["## Số chốt\n",
              "| | | |", "|---|---|---|",
              f"| **tầng cloud** | **{p0:.1%}** ±{b0:.1%} | {n0:,} câu |",
              f"| tầng trên xe | {d['chinh']['dung_ca_cau']:.1%} | "
              f"{d['bo_cau']['so_cau']:,} câu |",
              f"| độ trễ cloud | {cl0['do_tre_trung_vi_ms']:.0f}ms thường · "
              f"{cl0['do_tre_p90_ms']:.0f}ms chậm nhất trong 9/10 lần | hạn 1200ms |", "",
              "**Hai dòng đầu không so với nhau được.** Mỗi câu nói ra đều chạy "
              "qua tầng trên xe trước; chỉ câu nào nó không hiểu mới gửi lên "
              f"cloud. Nên 54,0% là trên tất cả {d['bo_cau']['so_cau']:,} câu, "
              f"còn 77,2% chỉ trên {n0:,} câu khó đã bị đẩy lên.", "",
              "**Vì sao tin được con số cloud:** chúng tôi sửa hệ thống dựa trên "
              "một nửa bộ câu, rồi chấm điểm trên nửa còn lại — nửa mà hệ thống "
              "chưa từng thấy. Hai nửa cho kết quả gần như nhau (77,7% và 77,2%), "
              "nghĩa là nó hiểu thật chứ không phải học thuộc.", "",
              "**Con số 54,0% thì chưa làm bước đó**, nên nhiều khả năng thực tế "
              "thấp hơn. Tầng trên xe do nhóm khác phụ trách.", "",
              "Phần dưới là chi tiết của ba dòng này.", ""]

    o += ["## Tầng trên xe\n",
         "| | |", "|---|---|"]
    xp = d.get("moc_xuat_phat")
    if xp:
        o.append(f"| đúng cả câu | **{c['dung_ca_cau']:.1%}** "
                 f"(xuất phát {xp['dung_ca_cau']:.1%}) |")
    else:
        o.append(f"| đúng cả câu | **{c['dung_ca_cau']:.1%}** |")
    o += [f"| độ phủ | {c['do_phu']:.1%} |",
          f"| precision | {c['precision']:.1%} |",
          f"| recall | {c['recall']:.1%} |",
          f"| F1 | {c['f1']:.1%} |",
          "", "precision/recall tính theo **exact match**: sai một trường là sai cả câu.", ""]
    o += ["## Từng trường\n", "| trường | |", "|---|---|"]
    o += [f"| {k} | {v:.1%} |" for k, v in t.items()]
    o += ["", "## Cổng chặn — câu KHÔNG phải lệnh\n",
          f"**{g['lenh_that_su_xuong_xe']}/{g['so_cau']}** ({g['ty_le']:.1%}) "
          f"câu khiến xe làm gì đó dù lẽ ra phải im.", "",
          "Mẫu lệch nên con số này KHÔNG nằm trong precision ở trên. "
          "Trong xe nó quan trọng hơn: không hiểu thì người ta nói lại, "
          "ra lệnh oan thì cửa kính tự hạ giữa đường.", ""]
    if d.get("cloud"):
        cl, cl_luat = d["cloud"], d.get("chi_tang_luat")
        o += ["## Ba tầng\n",
              "Hai tầng đầu chạy TRÊN XE (gọi chung là edge), tầng ba ra mạng.", "",
              "| tầng | chạy ở đâu | độ trễ | cộng dồn đúng cả câu |",
              "|---|---|---|---|"]
        if cl_luat:
            o += [f"| `[1]` luật + từ điển | trên xe | ~0,5ms | "
                  f"{cl_luat['dung_ca_cau']:.1%} |",
                  f"| `[1b]` model NLU 14,5M tham số | trên xe | ~4ms | "
                  f"**{c['dung_ca_cau']:.1%}** |"]
        else:
            o += [f"| `[1]`+`[1b]` luật + model trên xe | trên xe | dưới 5ms | "
                  f"**{c['dung_ca_cau']:.1%}** |"]
        o += [f"| `[2]` cloud qwen-plus | ra mạng | trung vị "
              f"{cl['do_tre_trung_vi_ms']:.0f}ms · p90 {cl['do_tre_p90_ms']:.0f}ms | "
              f"{d['edge_cong_cloud']:.1%} (ước tính) |", "",
              f"Ô cuối cùng **{d['edge_cong_cloud']:.1%} là PHÉP TÍNH, không phải phép đo**: "
              f"lấy {c['dung_ca_cau']:.1%} của edge cộng {1 - c['do_phu']:.1%} × "
              f"{cl['cloud_va_duoc']:.1%}. Nó áp tỷ lệ vá của cloud — đo trên câu QC "
              "gắn nhãn *cần mạng* — cho toàn bộ phần edge bó tay, trong đó có nhiều "
              "câu gắn *trên xe* chưa từng chạy qua cloud. Số đo thật là "
              f"**{cl['cloud_va_duoc']:.1%}** ở dòng dưới.", "",
              f"Trần của cả hệ thống là {c['dung_ca_cau'] + 1 - c['do_phu']:.1%} "
              f"({c['dung_ca_cau']:.1%} + {1 - c['do_phu']:.1%}) — đạt được khi cloud "
              "đúng 100%. Muốn vượt trần đó thì phải sửa tầng trên xe, không phải "
              "sửa cloud.", ""]
        if cl_luat:
            o += [f"Model trên xe đóng góp **{c['dung_ca_cau'] - cl_luat['dung_ca_cau']:+.1%}** "
                  f"và kéo độ phủ từ {cl_luat['do_phu']:.1%} lên {c['do_phu']:.1%} — "
                  f"tức là ngần ấy câu không phải ra mạng.", ""]
        import math
        n = cl["so_cau_edge_bo_tay"]
        pp = cl["cloud_va_duoc"]
        bien = 1.96 * math.sqrt(pp * (1 - pp) / n) if n else 0.0
        o += [f"Tầng `[2]` chỉ chạy khi hai tầng trên bó tay ({1 - c['do_phu']:.1%} số câu), "
              f"và vá được **{pp:.1%}** trong đó (±{bien:.1%}, n={n:,}).", ""]
        if cl.get("giu_sach"):
            o += ["Con số cloud đo trên tập QC **chưa hề dùng để chỉnh prompt** "
                  f"({cl['bo_cau']}). Đo trên tập đã dùng để soi lỗi thì ra 77,7% — "
                  "chênh 0,5 điểm, nằm trong nhiễu, nên luật là tổng quát chứ "
                  "không phải vá đúng mấy câu đã nhìn.", ""]
        if cl.get("truong_khi_goi"):
            o += ["| trường (chỉ câu đã lên cloud) | |", "|---|---|"]
            o += [f"| {k} | {v:.1%} |" for k, v in cl["truong_khi_goi"].items()]
            o += [""]
        o += ["Đây là độ chính xác **hiểu câu**, so khớp tuyệt đối với nhãn QC, "
              "trên **văn bản đã đúng sẵn**. Chưa có ASR — demo đang mượn của "
              "Chrome — nên sai số nhận dạng tiếng nói chưa nằm trong con số này.", ""]
    ls = d.get("lich_su_cloud")
    if ls:
        cot = ls["cot"]
        o += ["## Tiến triển tầng cloud\n",
              "**Chỉ so hai ô CÙNG CỘT.** Mỗi cột là một bộ câu khác nhau; "
              "nối chéo hai cột ra mức tăng không có thật.", "",
              "| prompt | việc đã làm | mẫu 500 | mẫu 3.600 | tập sạch |",
              "|---|---|---|---|---|"]
        for r in ls["lan_do"]:
            o.append("| `{}` | {} | {} | {} | {} |".format(
                r["prompt_sha"][:7], r["viec"],
                *[f"{r[k]:.1%}" if r.get(k) is not None else "—"
                  for k in ("mau_500", "mau_3600", "tap_sach")]))
        mt = ls["muc_tang_that"]
        o += ["", f"- mẫu 500: {cot['mau_500']}",
              f"- mẫu 3.600: {cot['mau_3600']}",
              f"- tập sạch: {cot['tap_sach']}", "",
              f"Mức tăng đo được: **{mt['tren_mau_500']['tang']:+.1%}** trên mẫu 500, "
              f"**{mt['tren_mau_3600']['tang']:+.1%}** trên mẫu 3.600. "
              f"{mt['canh_bao']}", ""]
    if d.get("luat_uc_cua_ba"):
        u = d["luat_uc_cua_ba"]
        o += ["## Luật UC của BA\n", f"**{u['dat']}/{u['tong']}** đạt.", ""]
    return "\n".join(o)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ghi", action="store_true", help="ghi tests/bao_cao.json và .md")
    a = ap.parse_args()
    d = gom()
    md = ra_markdown(d)
    print(md)
    if a.ghi:
        (ROOT / "tests" / "bao_cao.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (ROOT / "tests" / "bao_cao.md").write_text(md + "\n", encoding="utf-8")
        print("\nđã ghi tests/bao_cao.json và tests/bao_cao.md")


if __name__ == "__main__":
    main()
