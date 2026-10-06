"""Phân loại lý do tầng edge trượt. Thuần tất định, chưa đổi luồng."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.caps import load_caps
from agentcar.lexicon import load_lexicon
from agentcar.match import Matcher
from agentcar.triage import Escalation, classify

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
MATCHER = Matcher(CAPS, load_lexicon(CAPS))


def label(text: str, previous: str | None = None) -> str:
    return classify(MATCHER.match(text, previous_device=previous))


@pytest.mark.parametrize("text,expected", [
    ("bật điều hòa", Escalation.NONE),
    ("bật sưởi ghế lái mức 2", Escalation.NONE),
    ("mở cửa sổ trời khi nào tới nhà", Escalation.NOT_NOW),
    ("5 phút nữa bật điều hòa", Escalation.NOT_NOW),
    ("bật", Escalation.DEVICE),
    ("tắt đi", Escalation.DEVICE),
    ("nóng quá", Escalation.OFF_DOMAIN),
    ("hôm nay trời đẹp quá", Escalation.OFF_DOMAIN),
])
def test_labels(text, expected):
    assert label(text) == expected


def test_inheritance_changes_the_label():
    """'giảm 2 độ' đứng một mình là vô nghĩa, nhưng sau 'bật điều hòa' thì chạy được."""
    assert label("giảm 2 độ") != Escalation.NONE
    assert label("giảm 2 độ", previous="hvac") == Escalation.NONE


def test_conditional_beats_device_mention():
    """Câu hẹn giờ có nhắc thiết bị vẫn phải là NOT_NOW — tuyệt đối không chạy."""
    assert label("mở cửa sổ trời khi nào tới nhà") == Escalation.NOT_NOW


def test_off_domain_is_not_a_verdict():
    """OFF_DOMAIN chỉ là 'không có tín hiệu nào của xe', KHÔNG phải 'ngoài phạm vi'.

    'nóng quá' và 'hôm nay trời đẹp quá' cùng nhãn này nhưng một cái là lệnh điều
    khiển, một cái là tán gẫu — chỉ model phân biệt được. Vì vậy lớp này vẫn phải
    gọi cloud, không được tự trả lời tại chỗ.
    """
    assert label("nóng quá") == label("hôm nay trời đẹp quá") == Escalation.OFF_DOMAIN
