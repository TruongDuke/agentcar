"""Chấm repo theo LUẬT PARSER của BA (Capability sheet 3.1 + 3.2).

BA không chỉ nói "phải hiểu câu này", mà nói rõ phải XỬ LÝ THẾ NÀO:

    EXECUTE  gửi lệnh xuống xe
    CONFIRM  không gửi, hỏi lại xác nhận
    SUGGEST  không gửi, báo không hỗ trợ + liệt kê vùng/range hợp lệ
    INFORM   không gửi, chỉ thông báo trạng thái hiện tại

Bộ golden thường chỉ kiểm "ra lệnh gì", nên không phân biệt được CONFIRM với
SUGGEST với INFORM — cả ba đều "không ra lệnh". Script này chấm đúng bốn loại đó.

    python tools/check_uc.py
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Mã lỗi của repo -> loại xử lý BA gọi tên.
SUGGEST_CODES = {"VA_INVALID_ZONE", "VA_NOT_SUPPORT", "VA_INVALID_ITEM", "VA_INVALID_MODE",
                 "VA_MODE_EXCLUDED", "VA_INVALID_ACTION", "VA_INVALID_UNIT", "VA_NOT_READABLE",
                 "VA_OUT_OF_RANGE"}
ASK_CODES = {"VA_ASK", "VA_VALUE_REQUIRED", "VA_MODE_REQUIRED", "VA_ITEM_REQUIRED",
             "VA_DEVICE_REQUIRED"}
BLIND_CODES = {"VA_ESCALATE_UNKNOWN", "VA_ESCALATE_ROUTED", "VA_TOO_SHORT",
               "VA_VAGUE_REFERENCE", "VA_UNKNOWN_DEVICE", "VA_NO_DEFAULT_ACTION"}

# Luật BA mà repo CỐ Ý không theo khi khối `policy` trong caps để "qc". Trượt ở
# đây là quyết định nghiệm thu, không phải thiếu năng lực — phải nói ra, nếu không
# ai đọc "63/71" cũng tưởng còn 8 việc phải làm.
THEO_CHINH_SACH = {
    "N1": "gia_tri_ngoai_dai", "N15": "gia_tri_ngoai_dai", "N16": "gia_tri_ngoai_dai",
    "N12": "buoc_khong_duong", "N12b": "buoc_khong_duong",
    "N13": "buoc_khong_duong", "N13b": "buoc_khong_duong",
    "N14": "buoc_khong_duong",
}


def classify(turn) -> str:
    """Repo đã làm gì, quy về từ vựng của BA.

    Đọc thẳng turn.results chứ không dùng _actual(): _actual liệt kê mọi command
    kể cả cái đã bị chặn. Lệnh trùng trạng thái hiện tại (`da_dung`) KHÔNG được
    gửi xuống xe — đó đúng là INFORM của BA, không phải EXECUTE.
    """
    sent = [r for r in turn.results
            if r.ok and r.command is not None
            and r.command.action != "query" and not r.da_dung and not r.cham_bien
            and not r.hoi_vung]
    if sent:
        return "EXECUTE"
    # hoi_vung: không gửi lệnh, hỏi lại vùng rồi mới chạy — CONFIRM của BA.
    if any(r.hoi_vung for r in turn.results):
        return "CONFIRM"
    # da_dung = trùng trạng thái; cham_bien = lệnh tương đối khi đã ở min/max.
    # Cả hai đều KHÔNG gửi lệnh, chỉ nói ra trạng thái — đúng INFORM của BA.
    if any(r.da_dung or r.cham_bien for r in turn.results):
        return "INFORM"
    if any(r.command is not None and r.command.action == "query" for r in turn.results):
        return "INFORM"
    first = turn.results[0] if turn.results else None
    got = {"code": first.code if first else None}
    code = got.get("code") or ""
    if code in ("VA_NEED_CONFIRM", "VA_ZONE_AMBIGUOUS"):
        return "CONFIRM"
    if code in SUGGEST_CODES:
        return "SUGGEST"
    if code == "VA_SAFETY_DENY":
        return "SUGGEST"          # cũng là "không gửi + nói lý do"
    if code in ASK_CODES:
        return "HỎI LẠI"          # gần CONFIRM nhưng hỏi thiếu slot, không phải xác nhận
    if code in BLIND_CODES or not code:
        return "KHÔNG HIỂU"
    if code in ("VA_REPLY", "VA_NO_PREVIOUS_VALUE"):
        return "INFORM"
    return f"?{code}"


def main() -> None:
    from agentcar.agent import Agent
    from agentcar.caps import load_caps
    from agentcar.config import LLMSettings
    from agentcar.evaluate import _actual

    caps = load_caps(ROOT / "caps" / "vf9.yaml")
    cases = yaml.safe_load((ROOT / "tests" / "uc_parser.vi.yaml").read_text(encoding="utf-8"))

    tally: collections.Counter = collections.Counter()
    bad: list[tuple] = []
    print(f"{'luật':<6}{'BA cần':<10}{'repo làm':<14}{'':<3}{'câu'}")
    print("-" * 96)
    for c in cases:
        agent = Agent(caps, llm_settings=LLMSettings())
        for prior in c.get("context") or []:
            agent.handle(prior)
        turn = agent.handle(c["say"])
        got = _actual(turn)
        mine = classify(turn)
        want = c["can"]
        ok = mine in want.split("+")
        tally[(want, mine)] += 1
        tally[("__", "đạt" if ok else "trượt")] += 1
        print(f"{c['id']:<6}{want:<10}{mine:<14}{'✓' if ok else '✗':<3}{c['say'][:52]}")
        if not ok:
            bad.append((c["id"], want, mine, c["say"], got.get("code"), got.get("tts", "")[:60]))

    ok, no = tally[("__", "đạt")], tally[("__", "trượt")]
    do_chinh_sach = [r for r, *_ in bad
                     if caps.policy.get(THEO_CHINH_SACH.get(r, ""), "qc") == "qc"
                     and r in THEO_CHINH_SACH]
    print(f"\n{ok + no} luật · đạt {ok} ({ok / (ok + no):.1%}) · trượt {no}")
    if do_chinh_sach:
        print(f"   trong đó {len(do_chinh_sach)} luật trượt DO CHÍNH SÁCH (caps đang theo QC, "
              f"không theo BA): {', '.join(do_chinh_sach)}")
        print(f"   thiếu năng lực thật: {no - len(do_chinh_sach)} luật")
    print()

    print("MA TRẬN  (BA cần → repo làm)")
    per: dict = collections.defaultdict(collections.Counter)
    for (w, m), n in tally.items():
        if w != "__":
            per[w][m] += n
    for want, got_c in sorted(per.items()):
        tot = sum(got_c.values())
        detail = "  ".join(f"{m}:{n}" for m, n in got_c.most_common())
        print(f"  {want:<16}(n={tot:<3}) {detail}")

    print("\nTRƯỢT — chi tiết")
    for rid, want, mine, say, code, tts in bad:
        print(f"  [{rid}] cần {want}, được {mine}   « {say} »")
        print(f"        code={code}  tts={tts!r}")


if __name__ == "__main__":
    main()
