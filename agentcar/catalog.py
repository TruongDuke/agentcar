"""Catalog action canonical theo type (caps/actions.yaml)."""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "caps" / "actions.yaml"

VALUE_ACTIONS = ("set_level", "increase", "decrease")
MODE_ACTIONS = ("set_mode", "clear_mode")
QUERY = "query"


@dataclass(frozen=True)
class ActionSpec:
    name: str
    required_args: tuple[str, ...]
    optional_args: tuple[str, ...]
    semantics: str = ""


@dataclass(frozen=True)
class TypeSpec:
    name: str
    actions: tuple[str, ...]
    mode_as_action: bool = False
    mode_groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    proposed_actions: tuple[str, ...] = ()

    def group_of(self, mode: str) -> Optional[str]:
        """Mode thuộc nhóm nào — dùng để biết mode nào loại trừ lẫn nhau."""
        for group, patterns in self.mode_groups.items():
            for pat in patterns:
                if fnmatch.fnmatch(mode, pat):
                    return group
        return None


@dataclass
class Catalog:
    actions: dict[str, ActionSpec]
    types: dict[str, TypeSpec]
    decisions: dict[str, dict] = field(default_factory=dict)

    def provisional(self) -> list[tuple[str, str]]:
        """Quyết định còn ở trạng thái tạm chốt — cần xác nhận với bên định nghĩa xe."""
        return [
            (key, d.get("what", ""))
            for key, d in self.decisions.items()
            if str(d.get("status", "")).startswith("tạm chốt")
        ]

    def spec(self, type_name: str) -> TypeSpec:
        if type_name not in self.types:
            raise KeyError(f"type '{type_name}' chưa có trong caps/actions.yaml")
        return self.types[type_name]


def _split_args(args: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    required, optional = [], []
    for a in args or []:
        (optional if a.endswith("?") else required).append(a.rstrip("?"))
    return tuple(required), tuple(optional)


def load_catalog(path: Path | str = DEFAULT_PATH) -> Catalog:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    actions = {}
    for name, spec in (raw.get("actions") or {}).items():
        req, opt = _split_args(spec.get("args"))
        actions[name] = ActionSpec(name, req, opt, spec.get("semantics", ""))

    types = {}
    for name, spec in (raw.get("types") or {}).items():
        unknown = [a for a in (spec.get("actions") or []) if a not in actions]
        if unknown:
            raise ValueError(f"type '{name}' dùng action chưa khai: {unknown}")
        types[name] = TypeSpec(
            name=name,
            actions=tuple(spec.get("actions") or []),
            mode_as_action=bool(spec.get("mode_as_action")),
            mode_groups={g: tuple(p) for g, p in (spec.get("mode_groups") or {}).items()},
            proposed_actions=tuple(spec.get("proposed_actions") or []),
        )

    return Catalog(actions=actions, types=types, decisions=raw.get("decisions") or {})
