"""Test từ điển — coverage phải luôn đầy, và bẫy bỏ dấu phải được chặn."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentcar.caps import load_caps
from agentcar.lexicon import DEVICE, ITEM, MODE, ZONE, coverage, load_lexicon, normalize

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
LEX = load_lexicon(CAPS)
LEX_PATH = ROOT / "caps" / "lexicon.vi.yaml"


@pytest.mark.parametrize(
    "text,stripped,accented",
    [
        ("Điều Hoà!", "dieu hoa", "điều hoà"),
        ("  ĐÈN   VIỀN  ", "den vien", "đèn viền"),
        ("Ghế sau bên trái", "ghe sau ben trai", "ghế sau bên trái"),
        # "%" tách khỏi số: dính liền thì "100%" không phải số mà cũng không
        # phải alias đơn vị, nên "hạ kính 50%" mất giá trị và mở toang cửa kính.
        ("100%", "100 %", "100 %"),
        ("100 %", "100 %", "100 %"),
        ("%", "%", "%"),
    ],
)
def test_normalize(text, stripped, accented):
    assert normalize(text) == stripped
    assert normalize(text, keep_diacritics=True) == accented


def test_coverage_is_complete():
    """Thêm device/mode/zone vào caps mà quên đặt tên vi thì test này fail."""
    gaps = coverage(CAPS, LEX)
    assert gaps.complete, (gaps.devices, gaps.zones, gaps.modes, gaps.actions, gaps.units)


def test_cloud_only_has_no_grammar():
    """nav cố tình không có alias — câu dẫn đường phải rơi xuống escalate."""
    assert not LEX.aliases_of(DEVICE, "nav")


def test_caps_names_are_merged_not_overwritten():
    aliases = [a.lower() for a in LEX.aliases_of(DEVICE, "trunk")]
    assert "cốp xe" in aliases and "thùng xe" in aliases


def test_items_come_from_caps():
    assert LEX.lookup("spotify", kind=ITEM)[0].target == "spotify"
    assert LEX.lookup("cài đặt hud", kind=ITEM)[0].target == "hud_settings"


@pytest.mark.parametrize("text,kind,target", [
    ("đỏ", MODE, "amb_red"),
    ("độ", "unit", "celsius"),
    ("cam", MODE, "amb_orange"),
    ("câm", "action", "mute"),
])
def test_accented_layer_resolves_uniquely(text, kind, target):
    """Bẫy bỏ dấu: có dấu thì phải ra đúng 1 đích."""
    hits = LEX.lookup(text)
    assert len(hits) == 1, [(h.kind, h.target) for h in hits]
    assert (hits[0].kind, hits[0].target) == (kind, target)


def test_stripped_layer_is_fallback_only():
    """Mất dấu thì chấp nhận mơ hồ — matcher phải xử lý, không được im lặng chọn bừa."""
    assert len(LEX.lookup("do")) > 1


def test_every_stripped_ambiguity_is_separable_with_diacritics():
    for alias, group in LEX.ambiguous_only_stripped().items():
        assert len({e.accented for e in group}) == len(group), alias


def test_longest_match_ordering():
    entries = LEX.sorted_entries()
    lengths = [len(e.alias) for e in entries]
    assert lengths == sorted(lengths, reverse=True)


# Vùng khai ở zones.unsupported: CỐ Ý không nằm trong dev.zones. Có mặt trong từ
# điển để nhận ra rồi từ chối (VA_INVALID_ZONE), thay vì bỏ qua và để chữ số
# trong "hàng 3" trôi xuống thành mức.
_ZONES = yaml.safe_load(LEX_PATH.read_text(encoding="utf-8")).get("zones") or {}
UNSUPPORTED_ZONES = set(_ZONES.get("unsupported") or {})
# unsupported_per_device: chỉ vô hiệu với MỘT SỐ thiết bị (trái/phải — ghế và cửa
# kính vẫn dùng được, điều hòa thì tuỳ hành động).
PER_DEVICE_UNSUP = {z: set(spec.get("devices") or [])
                    for z, spec in {**(_ZONES.get("unsupported_per_device") or {}),
                                    **(_ZONES.get("ambiguous_per_device") or {})}.items()}


def test_unsupported_zones_are_known_but_not_addressable():
    assert UNSUPPORTED_ZONES, "mất khối zones.unsupported thì hàng 3 lại bị nuốt"
    for zone in UNSUPPORTED_ZONES:
        assert LEX.aliases_of(ZONE, zone, device="seat_heating")
        assert zone not in CAPS.devices["seat_heating"].zones


def test_per_device_unsupported_zones_only_on_listed_devices():
    """"bên trái" phải nhận ra ở quạt gió (để từ chối) nhưng KHÔNG chạm tới ghế."""
    assert PER_DEVICE_UNSUP, "mất khối unsupported_per_device thì trái/phải lại bị nuốt"
    for zone, devices in PER_DEVICE_UNSUP.items():
        for name in devices:
            # Thiết bị KHÔNG khai zones (frunk) thì resolve đã từ chối mọi vùng ở
            # nhánh riêng — không cần và không được đăng ký alias vùng cho nó.
            if not CAPS.devices[name].zones:
                continue
            assert LEX.aliases_of(ZONE, zone, device=name)
            assert zone not in CAPS.devices[name].zones
        for name in set(CAPS.devices) - devices:
            assert not LEX.aliases_of(ZONE, zone, device=name)


def test_alias_targets_all_exist():
    for e in LEX.entries:
        if e.kind == DEVICE:
            assert e.target in CAPS.devices
        elif e.kind == ITEM:
            assert e.target in CAPS.devices[e.device].items
        elif e.kind == ZONE:
            assert (e.target in CAPS.devices[e.device].zones
                    or e.target in UNSUPPORTED_ZONES
                    or e.device in PER_DEVICE_UNSUP.get(e.target, set()))
        elif e.kind == MODE:
            assert any(e.target in d.modes for d in CAPS.devices.values())


def test_zone_aliases_are_device_scoped():
    """'kính' là zone glass của sunroof, không phải zone của window."""
    assert LEX.aliases_of(ZONE, "glass", device="sunroof")
    assert not LEX.aliases_of(ZONE, "glass", device="window")
