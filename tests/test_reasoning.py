"""Luật suy luận là dữ liệu — lọc được theo xe, kiểm được, không trùng."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.caps import load_caps
from agentcar.config import LLMSettings
from agentcar.lexicon import load_lexicon
from agentcar.lint import ERROR, WARN, lint
from agentcar.llm import CloudPath
from agentcar.reasoning import (Rule, RuleSet, applicable, check, duplicates,
                                load_rules, render)

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
MINI = load_caps(ROOT / "tests" / "fixtures" / "mini.yaml")   # chỉ có window
RULES = load_rules()


def test_cues_are_split():
    rule = next(r for r in RULES.rules if "ngột ngạt" in r.cues)
    assert rule.cues == ("ngột ngạt", "bí", "thiếu khí")
    assert rule.device == "fan" and rule.mode == "fresh"


def test_every_shipped_rule_is_valid_for_vf9():
    kept, dropped = applicable(CAPS, RULES)
    assert not dropped, dropped
    assert len(kept) == len(RULES.rules)


def test_no_duplicate_cues():
    """Chính chỗ văn xuôi từng sai: luật hẹn giờ từng nằm hai lần trong prompt."""
    assert duplicates(CAPS, RULES) == []


def test_mode_as_action_target():
    """scene_mode dùng TÊN MODE làm action (D3), không có set_mode."""
    rule = next(r for r in RULES.rules if r.device == "scene_mode")
    assert rule.target(CAPS) == f"scene_mode {rule.mode}"


def test_normal_mode_target_uses_set_mode():
    rule = next(r for r in RULES.rules if r.device == "fan")
    assert rule.target(CAPS) == "fan set_mode fresh"


@pytest.mark.parametrize("rule,reason", [
    (Rule("sensations", ("x",), "khong_co_thiet_bi", action="turn_on"), "không có thiết bị"),
    (Rule("sensations", ("x",), "hud", action="turn_on"), "không dùng được"),
    (Rule("sensations", ("x",), "hvac", action="fold"), "không có action"),
    (Rule("sensations", ("x",), "hvac", mode="khong_co_mode"), "không có mode"),
    (Rule("sensations", (), "hvac", action="turn_on"), "không có cue"),
    (Rule("sensations", ("x",), "hvac"), "thiếu cả action và mode"),
])
def test_invalid_rules_are_caught(rule, reason):
    assert reason in (check(CAPS, rule) or "")


def test_rules_are_filtered_per_vehicle():
    """Đây là lý do chính tách ra dữ liệu: xe khác thì luật tự biến mất."""
    kept, dropped = applicable(MINI, RULES)
    assert [r.device for r in kept] == ["window"]
    assert len(dropped) == len(RULES.rules) - 1
    assert "hvac" not in render(MINI, RULES)


def test_dropped_rules_are_reported_by_lint():
    findings = lint(MINI, rules=RULES)
    warnings = [f for f in findings if f.level == WARN and f.where == "reasoning"]
    assert len(warnings) == len(RULES.rules) - 1


def test_duplicate_cue_is_an_error_not_a_warning():
    clashing = RuleSet(rules=[
        Rule("sensations", ("nóng",), "hvac", action="decrease"),
        Rule("situations", ("nóng",), "hvac", action="increase"),
    ])
    assert duplicates(CAPS, clashing)
    assert [f for f in lint(CAPS, rules=clashing) if f.level == ERROR]


def test_prompt_is_generated_from_the_rules():
    slow = CloudPath(CAPS, load_lexicon(CAPS), None, LLMSettings(), rules=RULES)
    assert "hvac decrease" in slow.system
    assert "scene_mode camp" in slow.system
    assert '"đèn"' in slow.system          # danh sách tên gọi chung


def test_prompt_shrinks_when_the_car_has_less():
    full = CloudPath(CAPS, load_lexicon(CAPS), None, LLMSettings(), rules=RULES).system
    small = CloudPath(MINI, load_lexicon(MINI), None, LLMSettings(), rules=RULES).system
    assert len(small) < len(full)


# ------------------------------------------------------------------ chỗ cắm trợ lý chung
def _rules_routing_to(target):
    base = load_rules()
    return RuleSet(rules=base.rules, ambiguous=base.ambiguous, vague=base.vague,
                   needs_live_data=base.needs_live_data, route_to=target)


def test_shipped_config_routes_to_an_assistant():
    assert load_rules().route_to == "assistant"


def test_without_a_target_the_tier_answers_itself():
    """Bỏ route_to thì tầng [2] tự trả lời — hành vi trước khi có trợ lý chung."""
    assert "trả lời bằng reply" in render(CAPS, _rules_routing_to(None))


def test_prompt_tells_the_model_to_hand_off_when_configured():
    prompt = render(CAPS, _rules_routing_to("assistant"))
    assert 'route: "assistant"' in prompt and "ĐỪNG tự trả lời" in prompt


def test_reply_is_handed_off_even_if_the_model_forgets_to_route():
    """Model quên dùng route thì agent vẫn giao cho trợ lý chung."""
    from agentcar.agent import Agent
    from agentcar.llm import CloudPath
    from agentcar.plan import Verdict
    from agentcar.safety import VehicleState

    class Client:
        def complete(self, system, user, timeout_s):
            return '{"reply":"Thủ đô nước Pháp là Paris ạ."}'

    class FakeAssistant:
        def answer(self, text):
            return "Paris ạ."

    agent = Agent(CAPS, load_lexicon(CAPS), handlers={"assistant": FakeAssistant()},
                  llm=CloudPath(CAPS, load_lexicon(CAPS), Client(), LLMSettings()))
    turn = agent.handle("thủ đô nước Pháp là gì", VehicleState())
    assert turn.verdict == Verdict.REPLY
    assert turn.results[0].target == "assistant"
    assert turn.tts == "Paris ạ."


def test_no_handler_falls_back_to_plain_routing():
    """Khai đích mà không có ai nhận thì vẫn trả ESCALATE_ROUTED cho tầng trên."""
    from agentcar.agent import Agent
    from agentcar.llm import CloudPath
    from agentcar.plan import Verdict
    from agentcar.safety import VehicleState

    class Client:
        def complete(self, system, user, timeout_s):
            return '{"route":"assistant"}'

    agent = Agent(CAPS, load_lexicon(CAPS), handlers={},
                  llm=CloudPath(CAPS, load_lexicon(CAPS), Client(), LLMSettings()))
    agent.handlers.clear()
    turn = agent.handle("thủ đô nước Pháp là gì", VehicleState())
    assert turn.verdict == Verdict.ESCALATE_ROUTED and turn.tts == ""


def test_model_cannot_invent_a_route_target():
    from agentcar.agent import Agent
    from agentcar.llm import CloudPath
    from agentcar.plan import Verdict
    from agentcar.safety import VehicleState

    class Client:
        def complete(self, system, user, timeout_s):
            return '{"route":"mot-agent-khong-ton-tai"}'

    agent = Agent(CAPS, load_lexicon(CAPS),
                  llm=CloudPath(CAPS, load_lexicon(CAPS), Client(), LLMSettings()))
    turn = agent.handle("câu gì đó lạ lắm", VehicleState())
    assert turn.verdict != Verdict.ESCALATE_ROUTED
    assert any("caps không công nhận" in n for n in turn.trace)
