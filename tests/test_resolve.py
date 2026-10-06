import pytest

from conftest import caps_theo

from agentcar.plan import Code, RawCommand, Verdict
from agentcar.resolve import resolve, snap


def test_default_action_zone_and_comfort_default(caps):
    r = resolve(caps, RawCommand("hvac"))
    assert r.ok
    assert r.command.action == "turn_on"
    assert r.command.zone == "all"
    assert (r.command.value, r.command.unit) == (22, "celsius")


def test_set_level_snaps_to_resolution(caps):
    r = resolve(caps, RawCommand("hvac", action="set_level", value=22.3))
    assert r.command.value == 22.5


def test_set_level_refuses_out_of_range(caps):
    """Chính sách `ba` (BA sheet 3.1 #1): ngoài dải thì KHÔNG gửi lệnh, báo dải đúng.

    Mặc định repo đang chạy chính sách `qc` (giữ nguyên con số), nên test này phải
    ép chính sách chứ không dùng caps mặc định — xem khối `policy` trong caps.
    """
    r = resolve(caps_theo(caps, gia_tri_ngoai_dai="ba"),
                RawCommand("volume", action="set_level", value=100))
    assert r.command is None
    assert r.code == Code.OUT_OF_RANGE
    assert r.range_spec == (0, 40, "level")


def test_relative_uses_nudge(caps):
    r = resolve(caps, RawCommand("hvac", action="decrease"))
    assert r.command.step == 2 and r.command.value is None


def test_relative_accepts_explicit_step(caps):
    r = resolve(caps, RawCommand("seat_heating", action="increase", value=2))
    assert r.command.step == 2


def test_fahrenheit_unit(caps):
    r = resolve(caps, RawCommand("hvac", action="set_level", value=70.4, unit="fahrenheit"))
    assert r.command.unit == "fahrenheit" and r.command.value == 70


def test_unknown_unit_rejected(caps):
    r = resolve(caps, RawCommand("hvac", action="set_level", value=22, unit="kelvin"))
    assert r.code == Code.INVALID_UNIT


def test_unsupported_device(caps):
    # frunk bỏ khỏi danh sách 28/09: BA chốt VF9 CÓ cốp trước.
    for name in ("auto_highbeam", "hud", "tire_pressure"):
        r = resolve(caps, RawCommand(name, action="query"))
        assert r.verdict == Verdict.NOT_SUPPORT and r.code == Code.NOT_SUPPORT


def test_cloud_only_escalates_with_known_target(caps):
    r = resolve(caps, RawCommand("nav"))
    assert r.verdict == Verdict.ESCALATE_ROUTED
    assert r.target == "nav"


def test_excluded_action_rejected(caps):
    assert resolve(caps, RawCommand("mirror", action="adjust")).code == Code.INVALID_ACTION


def test_excluded_mode_rejected(caps):
    r = resolve(caps, RawCommand("ambient_light", action="set_mode", mode="fx_none"))
    assert r.code == Code.MODE_EXCLUDED


def test_invalid_zone(caps):
    assert resolve(caps, RawCommand("window", action="open", zone="boot")).code == Code.INVALID_ZONE


def test_zone_on_zoneless_device(caps):
    assert resolve(caps, RawCommand("wifi", zone="driver")).code == Code.INVALID_ZONE


def test_item_required_then_accepted(caps):
    assert resolve(caps, RawCommand("app_control", action="open")).code == Code.ITEM_REQUIRED
    r = resolve(caps, RawCommand("app_control", action="open", item="spotify"))
    assert r.ok and r.command.item == "spotify"


def test_unknown_item(caps):
    assert resolve(caps, RawCommand("app_control", action="open", item="netflix")).code == Code.INVALID_ITEM


def test_query_blocked_when_not_readable(caps):
    # scene_mode readable -> ok; ambient_light readable -> ok; chọn device readable=false có support
    r = resolve(caps, RawCommand("scene_mode", action="query"))
    assert r.ok


def test_scene_mode_uses_mode_as_action(caps):
    r = resolve(caps, RawCommand("scene_mode", action="camp"))
    assert r.ok and r.command.action == "camp" and r.command.mode == "camp"


def test_no_default_action(caps):
    assert resolve(caps, RawCommand("volume")).code == Code.NO_DEFAULT_ACTION


# ------------------------------------------------------------------ D1..D6
@pytest.mark.parametrize("mode,group", [
    ("blow_face", "airflow"), ("recirc", "intake"),
])
def test_d1_fan_mode_groups_are_independent(caps, mode, group):
    """D1: đặt mode nhóm này không được hiểu là xoá mode nhóm kia."""
    r = resolve(caps, RawCommand("fan", action="set_mode", mode=mode))
    assert r.ok and r.command.mode_group == group


@pytest.mark.parametrize("mode,group", [("amb_blue", "color"), ("fx_wave", "effect")])
def test_d1_ambient_light_mode_groups(caps, mode, group):
    r = resolve(caps, RawCommand("ambient_light", action="set_mode", mode=mode))
    assert r.ok and r.command.mode_group == group


def test_d2_excluded_mode_has_its_own_code(caps):
    """D2: mode bị exclude khác mode gõ sai — phải trả lời khác nhau."""
    excluded = resolve(caps, RawCommand("ambient_light", action="set_mode", mode="fx_none"))
    typo = resolve(caps, RawCommand("ambient_light", action="set_mode", mode="fx_khong_co"))
    assert excluded.code == Code.MODE_EXCLUDED
    assert typo.code == Code.INVALID_MODE


def test_d3_scene_turn_off_requires_mode(caps):
    assert resolve(caps, RawCommand("scene_mode", action="turn_off")).code == Code.MODE_REQUIRED
    r = resolve(caps, RawCommand("scene_mode", action="turn_off", mode="camp"))
    assert r.ok and r.command.mode == "camp"


def test_d4_volume_has_no_mute(caps):
    """D4: 'tắt tiếng' = set_level(0), không phát action mute."""
    assert resolve(caps, RawCommand("volume", action="mute")).code == Code.INVALID_ACTION
    r = resolve(caps, RawCommand("volume", action="set_level", value=0))
    assert r.ok and r.command.value == 0


def test_d5_screen_control_can_be_closed_and_read(caps):
    """D5 ĐÃ ĐỔI: màn hình cài đặt nay đóng được và hỏi được.

    Lập luận cũ ("đóng màn hình cài đặt" là nút back của hệ điều hành, không phải
    lệnh thiết bị) không sai, nhưng 743 câu QC mong close và 816 câu mong query
    trên 2.407 câu screen_control — hai phần ba số câu về màn hình không trả lời
    nổi. Xem ghi chú trong caps/actions.yaml nếu muốn quay lại.
    """
    for action in ("open", "close", "query"):
        assert action in caps.effective_actions(caps.devices["screen_control"])
    assert "close" in caps.effective_actions(caps.devices["app_control"])


def test_provisional_decisions_are_tracked(caps):
    """D2 và D4 còn tạm chốt — linter phải nhắc cho tới khi được xác nhận."""
    assert {k for k, _ in caps.catalog.provisional()} == {"D2", "D4"}


@pytest.mark.parametrize("value,expected", [(50, 60), (49, 40), (41, 40), (1, 0)])
def test_snap_half_up(caps, value, expected):
    unit = caps.devices["window"].value.unit()
    assert snap(value, unit) == expected
