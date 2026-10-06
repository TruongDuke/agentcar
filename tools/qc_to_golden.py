"""Chuyển test report của QC thành bộ câu chuẩn chạy được bằng `agentcar eval`.

File QC (VITA-GRAMMAR-API-TESTREPORT) đo một hệ thống KHÁC, nên cột kết quả
(STATUS/ACTUAL_INTENTS) không nói gì về repo này. Thứ dùng được là hai cột đề
bài: VA_SAMPLE (câu người nói) và EXPECTED_INTENTS (đáp án do BA soạn) —
26.787 câu tiếng Việt có nhãn, so với 370 câu golden hiện có.

Schema hai bên gần trùng: 28/28 device khớp, zone khớp 99%, action khớp 88%.
Chỗ lệch được map lại ở ACTION_ALIAS/_mode_action; câu nào không map nổi thì bỏ
và ghi lý do, KHÔNG đoán bừa — golden sai còn tệ hơn golden thiếu.

    python tools/qc_to_golden.py                # ghi tests/golden_qc*.vi.yaml
    python tools/qc_to_golden.py --dry-run      # chỉ in thống kê
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import openpyxl
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # chạy được cả khi chưa cài package
QC_XLSX = ROOT / "test_docs" / "VITA-GRAMMAR-API-TESTREPORT-2509.xlsx"
CAPS = ROOT / "caps" / "vf9.yaml"

# QC gọi tên khác cho cùng một việc. Chỉ map khi chắc chắn cùng ngữ nghĩa.
# ---- SỬA LẠI CHỖ QC GÁN NHÃN SAI ----------------------------------------
# QC là TÀI NGUYÊN, không phải trọng tài. Chỗ nào nó gán sai thì sửa ở đây và ghi
# lý do, thay vì chép nguyên rồi để agent rớt vĩnh viễn dù làm đúng.

# "Hạ đèn viền xuống 98 mức" — QC gán decrease step=98. Đèn viền dải 1..100 nên
# giảm đi 98 nấc là về 1 từ mọi mức: cả loạt 80/85/90/95/98/100 ra cùng kết quả,
# con số người dùng nói thành vô nghĩa. Tiếng Việt đọc là ĐẶT VỀ mức đó.
GIOI_TU_DICH = re.compile(r"\b(xu[ốô]ng|l[êe]n|v[ềe]|c[òo]n|t[ớo]i|đ[ếe]n)\s+(\d+)")

ACTION_ALIAS = {
    ("hvac", "set_temp"): "set_level",
    ("volume", "set_volume"): "set_level",
}
# QC coi mỗi chế độ là một action; repo dùng set_mode + mode.
# Các biến thể "_off" ứng với clear_mode.
MODE_OFF = {"off", "msg_null", "fx_none"}


def _repo_schema() -> tuple[dict, set]:
    """Trả (devices, actions) đọc từ caps — nguồn sự thật của repo."""
    from agentcar.caps import load_caps

    caps = load_caps(CAPS)
    raw = yaml.safe_load(CAPS.read_text(encoding="utf-8"))
    actions: set[str] = set()
    devices: dict[str, dict] = {}
    for name, dev in caps.devices.items():
        eff = set(caps.effective_actions(dev))
        actions |= eff
        rawdev = (raw.get("devices") or {}).get(name) or {}
        devices[name] = {
            "actions": eff,
            "modes": set(rawdev.get("modes") or []),
            "zones": set(rawdev.get("zones") or []),
            "items": set(rawdev.get("items") or {}),
            "units": (dev.value.units if dev.value else {}),
        }
    return devices, actions


def _dich_thanh_muc(say: str, act: str, val, spec) -> bool:
    """Câu này có phải "đặt VỀ mức N" mà QC gán nhầm thành "giảm ĐI N" không.

    Ba điều kiện, thiếu một là không sửa — thà bỏ sót còn hơn sửa oan:
      1. QC gán increase/decrease
      2. có giới từ đích đứng NGAY TRƯỚC con số, và con số đó đúng bằng value
      3. con số nằm trong dải hợp lệ của thiết bị
    Điều kiện 3 giữ "tăng quạt lên 2 nấc" nguyên là increase: 2 nằm trong dải 1..6
    nhưng "lên 2" ở đây... vẫn lọt. Nên đây là heuristic, không phải luật — xem
    ghi chú `sua_lai` trong caps/tu_vung.yaml.
    """
    if act not in ("increase", "decrease") or not isinstance(val, (int, float)):
        return False
    m = GIOI_TU_DICH.search(say or "")
    if not m or int(m.group(2)) != val:
        return False
    units = spec.get("units") or {}
    return any(u.lo <= val <= u.hi for u in units.values())


def _map_intent(intent: dict, devices: dict, actions: set,
                say: str = "") -> tuple[Optional[dict], str]:
    """QC intent -> expect dict của repo. Trả (kết quả, lý do bỏ)."""
    dev = intent.get("device")
    if dev not in devices:
        return None, f"device lạ: {dev}"
    spec = devices[dev]

    act = intent.get("action")
    if not act:
        return None, "thiếu action"
    act = ACTION_ALIAS.get((dev, act), act)

    out: dict[str, Any] = {"device": dev}
    if act in spec["modes"]:
        out.update(action="set_mode", mode=act)
    elif act in MODE_OFF or (act.endswith("_off") and act[:-4] in spec["modes"]):
        out["action"] = "clear_mode"
    elif act in spec["actions"] or act in actions:
        out["action"] = act
    else:
        return None, f"action chưa có: {dev}.{act}"

    zone = intent.get("zone")
    if zone not in (None, ""):
        if zone not in spec["zones"]:
            return None, f"zone chưa có: {dev}.{zone}"
        out["zone"] = zone

    # QC nhét cả mức số lẫn tên mục vào chung cột `value`; repo tách `value` / `item`.
    val = intent.get("value")
    if isinstance(val, bool) or val is None:
        return out, ""
    if isinstance(val, (int, float)):
        # QC để LƯỢNG ĐIỀU CHỈNH vào `value`; repo tách riêng `step` cho lệnh tương
        # đối (value = mức đích, step = cộng/trừ bao nhiêu). Không map thì mọi câu
        # "tăng 2 độ" bị chấm sai dù agent làm đúng — 37% số câu có value là tương đối.
        if _dich_thanh_muc(say, act, val, spec):
            out["action"], out["value"] = "set_level", val
            return out, ""
        out["step" if act in ("increase", "decrease") else "value"] = val
        return out, ""
    if not isinstance(val, str):
        return None, f"value kiểu lạ: {type(val).__name__}"

    raw = val.strip()
    if raw.lower() in ("null", "none", ""):
        return out, ""
    if raw.endswith("%"):
        # Trước đây bỏ vì "tăng 20%" mơ hồ: thêm 20% hay đặt tới 20%? Giờ hết mơ hồ
        # — chính ACTION quyết: increase/decrease thì 20 là bước (`step`), còn lại
        # là mức đích (`value`). Cùng quy ước với nhánh số thuần ở trên.
        so = raw[:-1].strip()
        if so.lstrip("-").replace(".", "", 1).isdigit():
            n = float(so) if "." in so else int(so)
            out["step" if act in ("increase", "decrease") else "value"] = n
            return out, ""
        return None, f"value kèm % không đọc được: {val!r}"
    if raw.lstrip("-").replace(".", "", 1).isdigit():
        # Nhánh CHUỖI SỐ THUẦN — QC để "50" dạng chuỗi, không phải số, không có %.
        # Trước đây gán thẳng `value`, KHÔNG kiểm increase/decrease như hai nhánh
        # trên, nên 161 câu screen_brightness kiểu "tăng độ sáng thêm 50%" mang
        # nhãn value trong khi 2.393 câu tương tự mang step. Bộ đo vì thế chấm
        # agent sai dù agent làm đúng.
        n = float(raw) if "." in raw else int(raw)
        out["step" if act in ("increase", "decrease") else "value"] = n
        return out, ""
    if raw in spec["items"]:
        out["item"] = raw
        return out, ""
    return None, f"item chưa có: {dev}.{raw}"


def _rows(path: Path):
    """Sinh (câu nói, expected_intents) từ mọi sheet, bỏ sheet Summary."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        if ws.title == "Summary":
            continue
        hdr: dict[str, int] = {}
        blank = 0
        for i, row in enumerate(ws.iter_rows(values_only=True), 1):
            if i == 1:
                hdr = {v: j for j, v in enumerate(row) if v}
                continue
            if not any(row):
                blank += 1
                if blank > 50:      # vài sheet khai max_row = 1.048.571
                    break
                continue
            blank = 0
            get = lambda k: row[hdr[k]] if k in hdr and hdr[k] < len(row) else None
            say = get("VA_SAMPLE")
            if not say or not str(say).strip():
                continue
            try:
                exp = json.loads(str(get("EXPECTED_INTENTS")))
            except Exception:
                continue
            if not isinstance(exp, list):
                continue
            # Cột Offline của QC nói câu này XỬ LÝ ĐƯỢC TRÊN XE hay cần mạng.
            # 17.832 dòng đánh "Offline", 8.953 dòng để trống = cần mạng. Mang
            # nhãn này sang golden để đo riêng từng tầng mà khỏi phải suy ra
            # bằng cách chạy edge rồi xem nó trượt câu nào — suy thì tập đo đổi
            # theo mỗi lần edge khá lên, so hai lần đo với nhau thành vô nghĩa.
            tren_xe = str(get("Offline") or "").strip().lower() == "offline"
            yield ws.title, str(say).strip(), exp, tren_xe


def _co_phu_dinh(say: str) -> bool:
    """Câu có từ phủ định không — dùng để tách bộ 'phải im' làm hai.

    Từ điển phủ định lấy thẳng từ matcher, để hai bên không trôi khỏi nhau.
    """
    from agentcar.lexicon import normalize
    from agentcar.match import NEGATION

    toks = normalize(say, keep_diacritics=True).split()
    return any(" ".join(toks[i:i + 2]) in NEGATION or toks[i] in NEGATION
               for i in range(len(toks)))


def convert(path: Path = QC_XLSX) -> tuple[list, list, list, collections.Counter]:
    devices, actions = _repo_schema()
    positives: list[dict] = []
    negatives: list[str] = []
    tranhchap: list[dict] = []
    skipped: collections.Counter = collections.Counter()
    seen: set[str] = set()

    for sheet, say, exp, tren_xe in _rows(path):
        if say in seen:
            skipped["câu trùng"] += 1
            continue
        seen.add(say)

        if exp == []:
            # QC ghi [] cho câu này, NHƯNG với câu phủ định thì chính QC lại ghi
            # lệnh ở 684 dòng khác (xem defrost D268 vs D272, foglight D55 vs D58).
            # Chốt 29/09 theo QC = theo phe ra lệnh, nên những dòng [] phủ định
            # không dùng để chấm được nữa — tách ra thành danh sách gửi QC.
            if _co_phu_dinh(say):
                tranhchap.append({"sheet": sheet, "say": say})
            else:
                negatives.append(say)
            continue

        mapped, why = [], ""
        for intent in exp:
            if not isinstance(intent, dict):
                why = "intent không phải object"
                break
            one, why = _map_intent(intent, devices, actions, say)
            if one is None:
                break
            mapped.append(one)
        if why or not mapped:
            skipped[why or "rỗng sau khi map"] += 1
            continue

        # `tren_xe` = QC nói câu này xử lý được trên xe. Giữ NGOÀI `expect` vì
        # nó không phải thứ đem chấm — nó là nhãn để chọn tập đo.
        ca = {"say": say, "tren_xe": tren_xe}
        if len(mapped) == 1:
            ca["expect"] = {"verdict": "OK", **mapped[0]}
        else:
            ca["expect"] = {"verdict": "OK", "commands": mapped}
        positives.append(ca)

    return positives, negatives, tranhchap, skipped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", type=Path, default=QC_XLSX)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pos, neg, tranhchap, skipped = convert(args.xlsx)
    total = len(pos) + len(neg) + len(tranhchap) + sum(skipped.values())
    print(f"đọc {total} câu")
    print(f"  ra lệnh          {len(pos)}")
    print(f"  phải im          {len(neg)}")
    print(f"  tranh chấp       {len(tranhchap)}   (phủ định — QC tự mâu thuẫn, KHÔNG chấm)")
    print(f"  bỏ               {sum(skipped.values())}")
    for why, n in skipped.most_common(20):
        print(f"      {n:6d}  {why}")

    if args.dry_run:
        return

    head = ("# SINH TỰ ĐỘNG bởi tools/qc_to_golden.py — đừng sửa tay.\n"
            "# Nguồn: test_docs/VITA-GRAMMAR-API-TESTREPORT-2509.xlsx (cột VA_SAMPLE + EXPECTED_INTENTS).\n"
            "# Đáp án do BA soạn cho hệ S6; schema đã map sang caps/vf9.yaml.\n\n")
    p = ROOT / "tests" / "golden_qc.vi.yaml"
    p.write_text(head + yaml.safe_dump(pos, allow_unicode=True, sort_keys=False, width=200),
                 encoding="utf-8")
    n = ROOT / "tests" / "golden_qc_negative.vi.yaml"
    n.write_text(head + "# CHỈ giữ câu 'giữ nguyên đi, đừng đụng vào'. Câu PHỦ ĐỊNH đã tách sang\n"
                 "# golden_qc_tranhchap.vi.yaml vì QC ghi hai đáp án ngược nhau cho cùng kiểu câu.\n\n"
                 + yaml.safe_dump(neg, allow_unicode=True, sort_keys=False, width=200),
                 encoding="utf-8")
    t = ROOT / "tests" / "golden_qc_tranhchap.vi.yaml"
    t.write_text(
        "# KHÔNG PHẢI BỘ TEST — danh sách gửi QC để chốt, sinh bởi tools/qc_to_golden.py.\n"
        "#\n"
        "# Những câu PHỦ ĐỊNH mà QC ghi EXPECTED_INTENTS = [] (không làm gì). Nhưng với\n"
        "# cùng kiểu câu, QC lại ghi có lệnh ở 684 dòng khác:\n"
        "#     defrost  D268 \"Đừng bật sấy kính nha\"         -> defrost.turn_off\n"
        "#     defrost  D272 \"Đừng bật sấy kính lái lên nhé\" -> []\n"
        "#     foglight D55  \"Đừng tắt đèn sương mù.\"        -> fog_light.turn_on\n"
        "#     foglight D58  \"Không cần tắt đèn sương mù đâu.\" -> []\n"
        "#\n"
        "# Chốt 29/09: theo QC = theo phe ra lệnh. Nên những dòng dưới đây KHÔNG dùng\n"
        "# chấm điểm — chấm thì agent chắc chắn rớt, mà rớt theo đáp án đã bị bác bỏ.\n\n"
        + yaml.safe_dump(tranhchap, allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8")
    print(f"ghi {_rel(t) if False else t.relative_to(ROOT)}  ({len(tranhchap)} câu, không chấm)")
    print(f"\nghi {p.relative_to(ROOT)}  ({p.stat().st_size/1e6:.1f} MB)")
    print(f"ghi {n.relative_to(ROOT)}  ({n.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
