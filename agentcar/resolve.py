"""Tầng [3] — xác nhận command thô bằng caps + chuẩn hoá giá trị.

Mọi command, dù đến từ grammar hay từ LLM, đều phải đi qua đây. Cái gì caps
không xác nhận thì không xuống PlanRunner.
"""
from __future__ import annotations

import math
from typing import Optional

from .caps import Caps, Device, UnitSpec
from .catalog import QUERY, VALUE_ACTIONS

# Target vùng đặc biệt: khai trong lexicon `ambiguous_per_device`, không có trong
# dev.zones nên phải chặn TRƯỚC bước kiểm tra vùng hợp lệ.
AMBIGUOUS_ZONE = "__mo_ho__"
from .plan import Code, Command, RawCommand, Result, Verdict

RELATIVE_ACTIONS = ("increase", "decrease")


def _tidy(v: float) -> float | int:
    return int(v) if isinstance(v, float) and v.is_integer() else v


def clamp(v: float, unit: UnitSpec) -> float:
    return min(max(v, unit.lo), unit.hi)


def snap(v: float, unit: UnitSpec) -> float:
    """Làm tròn về bội của resolution.

    QUYẾT ĐỊNH (Q6): làm tròn half-up tính từ 0, rồi mới clamp về [lo, hi].
    Ví dụ window resolution=20: 50 -> 60, 49 -> 40. hvac resolution=0.5: 22.3 -> 22.5.
    """
    if not unit.resolution:
        return v
    steps = math.floor(v / unit.resolution + 0.5)
    return round(steps * unit.resolution, 6)


def normalize_value(v: float, unit: UnitSpec, cat_ve_dai: bool = True) -> tuple[float, list[str]]:
    """Làm tròn về bội resolution, rồi (tuỳ chính sách) cắt về [lo, hi].

    Hai việc TÁCH RỜI: snap là chuẩn hoá bước nhảy của thiết bị ("hạ kính một
    nửa" -> 60 vì resolution=20), luôn phải làm. Clamp là quyết định nghiệp vụ về
    giá trị ngoài dải — xem `policy.gia_tri_ngoai_dai` trong caps.
    """
    notes: list[str] = []
    snapped = snap(v, unit)
    if snapped != v:
        notes.append(f"snap {_tidy(v)} -> {_tidy(snapped)} (resolution={_tidy(unit.resolution)})")
    if not cat_ve_dai and not unit.lo <= v <= unit.hi:
        # Người dùng xin ngoài dải: giữ nguyên, để tầng dưới quyết (chính sách qc).
        return snapped, notes
    if not cat_ve_dai:
        # Người dùng xin TRONG dải mà snap đẩy ra ngoài (window resolution=20, xin
        # 1% -> 0): đó là lỗi làm tròn của mình, không phải ý người ta. Vẫn cắt.
        final = clamp(snapped, unit)
        if final != snapped:
            notes.append(f"snap vượt dải, kéo về {_tidy(final)}")
        return final, notes
    final = clamp(snapped, unit)
    if final != snapped:
        notes.append(f"clamp {_tidy(snapped)} -> {_tidy(final)} (range {_tidy(unit.lo)}..{_tidy(unit.hi)})")
    return final, notes


def _fail(code: str, reason: str, device: Optional[str] = None) -> Result:
    return Result(verdict=Verdict.INVALID, code=code, reason=reason, device=device)


def _muon_tat(device: Device, zone: Optional[str], unit: UnitSpec) -> Result:
    """Xin "mức 0" trên thiết bị mà 0 nghĩa là TẮT -> hỏi lại, đừng tự quyết.

    BA sheet 3.1 #12: quạt gió và ghế sưởi/mát/massage có mức 0 = tắt (cột P).
    Người ta nói "quạt mức 0" nhiều khả năng muốn tắt quạt, nhưng tắt hẳn là
    việc khác với chỉnh mức — hỏi một câu rồi hẵng làm.

    Trả CONFIRM kèm sẵn lệnh tắt: Agent cất vào `pending`, người dùng "ừ" là chạy.
    """
    return Result(verdict=Verdict.CONFIRM, code=Code.NEED_CONFIRM, device=device.name,
                  command=Command(device=device.name, action="turn_off", zone=zone))


def _theo_ba(caps: Caps, khoa: str) -> bool:
    """Điểm mâu thuẫn `khoa` này đang xử theo BA hay theo QC. Xem khối `policy`."""
    return caps.policy.get(khoa, "qc") == "ba"


def _out_of_range(v: float, unit: UnitSpec, device: Device) -> Optional[Result]:
    """Giá trị TUYỆT ĐỐI ngoài range → không gửi lệnh, báo range đúng.

    QUYẾT ĐỊNH (28/09, theo BA sheet 3.1 #1): parser giữ nguyên con số người
    dùng nói, không tự cắt về biên. Clamp lặng lẽ làm mất thông tin: "bật điều
    hòa 35 độ" thành lệnh set 32 hợp lệ, nên tầng sau không còn gì để báo, và
    người dùng không biết dải hỗ trợ là bao nhiêu.

    Chỉ chặn giá trị nói thẳng ra. Lệnh TƯƠNG ĐỐI ("tăng 5 độ" khi đang 30, max
    32) vẫn thực thi về biên — BA sheet 3.1 #5/#8 yêu cầu EXECUTE cho ca đó, và
    đường đó không đi qua đây.
    """
    if unit.lo <= v <= unit.hi:
        return None
    res = _fail(Code.OUT_OF_RANGE,
                f"{device.name}: {_tidy(v)} ngoài range {_tidy(unit.lo)}..{_tidy(unit.hi)}",
                device.name)
    res.range_spec = (_tidy(unit.lo), _tidy(unit.hi), unit.name)
    return res


def _resolve_unit(device: Device, raw: RawCommand) -> tuple[Optional[UnitSpec], Optional[Result]]:
    assert device.value is not None
    name = raw.unit or device.value.default_unit
    unit = device.value.unit(name)
    if unit is None:
        known = ", ".join(device.value.units)
        return None, _fail(Code.INVALID_UNIT, f"{device.name}: đơn vị '{name}' không hợp lệ (có: {known})")
    return unit, None


def resolve(caps: Caps, raw: RawCommand) -> Result:
    notes: list[str] = []

    device = caps.devices.get(raw.device)
    if device is None:
        return _fail(Code.UNKNOWN_DEVICE, f"không có thiết bị '{raw.device}' trên {caps.model}")

    if device.cloud_only:
        # Đích đã biết từ caps → router chuyển thẳng, không cần tầng suy luận
        return Result(verdict=Verdict.ESCALATE_ROUTED, code=Code.ESCALATE_ROUTED,
                      target=device.name, device=device.name,
                      reason=f"{device.name} do cloud xử lý")

    if not device.support:
        return Result(verdict=Verdict.NOT_SUPPORT, code=Code.NOT_SUPPORT, device=device.name,
                      reason=f"{caps.model} không hỗ trợ {device.name}")

    # ---- action
    action = raw.action or device.default_action
    if action is None:
        return _fail(Code.NO_DEFAULT_ACTION, f"{device.name}: thiếu action và caps không khai default_action", device.name)
    if raw.action is None:
        notes.append(f"action mặc định: {action}")

    allowed = caps.effective_actions(device)
    if action not in allowed:
        if action == QUERY:
            return _fail(Code.NOT_READABLE, f"{device.name}: không đọc được trạng thái (readable=false)", device.name)
        return _fail(Code.INVALID_ACTION, f"{device.name}: action '{action}' không hợp lệ (có: {', '.join(allowed)})", device.name)

    spec = caps.catalog.spec(device.type)

    # ---- zone
    zone = raw.zone
    zone_mac_dinh = False
    if device.zones:
        if zone is None:
            zone = device.default_zone
            zone_mac_dinh = zone is not None
            if zone is not None:
                notes.append(f"zone mặc định: {zone}")
        if zone == AMBIGUOUS_ZONE:
            # Không tự chọn hộ: "ghế khách" là ghế phụ hay hàng sau thì chỉ người
            # nói mới biết (BA sheet 3.2 #47).
            res = _fail(Code.ZONE_AMBIGUOUS, f"{device.name}: vùng nghe ra nhiều vị trí",
                        device.name)
            res.cho_vung = RawCommand(device=device.name, action=action, zone=None,
                                      value=raw.value, unit=raw.unit, mode=raw.mode)
            return res
        if zone is not None and zone not in device.zones:
            group = "level" if action in VALUE_ACTIONS else "switch"
            mapped = (device.zone_alias.get(group) or {}).get(zone)
            if mapped is not None and mapped in device.zones:
                notes.append(f"vùng '{zone}' -> '{mapped}' (nhóm {group})")
                zone = mapped
            else:
                return _fail(Code.INVALID_ZONE, f"{device.name}: zone '{zone}' không hợp lệ (có: {', '.join(device.zones)})", device.name)
    elif zone is not None:
        return _fail(Code.INVALID_ZONE, f"{device.name}: không có zone", device.name)

    # ---- mode
    mode = raw.mode
    valid_modes = [m for m in device.modes if m not in device.exclude]

    if spec.mode_as_action and action in valid_modes:
        mode = action  # D3: tên mode chính là action (theo policy trong caps)
    if spec.mode_as_action and action == "turn_off" and mode is None:
        return _fail(Code.MODE_REQUIRED, f"{device.name}: cần nói rõ tắt chế độ nào", device.name)

    if action in ("set_mode", "clear_mode") and mode is None:
        return _fail(Code.MODE_REQUIRED, f"{device.name}: action '{action}' cần mode", device.name)
    if mode is not None and mode not in valid_modes:
        # D2: mode bị exclude khác hẳn mode gõ sai — tách mã lỗi để trả lời cho đúng
        if mode in device.modes:
            return _fail(Code.MODE_EXCLUDED, f"{caps.model} không hỗ trợ chế độ '{mode}' của {device.name}", device.name)
        return _fail(Code.INVALID_MODE, f"{device.name}: mode '{mode}' không hợp lệ", device.name)

    # ---- item (app_control / screen_control)
    item = raw.item
    if device.has_items:
        if action in ("open", "close"):
            if item is None:
                return _fail(Code.ITEM_REQUIRED, f"{device.name}: cần chỉ rõ mở cái gì", device.name)
            if item not in device.items:
                return _fail(Code.INVALID_ITEM, f"{device.name}: '{item}' không có trong danh sách", device.name)
    elif item is not None:
        return _fail(Code.INVALID_ITEM, f"{device.name}: không nhận item", device.name)

    # ---- value
    value: Optional[float] = None
    unit_name: Optional[str] = None
    step: Optional[float] = None

    if action in VALUE_ACTIONS:
        if not device.has_number:
            return _fail(Code.INVALID_ACTION, f"{device.name}: không có giá trị số", device.name)
        unit, err = _resolve_unit(device, raw)
        if err:
            return err
        assert unit is not None
        unit_name = unit.name

        if action == "set_level":
            if raw.value is None:
                return _fail(Code.VALUE_REQUIRED, f"{device.name}: set_level cần value", device.name)
            asked = float(raw.value)
            if _theo_ba(caps, "buoc_khong_duong") and asked == 0 and unit.zero_is_off:
                return _muon_tat(device, zone, unit)
            theo_ba = _theo_ba(caps, "gia_tri_ngoai_dai")
            if theo_ba:
                err = _out_of_range(asked, unit, device)
                if err:
                    return err
            # Theo QC: vẫn snap, nhưng KHÔNG cắt về dải — con số người dùng nói
            # phải đi nguyên xuống dưới (QC Sunroof E197 mong value=200).
            value, vnotes = normalize_value(asked, unit, cat_ve_dai=theo_ba)
            notes += vnotes
        else:  # increase / decrease
            step = float(raw.value) if raw.value is not None else unit.nudge
            if step is None:
                return _fail(Code.VALUE_REQUIRED, f"{device.name}: {action} cần value (caps không khai nudge)", device.name)
            if raw.value is None:
                notes.append(f"bước mặc định: nudge={_tidy(step)}")
            elif step == 0 and unit.zero_is_off and _theo_ba(caps, "buoc_khong_duong"):
                return _muon_tat(device, zone, unit)
            elif step <= 0 and _theo_ba(caps, "buoc_khong_duong"):
                # "giảm quạt 0 mức" / "giảm điều hòa -2 độ": bước không dương thì
                # không phải điều chỉnh. Trước đây vẫn ra lệnh và đọc "Đã giảm
                # quạt gió 0 mức" — nghe như đã làm gì đó. BA sheet 3.1 #12–#14
                # bảo dừng lại và báo dải đúng.
                res = _fail(Code.OUT_OF_RANGE,
                            f"{device.name}: bước {_tidy(step)} không hợp lệ "
                            f"(dải {_tidy(unit.lo)}..{_tidy(unit.hi)})",
                            device.name)
                res.range_spec = (_tidy(unit.lo), _tidy(unit.hi), unit.name)
                return res

    elif action == "turn_on" and device.has_number and raw.value is not None:
        unit, err = _resolve_unit(device, raw)
        if err:
            return err
        assert unit is not None
        unit_name = unit.name
        asked = float(raw.value)
        if _theo_ba(caps, "buoc_khong_duong") and asked == 0 and unit.zero_is_off:
            return _muon_tat(device, zone, unit)
        theo_ba = _theo_ba(caps, "gia_tri_ngoai_dai")
        if theo_ba:
            err = _out_of_range(asked, unit, device)
            if err:
                return err
        value, vnotes = normalize_value(asked, unit, cat_ve_dai=theo_ba)
        notes += vnotes

    elif action == "turn_on" and device.has_number:
        unit = device.value.unit() if device.value else None
        if unit is not None and unit.comfort_default is not None:
            value, unit_name = unit.comfort_default, unit.name
            notes.append(f"comfort_default: {_tidy(value)} {unit_name}")

    cmd = Command(
        device=device.name,
        action=action,
        zone=zone,
        value=_tidy(value) if value is not None else None,
        unit=unit_name,
        mode=mode,
        mode_group=spec.group_of(mode) if mode else None,  # D1
        item=item,
        step=_tidy(step) if step is not None else None,
    )
    return Result(verdict=Verdict.OK, command=cmd, notes=notes, zone_mac_dinh=zone_mac_dinh)


def va_lenh_mo_hinh(caps: Caps, raw: RawCommand) -> tuple[RawCommand, list[str]]:
    """Vá lệnh do MODEL sinh ra, thay vì vứt cả lệnh vì một trường sai.

    Model (cloud lẫn NLU trên xe) hay đúng thiết bị và hành động nhưng sai một
    chi tiết — prompt ĐÃ liệt kê vùng và item hợp lệ của từng thiết bị, model
    vẫn trả `mirror.fold zone=rear`. Chống thì không chống được; chịu đựng thì
    được, và một lệnh thiếu vùng vẫn hơn hẳn không lệnh nào.

    Đo trên 120 câu edge bó tay: 8 câu rơi vào nhóm này.

    KHÔNG vá hành động và KHÔNG đoán thiết bị từ chữ — đó là phần ý chính của
    câu, sai thì phải trượt chứ không được chữa bừa.
    """
    sua: list[str] = []

    # Item chỉ thuộc ĐÚNG MỘT thiết bị thì chính nó nói ra chủ của mình:
    # "screen_control + battery_charging" -> app_control.
    #
    # Không thuộc thiết bị NÀO thì model vừa bịa ra ("error_alert" — caps có
    # "vehicle_alert"). Bỏ item, giữ lệnh: "màn hình đang hiện gì" vẫn trả lời
    # được, còn giữ item bịa thì resolve bác sạch cả lệnh.
    #
    # Ép enum ở tầng API cũng chặn được chuyện này, và DashScope CÓ hỗ trợ
    # json_schema. Nhưng đo thật: schema làm mỗi lượt chậm thêm ~1,2 giây
    # (2.651-3.071ms so với 1.461-1.987ms), mà trần của xe là 1.200ms. Và
    # `strict` bắt mọi khoá phải có mặt nên model điền rác vào `ask`. Làm ở đây
    # thì miễn phí và tức thì.
    if raw.item:
        chu = [d.name for d in caps.devices.values() if raw.item in (d.items or {})]
        if len(chu) == 1 and chu[0] != raw.device:
            sua.append(f"item '{raw.item}' thuộc {chu[0]}, không phải {raw.device}")
            raw.device = chu[0]
        elif not chu:
            sua.append(f"bỏ item '{raw.item}' (không thiết bị nào có)")
            raw.item = None

    device = caps.devices.get(raw.device)
    if device is None:
        return raw, sua

    # Vùng không có thật -> BỎ VÙNG, giữ lệnh. Thiết bị không có vùng nào cũng
    # vậy. Mặc định của caps sẽ điền chỗ trống.
    if raw.zone and raw.zone not in device.zones:
        sua.append(f"bỏ vùng '{raw.zone}' ({raw.device} không có)")
        raw.zone = None

    # Chế độ không có thật -> bỏ chế độ, giữ lệnh. Cùng lý do với item.
    if raw.mode and raw.mode not in (device.modes or ()):
        chu = [d.name for d in caps.devices.values() if raw.mode in (d.modes or ())]
        if len(chu) == 1:
            sua.append(f"mode '{raw.mode}' thuộc {chu[0]}, không phải {raw.device}")
            raw.device = chu[0]
            device = caps.devices[chu[0]]
        elif not chu:
            sua.append(f"bỏ mode '{raw.mode}' (không thiết bị nào có)")
            raw.mode = None

    # Đơn vị không có thật -> bỏ đơn vị, giữ con số. Đơn vị mặc định của thiết
    # bị thường là thứ người ta định nói.
    if raw.unit and device.value is not None and raw.unit not in device.value.units:
        sua.append(f"bỏ đơn vị '{raw.unit}' ({raw.device} đo bằng "
                   f"{', '.join(device.value.units)})")
        raw.unit = None

    return raw, sua
