"""Ghi số liệu mỗi lượt — và không được ghi câu nói trừ khi bật có chủ ý."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcar.agent import Agent
from agentcar.caps import load_caps
from agentcar.config import LLMSettings
from agentcar.safety import VehicleState as S
from agentcar.telemetry import Recorder, load, summarize

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")


@pytest.fixture
def log(tmp_path):
    return tmp_path / "turns.jsonl"


def agent_logging_to(log, keep_text=False):
    return Agent(CAPS, llm_settings=LLMSettings(),
                 recorder=Recorder(path=log, keep_text=keep_text))


def test_one_line_per_turn(log):
    agent = agent_logging_to(log)
    for text in ["bật điều hòa", "tắt điều hòa", "mở cửa kính"]:
        agent.handle(text, S())
    assert len(load(log)) == 3


def test_text_is_not_logged_by_default(log):
    """Trong xe người ta nói cả tên người, địa chỉ — mặc định không ghi."""
    agent_logging_to(log).handle("bật điều hòa", S())
    assert "text" not in load(log)[0]


def test_text_is_logged_only_when_asked(log):
    agent_logging_to(log, keep_text=True).handle("bật điều hòa", S())
    assert load(log)[0]["text"] == "bật điều hòa"


def test_env_can_turn_it_off():
    assert Recorder.from_env({"AGENTCAR_LOG": "off"}).enabled is False
    assert Recorder.from_env({"AGENTCAR_LOG": "/tmp/x.jsonl"}).keep_text is False
    assert Recorder.from_env({"AGENTCAR_LOG_TEXT": "1"}).keep_text is True


@pytest.mark.parametrize("text,label,checkpoint", [
    ("bật điều hòa", "none", 2),
    ("", "gate", 1),   # gate chặn trước cả triage nên có nhãn riêng
    ("5 phút nữa bật điều hòa", "not_now", 3),
    ("bật đèn", "device", 4),
])
def test_label_and_checkpoint(log, text, label, checkpoint):
    agent_logging_to(log).handle(text, S())
    row = load(log)[0]
    assert (row["label"], row["checkpoint"]) == (label, checkpoint)


def test_local_turns_are_marked_local(log):
    agent_logging_to(log).handle("bật điều hòa", S())
    row = load(log)[0]
    assert row["path"] == "edge" and row["cloud_ms"] is None


def test_plan_and_verdict_are_recorded(log):
    agent_logging_to(log).handle("bật sưởi ghế lái mức 2", S())
    row = load(log)[0]
    assert row["verdict"] == "OK"
    assert row["plan"] == [{"device": "seat_heating", "action": "set_level"}]


def test_a_broken_log_path_never_breaks_the_agent(tmp_path):
    """Telemetry hỏng thì thôi — không bao giờ được làm sập agent."""
    blocked = tmp_path / "khong-ghi-duoc"
    blocked.write_text("đây là file, không phải thư mục")
    agent = Agent(CAPS, llm_settings=LLMSettings(),
                  recorder=Recorder(path=blocked / "turns.jsonl"))
    assert agent.handle("bật điều hòa", S()).verdict == "OK"


def test_corrupt_lines_are_skipped(log):
    log.write_text('{"ok":1}\nkhông phải json\n{"ok":2}\n', encoding="utf-8")
    assert len(load(log)) == 2


def test_summary_of_nothing_says_so():
    assert "chưa có số liệu" in summarize([])


def test_summary_counts_cloud_share(log):
    rows = [{"path": "cloud", "ms": 800, "cloud_ms": 780, "cloud_kind": "commands",
             "label": "off_domain", "checkpoint": 5, "verdict": "OK"},
            {"path": "edge", "ms": 1, "label": "none", "checkpoint": 2, "verdict": "OK"}]
    report = summarize(rows)
    assert "2 lượt" in report and "lên cloud 1" in report


def test_measurement_runs_can_tag_themselves(log):
    """Script đo phải khai nguồn, nếu không số liệu thật lẫn hàng trăm lượt giả."""
    Agent(CAPS, llm_settings=LLMSettings(),
          recorder=Recorder(path=log, tag="do-thu")).handle("bật điều hòa", S())
    assert load(log)[0]["tag"] == "do-thu"


def test_untagged_turns_are_the_real_ones(log):
    agent_logging_to(log).handle("bật điều hòa", S())
    assert "tag" not in load(log)[0]


def test_only_real_filters_tagged_rows():
    from agentcar.telemetry import only_real
    rows = [{"verdict": "OK"}, {"verdict": "OK", "tag": "do-thu"}]
    assert only_real(rows) == [{"verdict": "OK"}]


def test_summary_warns_about_tagged_rows():
    report = summarize([{"path": "edge", "ms": 1, "label": "none", "checkpoint": 2,
                         "verdict": "OK", "tag": "do-thu"}])
    assert "script đo" in report


def test_env_reads_the_tag():
    assert Recorder.from_env({"AGENTCAR_LOG_TAG": "benchmark"}).tag == "benchmark"


# ------------------------------------------------- thời gian trả về cho người gọi
def test_turn_mang_theo_thoi_gian_va_duong_di():
    """Trước đây ms chỉ đi vào telemetry rồi mất. Người gọi cũng cần: caps khai
    gate.deadline_ms cho tầng edge, không trả ms ra thì không ai đối chiếu được
    lượt vừa rồi có kịp ngân sách đó không."""
    turn = Agent(CAPS).handle("bật sưởi ghế lái mức 2", S())
    assert turn.ms is not None and turn.ms > 0
    assert turn.path == "edge"           # không gọi cloud thì ở lại trên máy

    out = turn.to_dict()
    assert out["ms"] == round(turn.ms, 1) and out["path"] == "edge"
    assert "cloud_ms" not in out and "label" not in out   # không có thì đừng bày ra


def test_nhan_triage_chi_hien_khi_edge_truot():
    turn = Agent(CAPS).handle("hôm nay trời đẹp nhỉ", S())
    assert turn.to_dict().get("label") == "off_domain"
