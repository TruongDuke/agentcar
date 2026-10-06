"""Khôi phục mức sau khi tắt tiếng — state của hội thoại, không phải của thiết bị."""
from __future__ import annotations

from pathlib import Path

from agentcar.agent import Agent
from agentcar.caps import load_caps
from agentcar.plan import Code, Verdict
from agentcar.safety import VehicleState as S

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")


def test_unmute_restores_the_level_we_set():
    agent = Agent(CAPS)
    agent.handle("âm lượng 30", S())
    agent.handle("tắt tiếng", S())
    turn = agent.handle("bật tiếng lại", S())
    assert turn.verdict == Verdict.OK
    assert turn.results[0].command.value == 30


def test_mute_does_not_overwrite_the_memory():
    """Nhớ cả mức 0 thì 'bật tiếng lại' sẽ khôi phục đúng trạng thái tắt."""
    agent = Agent(CAPS)
    agent.handle("âm lượng 25", S())
    agent.handle("tắt tiếng", S())
    assert agent.last_level["volume"] == 25


def test_unmute_without_memory_asks():
    agent = Agent(CAPS)
    agent.handle("tắt tiếng", S())
    turn = agent.handle("bật tiếng lại", S())
    assert turn.verdict == Verdict.INVALID
    assert turn.results[0].code == Code.NO_PREVIOUS_VALUE
    assert "bao nhiêu" in turn.tts


def test_relative_change_does_not_update_memory():
    """Không có state provider thì tăng/giảm không suy ra được mức thật,
    nên không được ghi bừa vào bộ nhớ."""
    agent = Agent(CAPS)
    agent.handle("âm lượng 20", S())
    agent.handle("tăng âm lượng", S())
    assert agent.last_level["volume"] == 20


def test_memory_is_per_device():
    agent = Agent(CAPS)
    agent.handle("âm lượng 20", S())
    agent.handle("độ sáng màn hình 80 phần trăm", S())
    assert agent.last_level == {"volume": 20, "screen_brightness": 80}


def test_blocked_command_is_not_remembered():
    agent = Agent(CAPS)
    agent.handle("hạ kính một nửa", S(gear="D"))      # CONFIRM, chưa chạy
    assert "window" not in agent.last_level


def test_reset_clears_memory():
    agent = Agent(CAPS)
    agent.handle("âm lượng 30", S())
    agent.reset()
    assert agent.last_level == {}
