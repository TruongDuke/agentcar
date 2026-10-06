"""Vòng hội thoại xác nhận: đồng ý, từ chối, quá hạn, và kiểm lại trạng thái xe."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.agent import Agent
from agentcar.caps import load_caps
from agentcar.lexicon import load_lexicon
from agentcar.plan import Verdict
from agentcar.safety import VehicleState as S

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
MINI = load_caps(ROOT / "tests" / "fixtures" / "mini.yaml")


@pytest.fixture
def clock():
    return [0.0]


@pytest.fixture
def agent(clock):
    return Agent(CAPS, clock=lambda: clock[0])


def test_confirm_then_yes_executes(agent):
    driving = S(gear="D", speed_kmh=40)
    first = agent.handle("mở cửa kính", driving)
    assert first.verdict == Verdict.CONFIRM and first.awaiting_confirm

    second = agent.handle("ừ", driving)
    assert second.verdict == Verdict.OK
    assert second.results[0].command.device == "window"
    assert agent.pending is None


@pytest.mark.parametrize("answer", ["ừ", "đúng rồi", "ok", "làm đi", "vâng"])
def test_various_yes_phrases(agent, answer):
    agent.handle("mở cửa kính", S(gear="D"))
    assert agent.handle(answer, S(gear="D")).verdict == Verdict.OK


@pytest.mark.parametrize("answer", ["thôi", "không", "thôi khỏi", "hủy", "đừng"])
def test_various_no_phrases(agent, answer):
    agent.handle("mở cửa kính", S(gear="D"))
    turn = agent.handle(answer, S(gear="D"))
    assert turn.verdict == Verdict.CANCELLED and agent.pending is None


def test_state_recheck_can_turn_confirm_into_deny(clock):
    """Tính chất quan trọng nhất: đồng ý KHÔNG phải là giấy thông hành.

    Xe tăng tốc trong lúc chờ thì lệnh phải bị từ chối, không được chạy.
    """
    agent = Agent(MINI, clock=lambda: clock[0])
    assert agent.handle("mở cửa kính", S(gear="D", speed_kmh=10)).verdict == Verdict.CONFIRM
    turn = agent.handle("ừ", S(gear="D", speed_kmh=60))
    assert turn.verdict == Verdict.DENY
    assert "30 km/h" in turn.results[0].reason


def test_state_recheck_can_drop_the_question(clock):
    """Ngược lại: xe đã về P thì không còn lý do chặn nữa."""
    agent = Agent(MINI, clock=lambda: clock[0])
    agent.handle("mở cửa kính", S(gear="D"))
    assert agent.handle("ừ", S(gear="P")).verdict == Verdict.OK


def test_pending_expires(agent, clock):
    agent.handle("mở cửa kính", S(gear="D"))
    clock[0] = 45.0
    turn = agent.handle("ừ", S(gear="D"))
    assert turn.verdict == Verdict.ESCALATE_UNKNOWN
    assert any("quá hạn" in n for n in turn.trace)


def test_new_command_replaces_pending(agent):
    agent.handle("mở cửa kính", S(gear="D"))
    turn = agent.handle("bật điều hòa", S(gear="D"))
    assert turn.verdict == Verdict.OK
    assert turn.results[0].command.device == "hvac"
    assert agent.pending is None


def test_question_ending_in_khong_is_not_a_refusal(agent):
    """'không' một mình là từ chối, nhưng '... mở không' là câu hỏi."""
    agent.handle("mở cửa kính", S(gear="D"))
    turn = agent.handle("cửa kính mở không", S(gear="D"))
    assert turn.verdict == Verdict.OK
    assert turn.results[0].command.action == "query"


def test_question_does_not_cancel_pending(agent):
    """C4: hỏi lại cho rõ rồi mới quyết là chuyện bình thường, không được mất lệnh."""
    agent.handle("mở cửa kính", S(gear="D"))
    middle = agent.handle("cửa kính mở chưa", S(gear="D"))
    assert middle.awaiting_confirm and agent.pending is not None
    assert agent.handle("ừ", S(gear="D")).verdict == Verdict.OK


def test_answer_without_pending_escalates(agent):
    assert agent.handle("ừ", S()).verdict == Verdict.ESCALATE_UNKNOWN


def test_deny_is_never_queued_for_confirmation(agent):
    """DENY không bao giờ hỏi lại — không có gì để người dùng đồng ý."""
    turn = agent.handle("gập gương", S(speed_kmh=50))
    assert turn.verdict == Verdict.DENY
    assert agent.pending is None and not turn.awaiting_confirm


def test_answer_phrases_are_whole_utterance_only():
    lex = load_lexicon(CAPS)
    assert lex.answer("ừ") is True
    assert lex.answer("không") is False
    assert lex.answer("điều hòa đang bật không") is None
