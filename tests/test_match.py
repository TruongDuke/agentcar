"""Chạy bộ câu chuẩn tiếng Việt qua toàn bộ pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.caps import load_caps
from agentcar.evaluate import load_cases, run_case
from agentcar.match import Matcher
from agentcar.lexicon import load_lexicon

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
CASES = load_cases(ROOT / "tests" / "golden.vi.yaml")


@pytest.mark.parametrize("case", CASES, ids=[c["say"] for c in CASES])
def test_golden(case):
    result = run_case(CAPS, case)
    assert result.passed, "; ".join(result.diffs)


def test_longest_match_beats_substring():
    """'độ sáng màn hình' phải thắng 'màn hình'."""
    m = Matcher(CAPS, load_lexicon(CAPS))
    cmds = m.match("độ sáng màn hình 80 phần trăm").commands
    assert cmds[0].device == "screen_brightness"


def test_connector_inside_alias_is_not_a_split():
    """M4: 'thổi mặt và chân' là một mode, không phải hai lệnh."""
    m = Matcher(CAPS, load_lexicon(CAPS))
    result = m.match("thổi mặt và chân")
    assert len(result.commands) == 1 and result.commands[0].mode == "blow_face_feet"


@pytest.mark.parametrize("text", ["bật điều hòa", "bật điều hoà", "bat dieu hoa"])
def test_three_matching_tiers(text):
    """Có dấu, khác quy ước đặt dấu, và mất dấu hoàn toàn — cả ba đều ra hvac."""
    m = Matcher(CAPS, load_lexicon(CAPS))
    assert m.match(text).commands[0].device == "hvac"


def test_stripped_tier_only_helps_undiacriticized_input():
    """'đó' KHÔNG được khớp thành 'đỏ' — chữ có dấu mà khác dấu là chữ khác.

    Chỉ khi người nói/ASR bỏ dấu hẳn thì mới hạ chuẩn xuống tầng bỏ dấu.
    """
    m = Matcher(CAPS, load_lexicon(CAPS))
    assert not m.match("làm gì đó đi").commands
    assert m.match("den vien mau do").commands[0].mode == "amb_red"


def test_no_device_no_command():
    """Không suy được thiết bị thì không bịa ra lệnh."""
    m = Matcher(CAPS, load_lexicon(CAPS))
    assert not m.match("hôm nay trời đẹp quá").commands


def test_zone_infers_device_only_when_unique():
    """M18. 'phía trước' thuộc fan, defrost và fog_light — không suy ra được ai.

    Trước đây chỉ MODE bị kiểm tra tính duy nhất, ZONE thì không, nên thứ tự chèn
    alias quyết định: "mở chỗ để đồ phía trước" (người ta xin mở cốp trước) ra
    thành bật quạt. Có tên thiết bị thì vùng vẫn phải chạy bình thường.
    """
    m = Matcher(CAPS, load_lexicon(CAPS))
    assert not m.match("mở chỗ để đồ phía trước").commands
    assert not m.match("bật phía sau").commands
    assert m.match("sấy kính phía trước").commands[0].device == "defrost"
    assert m.match("bật quạt phía trước").commands[0].device == "fan"


def test_soft_correction_needs_something_concrete_after_it():
    """M19. "không" trong "cho không gian" không phải người nói tự sửa ý.

    Chữ sửa ý lẻ chỉ tính khi ngay sau nó là alias hoặc số — thứ cụ thể thay cho ý
    cũ. Trước đây "mở ứng dụng nhạc lên cho không gian thêm hứng khởi" bị cắt mất
    nửa đầu, nên "nhạc" rơi về nghĩa kênh âm lượng và agent đi tăng âm lượng.
    """
    m = Matcher(CAPS, load_lexicon(CAPS))
    cmd = m.match("mở ứng dụng nhạc lên giúp mình cho không gian thêm hứng khởi").commands
    assert len(cmd) == 1
    assert (cmd[0].device, cmd[0].item) == ("app_control", "music")
    # sửa ý thật thì vẫn phải cắt
    assert m.match("mở cửa kính thôi đóng lại").commands[0].action == "close"
    assert m.match("bật điều hòa 24 độ à không 22 thôi").commands[0].value == 22


def test_weak_verb_needs_a_number():
    """M20. "để" chỉ là lệnh khi có số ngay sau.

    "chỗ để đồ phía trước" (xin mở cốp trước) từng ra lệnh BẬT QUẠT: "để" khiến
    tập thiết bị của vùng 'front' hẹp lại còn mỗi fan — defrost và fog_light không
    set_level được — nên qua lọt cả M18.
    """
    m = Matcher(CAPS, load_lexicon(CAPS))
    hit = m.match("điều hoà để 22 độ").commands[0]
    assert (hit.device, hit.action, hit.value) == ("hvac", "set_level", 22)
    assert m.match("sưởi ghế để mức 3").commands[0].value == 3
    assert not m.match("cái chỗ để đồ phía trước ấy, mở nó ra giùm tôi").commands
    assert not m.match("để mình xem đã").commands
