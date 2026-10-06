"""Chấm agent trên bộ câu chuẩn tiếng Việt."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from .agent import Agent
from .caps import Caps
from .config import LLMSettings
from .safety import VehicleState

DEFAULT_GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "golden.vi.yaml"


@dataclass
class CaseResult:
    say: str
    passed: bool
    expected: dict
    got: dict
    diffs: list[str] = field(default_factory=list)


def load_cases(path: Path | str = DEFAULT_GOLDEN) -> list[dict]:
    rows = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    # Tập "không được ra lệnh" viết dạng danh sách câu cho gọn.
    return [r if isinstance(r, dict) else {"say": r, "expect": {"no_command": True}}
            for r in rows]


def _state(raw: Optional[dict]) -> VehicleState:
    return VehicleState(**(raw or {}))


def _actual(turn) -> dict:
    """Gồm cả TẦNG đã đi qua: kết quả đúng mà đi sai đường vẫn là sai.

    checkpoint  1 gate · 2 tầng edge · 3 điều kiện · 4 hỏi tại chỗ · 5-6 cloud
    path        local | cloud
    """
    out: dict[str, Any] = {
        "verdict": turn.verdict, "tts": turn.tts,
        "checkpoint": turn.checkpoint,
        "path": "cloud" if turn.cloud_ms is not None else "edge",
        "label": turn.label,
    }
    first = turn.results[0] if turn.results else None
    if first is not None:
        if first.code:
            out["code"] = first.code
        if first.command:
            out.update({k: v for k, v in first.command.to_dict().items()})
    out["commands"] = [r.command.to_dict() for r in turn.results if r.command]
    # `commands` là mọi lệnh trong plan — kể cả `query` (chỉ đọc trạng thái) và
    # lệnh trùng trạng thái hiện tại (`da_dung`), hai loại agent KHÔNG gửi xuống
    # xe. Muốn đo "xe có thật sự làm gì không" thì phải nhìn `sent`.
    out["sent"] = [r.command.to_dict() for r in turn.results
                   if r.ok and r.command is not None
                   and r.command.action != "query"
                   and not r.da_dung and not r.cham_bien and not r.hoi_vung]
    return out


def run_case(caps: Caps, case: dict, nlu=None) -> CaseResult:
    # Bộ này đo TẦNG EDGE nên phải tắt tầng [2]: nếu không, "nóng quá" lúc ra
    # ESCALATE lúc ra lệnh thật tuỳ .env, và mỗi lần chấm lại tốn tiền gọi API.
    # Câu dành cho tầng [2] nằm ở tests/golden_llm.vi.yaml.
    # nlu=False tắt tầng [1b] để đo riêng đóng góp của tầng luật. Mặc định None
    # = để Agent tự quyết (bật nếu có trọng số).
    agent = Agent(caps, llm_settings=LLMSettings(), nlu=nlu)
    for prior in case.get("context") or []:
        agent.handle(prior, _state(case.get("state")))

    turn = agent.handle(case["say"], _state(case.get("state")))
    got = _actual(turn)
    expected = case["expect"]
    diffs = []

    for key, want in expected.items():
        if key == "no_command":
            if bool(got["commands"]) == bool(want):
                diffs.append(f"ra lệnh oan: {got['commands']}")
        elif key == "commands":
            for i, want_cmd in enumerate(want):
                if i >= len(got["commands"]):
                    diffs.append(f"thiếu lệnh #{i}")
                    continue
                for k, v in want_cmd.items():
                    if got["commands"][i].get(k) != v:
                        diffs.append(f"lệnh#{i}.{k}: cần {v}, được {got['commands'][i].get(k)}")
        elif got.get(key) != want:
            diffs.append(f"{key}: cần {want}, được {got.get(key)}")

    return CaseResult(say=case["say"], passed=not diffs, expected=expected, got=got, diffs=diffs)


def evaluate(caps: Caps, cases: Optional[list[dict]] = None) -> list[CaseResult]:
    return [run_case(caps, c) for c in (cases if cases is not None else load_cases())]


def format_report(results: list[CaseResult]) -> str:
    passed = sum(1 for r in results if r.passed)
    lines = [f"{len(results)} câu | đúng {passed} ({passed / max(len(results), 1):.1%})"]
    for r in results:
        if not r.passed:
            lines.append(f"  FAIL  {r.say}")
            for d in r.diffs:
                lines.append(f"        {d}")
    return "\n".join(lines)
