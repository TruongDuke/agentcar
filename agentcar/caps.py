"""Loader + index cho caps/<model>.yaml. Caps là nguồn sự thật duy nhất."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from .catalog import MODE_ACTIONS, QUERY, VALUE_ACTIONS, Catalog, TypeSpec, load_catalog


@dataclass(frozen=True)
class UnitSpec:
    name: str
    lo: float
    hi: float
    resolution: Optional[float] = None
    nudge: Optional[float] = None
    comfort_default: Optional[float] = None
    # Cột P bảng range của BA (Capability 3.1, ô P4:P11) — "Mức 0 = Tắt?".
    # KHÔNG suy được từ lo: quạt và ghế đều lo=1 và 0 nghĩa là tắt, nhưng đèn
    # viền và màn hình cũng lo=1 mà BA ghi Không (màn hình luôn phải sáng ≥1).
    zero_is_off: bool = False


@dataclass(frozen=True)
class ValueSpec:
    kind: str  # "number" | "item"
    default_unit: Optional[str] = None
    units: dict[str, UnitSpec] = field(default_factory=dict)

    @property
    def is_number(self) -> bool:
        return self.kind == "number"

    def unit(self, name: Optional[str] = None) -> Optional[UnitSpec]:
        return self.units.get(name or self.default_unit or "")


@dataclass(frozen=True)
class SafetyRule:
    device: str
    action: str
    verdict: str
    when: str
    reason: str
    index: int = 0

    @property
    def is_wildcard(self) -> bool:
        return self.action == "*"


@dataclass
class Device:
    name: str
    type: str
    zones: tuple[str, ...] = ()
    default_zone: Optional[str] = None
    value: Optional[ValueSpec] = None
    modes: tuple[str, ...] = ()
    items: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    names: dict[str, list[str]] = field(default_factory=dict)
    default_action: Optional[str] = None
    readable: bool = False
    support: bool = True
    query_only: bool = False
    cloud_only: bool = False
    safety_gated: bool = False
    exclude: tuple[str, ...] = ()
    # Ánh xạ vùng theo NHÓM HÀNH ĐỘNG — cột M sheet 3.2 của BA tách mỗi thiết bị
    # thành nhiều dòng ("Điều hòa – Bật/Tắt" vs "Điều hòa – Nhiệt độ") với hai bộ
    # vùng khác nhau. {"level": {"left": "driver"}} nghĩa là: với lệnh mức, "bên
    # trái" là khu lái; với nhóm khác thì vẫn không hợp lệ.
    zone_alias: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def has_number(self) -> bool:
        return self.value is not None and self.value.is_number

    @property
    def has_items(self) -> bool:
        return bool(self.items)

    def names_for(self, locale: str = "vi") -> list[str]:
        return list(self.names.get(locale) or [])


@dataclass
class Caps:
    version: int
    model: str
    locales: tuple[str, ...]
    devices: dict[str, Device]
    safety: list[SafetyRule]
    gate: dict[str, Any]
    # Chuẩn nghiệm thu khi hai tài liệu mâu thuẫn. Xem khối `policy` trong caps.
    policy: dict[str, str]
    nlu: dict[str, Any]
    catalog: Catalog
    path: Optional[Path] = None

    # ---------------------------------------------------------------- actions
    def catalog_actions(self, device: Device) -> list[str]:
        """Action mà TYPE hỗ trợ, sau khi trừ exclude và lọc theo cấu hình device.

        Chưa xét support/cloud_only — dùng cho thông báo lỗi và cho linter.
        """
        spec: TypeSpec = self.catalog.spec(device.type)
        acts = [a for a in spec.actions if a not in device.exclude]

        if spec.mode_as_action:
            acts += [m for m in device.modes if m not in device.exclude]
        if not device.has_number:
            acts = [a for a in acts if a not in VALUE_ACTIONS]
        if not device.modes:
            acts = [a for a in acts if a not in MODE_ACTIONS]
        if device.readable or device.query_only:
            acts.append(QUERY)

        seen, out = set(), []
        for a in acts:
            if a not in seen:
                seen.add(a)
                out.append(a)
        return out

    def effective_actions(self, device: Device) -> list[str]:
        """Action thực sự thực thi được trên dòng xe này."""
        if not device.support or device.cloud_only:
            return []
        return self.catalog_actions(device)

    # ---------------------------------------------------------------- safety
    def rules_for(self, device: str, action: str) -> list[SafetyRule]:
        """Rule khớp (device, action). Wildcard '*' chỉ phủ action điều khiển.

        QUYẾT ĐỊNH: query không bị safety chặn trừ khi rule ghi đích danh
        action: query — nếu không thì "nắp sạc mở chưa?" sẽ bị DENY lúc xe chạy.
        """
        out = []
        for r in self.safety:
            if r.device != device:
                continue
            if r.action == action:
                out.append(r)
            elif r.is_wildcard and action != QUERY:
                out.append(r)
        return out

    def wildcard_expansion(self, rule: SafetyRule) -> list[str]:
        dev = self.devices.get(rule.device)
        if dev is None:
            return []
        return [a for a in self.effective_actions(dev) if a != QUERY]


def _parse_value(raw: Optional[dict]) -> Optional[ValueSpec]:
    if not raw:
        return None
    if raw.get("kind") == "item":
        return ValueSpec(kind="item")
    units = {}
    for uname, u in (raw.get("units") or {}).items():
        units[uname] = UnitSpec(
            name=uname,
            lo=u["lo"],
            hi=u["hi"],
            resolution=u.get("resolution"),
            nudge=u.get("nudge"),
            comfort_default=u.get("comfort_default"),
            zero_is_off=bool(u.get("zero_is_off")),
        )
    return ValueSpec(kind="number", default_unit=raw.get("default_unit"), units=units)


def load_caps(path: Path | str, catalog: Optional[Catalog] = None) -> Caps:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    catalog = catalog or load_catalog()

    devices: dict[str, Device] = {}
    for name, d in (raw.get("devices") or {}).items():
        devices[name] = Device(
            name=name,
            type=d.get("type", name),
            zones=tuple(d.get("zones") or ()),
            default_zone=d.get("default_zone"),
            value=_parse_value(d.get("value")),
            modes=tuple(d.get("modes") or ()),
            items=d.get("items") or {},
            names=d.get("names") or {},
            default_action=d.get("default_action"),
            readable=bool(d.get("readable")),
            support=d.get("support", True),
            query_only=bool(d.get("query_only")),
            cloud_only=bool(d.get("cloud_only")),
            safety_gated=bool(d.get("safety_gated")),
            exclude=tuple((d.get("actions") or {}).get("exclude") or ()),
            zone_alias={g: dict(m) for g, m in (d.get("zone_alias") or {}).items()},
        )

    safety = [
        SafetyRule(
            device=r["device"],
            action=r["action"],
            verdict=r["verdict"],
            when=r["when"],
            reason=r.get("reason", ""),
            index=i,
        )
        for i, r in enumerate(raw.get("safety") or [])
    ]

    return Caps(
        version=raw.get("version", 0),
        model=raw.get("model", "?"),
        locales=tuple(raw.get("locales") or ()),
        devices=devices,
        safety=safety,
        gate=raw.get("gate") or {},
        policy={k: str(v) for k, v in (raw.get("policy") or {}).items()},
        nlu=raw.get("nlu") or {},
        catalog=catalog,
        path=path,
    )
