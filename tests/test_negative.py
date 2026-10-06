"""Độ CHÍNH XÁC: câu không phải lệnh thì tuyệt đối không được ra lệnh.

144 câu golden chỉ đo được độ PHỦ ("câu này phải ra lệnh gì"). Trong xe, ra lệnh
oan tệ hơn không hiểu nhiều: không hiểu thì người ta nói lại, còn ra lệnh oan thì
cửa kính tự hạ giữa đường.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.caps import load_caps
from agentcar.evaluate import load_cases, run_case

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
CASES = load_cases(ROOT / "tests" / "golden_negative.vi.yaml")


# Tầng [1b] (model NLU) ra lệnh oan ở hai câu này. Ngưỡng tin cậy KHÔNG cứu được:
# "mo cho de do phia truoc" model chấm 1.000 (sai) trong khi "cho interior light
# hoạt động đi" chỉ 0.875 (đúng) — nâng ngưỡng là mất câu đúng, giữ câu sai.
# Đây là lỗi model, phải sửa bằng dữ liệu huấn luyện chứ không bằng hiệu chỉnh.
# strict=True: hôm nào model sửa xong thì test này ĐỎ để có người xoá dòng này đi.
NLU_RA_LENH_OAN = {
    "trời xanh mây trắng",                             # -> volume.query
    "mo cho de do phia truoc",                         # -> fan.turn_on
    "đường Nguyễn Trãi có tắc không",                  # -> volume.query
    "cái chỗ để đồ phía trước ấy, mở nó ra giùm tôi",  # -> sunroof.open
}


@pytest.mark.parametrize("case", CASES, ids=[c["say"] for c in CASES])
def test_says_nothing_and_does_nothing(case, request):
    if case["say"] in NLU_RA_LENH_OAN:
        request.node.add_marker(pytest.mark.xfail(strict=True, reason="tầng [1b] ra lệnh oan"))
    result = run_case(CAPS, case)
    assert result.passed, "; ".join(result.diffs)


def test_the_set_is_big_enough_to_mean_something():
    """7 câu thì là ví dụ, không phải thước đo."""
    assert len(CASES) >= 60


def test_mac_ke_swallows_no_real_command():
    """MAC_KE chặn hẳn lệnh, kể cả tầng [1b] — nên phải tuyệt đối không nổ oan.

    Đây là điều kiện để nó được quyền phủ quyết model. M11 không có tính chất này
    (nổ trên 49,3% số câu tầng luật bỏ sót) nên không được dùng làm cổng. Ai thêm
    dấu hiệu mới vào MAC_KE phải đo lại ở đây, đừng đoán.
    """
    from agentcar.lexicon import load_lexicon
    from agentcar.match import Matcher
    from agentcar.reasoning import load_rules

    matcher = Matcher(CAPS, load_lexicon(CAPS), vague=load_rules().vague)
    cases = load_cases(ROOT / "tests" / "golden_qc.vi.yaml")
    nuot = [c["say"] for c in cases
            if (c.get("expect") or {}).get("device") and matcher.match(c["say"]).mac_ke]
    assert not nuot, f"{len(nuot)} câu đáng ra lệnh bị nuốt, ví dụ: {nuot[:3]}"
