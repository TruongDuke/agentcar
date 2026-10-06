"""Hợp đồng cho hai đầu nối với xe — sinh từ caps.

Ngày có adapter thật (đọc CAN / gửi lệnh xuống bus), thêm nó vào PROVIDERS và
RUNNERS dưới đây là biết ngay đúng hay sai, thay vì dò tay 30 thiết bị.

Mọi ca test đều sinh từ caps: thêm thiết bị vào caps là hợp đồng tự rộng theo.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.caps import load_caps
from agentcar.resolve import resolve
from agentcar.runner import ExecResult, MockPlanRunner
from agentcar.state import MockStateProvider
from helpers import minimal_raw

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")

# Thêm adapter thật vào đây khi có.
PROVIDERS = {"mock": lambda: MockStateProvider(CAPS)}
RUNNERS = {"mock": MockPlanRunner}

CONTROL = [(d.name, a) for d in CAPS.devices.values()
           for a in CAPS.effective_actions(d) if a != "query"]
IDS = [f"{d}.{a}" for d, a in CONTROL]

# Lệnh tương đối không nằm trong hợp đồng "chạy xong là biết trạng thái": chưa biết
# mức cũ thì không suy ra được mức mới, và KHÔNG được đoán (quyết định S2).
# clear_mode cũng vậy: xoá một chế độ chưa từng bật thì không có gì để ghi.
RELATIVE = ("increase", "decrease", "clear_mode")
ABSOLUTE = [(d, a) for d, a in CONTROL if a not in RELATIVE]
ABS_IDS = [f"{d}.{a}" for d, a in ABSOLUTE]


def command_for(device: str, action: str):
    result = resolve(CAPS, minimal_raw(CAPS, CAPS.devices[device], action))
    assert result.ok, f"caps không dựng được lệnh {device}.{action}: {result.reason}"
    return result.command


@pytest.fixture(params=list(PROVIDERS), ids=list(PROVIDERS))
def provider(request):
    return PROVIDERS[request.param]()


@pytest.fixture(params=list(RUNNERS), ids=list(RUNNERS))
def runner(request):
    return RUNNERS[request.param]()


# ------------------------------------------------------------------ StateProvider
@pytest.mark.parametrize("device,action", ABSOLUTE, ids=ABS_IDS)
def test_state_is_known_after_a_command(provider, device, action):
    """Chạy lệnh rồi thì phải đọc lại được trạng thái — nếu không, câu hỏi trạng
    thái sẽ luôn trả 'chưa biết'."""
    command = command_for(device, action)
    provider.apply(command)
    assert provider.get(device, command.zone).known, f"{device}.{action} không ghi lại gì"


@pytest.mark.parametrize("device", sorted({d for d, a in CONTROL if a == "clear_mode"}))
def test_clear_mode_removes_what_set_mode_added(provider, device):
    provider.apply(command_for(device, "set_mode"))
    provider.apply(command_for(device, "clear_mode"))
    assert not provider.get(device, command_for(device, "set_mode").zone).modes


@pytest.mark.parametrize("device", sorted({d for d, a in CONTROL
                                           if a in ("increase", "decrease")}))
def test_relative_change_starts_from_comfort_default(provider, device):
    """Chưa biết mức cũ thì lấy comfort_default của caps; biết rồi thì cập nhật đúng bước.

    ĐẢO NGƯỢC giao kèo cũ, có chủ ý. Trước đây tăng/giảm khi chưa biết mức là một
    no-op im lặng — nhưng agent vẫn nói "đã giảm 2 độ", nên bảng trạng thái hiện
    "tắt" ngay dưới câu báo thành công. Nói dối thì tệ hơn đoán, mà đây cũng không
    hẳn là đoán: comfort_default là con số caps đã khai sẵn.

    Đơn vị nào KHÔNG khai comfort_default thì quay lại hành vi cũ, và test này canh
    đúng chỗ đó: mọi đơn vị có tăng/giảm đều phải khai, nếu không lời nói dối quay
    lại qua cửa sau.
    """
    relative = next(a for a in CAPS.effective_actions(CAPS.devices[device])
                    if a in ("increase", "decrease"))
    step = command_for(device, relative)
    unit = CAPS.devices[device].value.unit(step.unit)
    assert unit.comfort_default is not None, \
        f"{device}.{unit.name}: có tăng/giảm mà caps không khai comfort_default"

    provider.apply(step)
    delta = step.step if relative == "increase" else -step.step
    want = min(max(unit.comfort_default + delta, unit.lo), unit.hi)
    assert provider.get(device, step.zone).value == want

    if "set_level" not in CAPS.effective_actions(CAPS.devices[device]):
        return
    base = command_for(device, "set_level")
    provider.apply(base)
    provider.apply(step)
    unit = CAPS.devices[device].value.unit(base.unit)
    expected = base.value + (step.step if relative == "increase" else -step.step)
    assert provider.get(device, step.zone).value == min(max(expected, unit.lo), unit.hi)


@pytest.mark.parametrize("device", sorted({d for d, a in CONTROL if a == "set_level"}))
def test_set_level_keeps_value_and_unit(provider, device):
    command = command_for(device, "set_level")
    provider.apply(command)
    state = provider.get(device, command.zone)
    assert state.value == command.value and state.unit == command.unit


@pytest.mark.parametrize("device", sorted({d for d, a in CONTROL if a == "set_mode"}))
def test_set_mode_records_the_mode(provider, device):
    command = command_for(device, "set_mode")
    provider.apply(command)
    assert command.mode in provider.get(device, command.zone).modes.values()


def test_unknown_device_is_answered_not_crashed(provider):
    assert not provider.get("khong_co_thiet_bi_nay").known


def test_query_never_changes_state(provider):
    provider.apply(command_for("hvac", "turn_on"))
    before = provider.get("hvac", "all")
    provider.apply(resolve(CAPS, minimal_raw(CAPS, CAPS.devices["hvac"], "query")).command)
    assert provider.get("hvac", "all") == before


# ------------------------------------------------------------------ PlanRunner
@pytest.mark.parametrize("device,action", CONTROL, ids=IDS)
def test_runner_answers_every_valid_command(runner, device, action):
    command = command_for(device, action)
    outcomes = runner.execute([command])
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], ExecResult)
    assert outcomes[0].command is command, "phải trả về đúng lệnh đã nhận"


def test_runner_keeps_order_and_count(runner):
    commands = [command_for("hvac", "turn_on"), command_for("wifi", "turn_on"),
                command_for("mirror", "fold")]
    outcomes = runner.execute(commands)
    assert [o.command.device for o in outcomes] == [c.device for c in commands]


def test_runner_reports_refusal_instead_of_raising():
    refusing = MockPlanRunner(reject=lambda cmd: "gate CAN chặn")
    outcome = refusing.execute([command_for("hvac", "turn_on")])[0]
    assert not outcome.ok and outcome.detail
    assert refusing.log == [], "lệnh bị từ chối thì không được ghi là đã chạy"


def test_runner_handles_an_empty_plan(runner):
    assert runner.execute([]) == []
