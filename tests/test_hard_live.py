"""Case khó — đo tầng suy luận trên cloud. Gọi thật, mặc định bỏ qua.

    AGENTCAR_LIVE=1 pytest tests/test_hard_live.py -v

Kiểm DẠNG kết quả chứ không ép câu chữ: model diễn đạt mỗi lần một khác, nhưng
"phải hỏi lại" hay "phải chuyển NavAgent" thì không được đổi.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agentcar.agent import Agent
from agentcar.caps import load_caps
from agentcar.plan import Verdict
from agentcar.safety import VehicleState as S

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
CASES = yaml.safe_load((ROOT / "tests" / "golden_hard.vi.yaml").read_text(encoding="utf-8"))

live = pytest.mark.skipif(os.environ.get("AGENTCAR_LIVE") != "1",
                          reason="cần AGENTCAR_LIVE=1 (gọi mạng thật, tốn tiền)")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Gỡ chặn mạng (bộ này cố tình gọi thật) nhưng VẪN không ghi telemetry.

    Fixture này ghi đè bản trong conftest, nên phải tự đặt lại cờ tắt log —
    nếu không thì mỗi lần chạy live test lại nhồi mấy chục dòng giả vào số liệu.
    """
    monkeypatch.setenv("AGENTCAR_LOG", "off")
    yield


@live
@pytest.mark.parametrize("case", CASES, ids=[f"{c['need']}:{c['say']}" for c in CASES])
def test_hard(case, request):
    if case.get("known_gap"):
        request.applymarker(pytest.mark.xfail(reason="nợ kỹ thuật đã ghi nhận", strict=False))
    agent = Agent(CAPS)
    if agent.cloud is None:
        pytest.skip("chưa có key hoặc AGENTCAR_LLM_ENABLED=false")
    for prior in case.get("after") or []:
        agent.handle(prior, S())

    turn = agent.handle(case["say"], S())
    commands = [r.command for r in turn.results if r.command]
    kind = case["kind"]

    if case.get("path") == "cloud":
        assert turn.cloud_ms is not None, \
            f"tầng edge chộp mất câu cần suy luận (chốt {turn.checkpoint})"

    if kind == "commands":
        assert commands, f"không ra lệnh nào: {turn.verdict} / {turn.tts}"
        assert len(commands) >= case.get("min_commands", 1), [c.device for c in commands]
        want = case.get("device")
        if want:
            want = [want] if isinstance(want, str) else want
            assert commands[0].device in want, f"ra {commands[0].device}, cần một trong {want}"
        # Kiểm cả tham số: chỉ kiểm device thì "24 độ à không 22 thôi" cũng đậu,
        # vì thiết bị vẫn đúng mà giá trị thì sai hẳn.
        for field in ("action", "value", "mode", "zone"):
            if field in case:
                got = getattr(commands[0], field)
                assert got == case[field], f"{field}: cần {case[field]}, được {got}"
    elif kind == "ask":
        assert turn.verdict == Verdict.ASK, f"{turn.verdict}: {turn.tts}"
        assert turn.tts.strip().endswith("?") or "?" in turn.tts
    elif kind == "refuse":
        # Ai từ chối không quan trọng; điều bất biến là KHÔNG chạy lệnh nào.
        assert not commands, f"đã chạy lệnh dù là câu có điều kiện: {[c.device for c in commands]}"
        assert turn.tts, "từ chối mà im lặng thì người dùng không biết chuyện gì"
    elif kind == "reply":
        assert turn.verdict == Verdict.REPLY, f"{turn.verdict}: {turn.tts}"
        assert not commands, f"không được chạy lệnh nào: {[c.device for c in commands]}"
    elif kind == "route":
        assert turn.verdict == Verdict.ESCALATE_ROUTED, f"{turn.verdict}: {turn.tts}"
        assert turn.results[0].target == case["target"]
