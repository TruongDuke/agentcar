"""Gọi DashScope thật. Mặc định bỏ qua vì tốn tiền.

    AGENTCAR_LIVE=1 pytest tests/test_llm_live.py -v

Giữ CHIỀU của lệnh suy ra từ câu cảm giác — thứ mà tầng [3][4] không bắt được,
vì "nóng quá -> tăng nhiệt độ" vẫn là một lệnh hợp lệ.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agentcar.caps import load_caps
from agentcar.config import settings
from agentcar.lexicon import load_lexicon
from agentcar.llm import build_cloud_path

ROOT = Path(__file__).resolve().parent.parent
CASES = yaml.safe_load((ROOT / "tests" / "golden_llm.vi.yaml").read_text(encoding="utf-8"))

live = pytest.mark.skipif(os.environ.get("AGENTCAR_LIVE") != "1",
                          reason="cần AGENTCAR_LIVE=1 (gọi mạng thật, tốn tiền)")


@pytest.fixture(autouse=True)
def no_network():
    """Bỏ chặn mạng của conftest — đây là bộ test cố tình gọi thật."""
    yield


@pytest.fixture(scope="module")
def slow():
    caps = load_caps(ROOT / "caps" / "vf9.yaml")
    path = build_cloud_path(caps, load_lexicon(caps), settings(caps))
    if path is None:
        pytest.skip("chưa có key hoặc AGENTCAR_LLM_ENABLED=false")
    return path


@live
@pytest.mark.parametrize("case", CASES, ids=[c["say"] for c in CASES])
def test_live(case, slow):
    outcome = slow.interpret(case["say"])
    assert outcome.ok, outcome.error
    expect = case["expect"]

    if expect.get("empty"):
        assert not outcome.commands, outcome.commands
        return

    assert outcome.commands, "model không trả lệnh nào"
    command = outcome.commands[0]
    for key, want in expect.items():
        assert getattr(command, key) == want, f"{key}: cần {want}, được {getattr(command, key)}"


@live
def test_latency_fits_the_deadline(slow):
    outcome = slow.interpret("nóng quá")
    assert outcome.ok, outcome.error
    assert outcome.elapsed_ms < slow.settings.timeout_ms
