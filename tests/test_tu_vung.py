"""Hợp đồng giữa caps và ba bộ từ vựng bên ngoài (caps/tu_vung.yaml).

Sáu lỗi đo trong một ngày đều sinh ở chỗ dịch tên giữa các bên, và cả sáu đều
THẤT BẠI IM LẶNG. Bộ test này biến im lặng thành đỏ: mọi tên lạ phải nằm ở `map`
hoặc ở `chua_co`, không có đường thứ ba.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agentcar.caps import load_caps

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")
TU_VUNG = yaml.safe_load((ROOT / "caps" / "tu_vung.yaml").read_text(encoding="utf-8"))
RAW = yaml.safe_load((ROOT / "caps" / "vf9.yaml").read_text(encoding="utf-8"))


def caps_actions() -> set[str]:
    out: set[str] = set()
    for name, dev in CAPS.devices.items():
        out |= set(CAPS.effective_actions(dev))
        out |= set((RAW["devices"].get(name) or {}).get("modes") or [])
    return out


# ------------------------------------------------------------------ nguồn sự thật
def test_nguon_nghiem_thu_khop_voi_policy():
    """`nguon_nghiem_thu` và khối `policy` không được nói ngược nhau."""
    nguon = TU_VUNG["nguon_nghiem_thu"]
    assert nguon in ("qc", "ba")
    assert CAPS.policy, "caps thiếu khối policy"
    assert all(v == nguon for v in CAPS.policy.values()), (
        f"tu_vung nói nghe {nguon} nhưng policy lại là {CAPS.policy} — "
        "hai chỗ khai cùng một quyết định thì phải khớp")


# ------------------------------------------------------------------------ QC
def test_qc_map_tro_toi_action_co_that():
    for cu, moi in TU_VUNG["qc"]["action"].items():
        assert moi in caps_actions(), f"QC {cu} -> {moi}: caps không có {moi}"


def test_qc_chua_co_thi_dung_la_chua_co():
    """Đã khai `chua_co` thì caps phải THẬT SỰ chưa có — làm xong mà quên xoá
    khỏi danh sách thì backlog nói dối."""
    for act in TU_VUNG["qc"]["chua_co"]:
        assert act not in caps_actions(), (
            f"'{act}' khai là chưa có nhưng caps đã có rồi — xoá khỏi tu_vung.yaml")


@pytest.mark.skipif(not (ROOT / "tests" / "golden_qc.vi.yaml").exists(),
                    reason="chưa sinh golden_qc")
def test_moi_action_trong_golden_deu_map_duoc():
    """Không câu nào trong bộ đo dùng action mà bản dịch không biết."""
    cases = yaml.safe_load((ROOT / "tests" / "golden_qc.vi.yaml").read_text(encoding="utf-8"))
    biet = caps_actions() | set(TU_VUNG["qc"]["action"]) | set(TU_VUNG["qc"]["chua_co"])
    la = {c["expect"]["action"] for c in cases
          if isinstance(c, dict) and c.get("expect", {}).get("action")} - biet
    assert not la, f"action lạ trong golden_qc, chưa khai ở tu_vung.yaml: {sorted(la)}"


# --------------------------------------------------------------------- model
@pytest.mark.skipif(not (ROOT / "joint-nlu-trained" / "label_maps.json").exists(),
                    reason="không có model")
def test_moi_intent_cua_model_hoac_map_duoc_hoac_khai_ngoai_caps():
    """Đường thứ ba là chỗ lỗi trốn: intent không map được mà cũng không khai
    ngoài caps thì sang_raw() lặng lẽ trả None và không ai biết."""
    lm = json.loads((ROOT / "joint-nlu-trained" / "label_maps.json").read_text(encoding="utf-8"))
    ngoai = set(TU_VUNG["model"]["ngoai_caps"])
    chua = set(TU_VUNG["model"].get("chua_co") or [])
    alias = TU_VUNG["model"]["action"]
    acts = caps_actions()

    la = []
    for intent in lm["intents"]:
        dev, _, act = intent.partition(".")
        if dev in ngoai or intent in chua:
            continue
        if dev not in CAPS.devices:
            la.append(f"{intent} (device lạ)")
        elif act not in acts and act not in alias:
            la.append(f"{intent} (action lạ)")
    assert not la, ("intent của model không map được mà cũng không khai ngoai_caps:\n  "
                    + "\n  ".join(la))


def test_model_chua_co_thi_dung_la_chua_co():
    for intent in TU_VUNG["model"].get("chua_co") or []:
        dev, _, act = intent.partition(".")
        assert dev in CAPS.devices, f"'{intent}': caps không có cả thiết bị {dev}"
        assert act not in caps_actions(), (
            f"'{intent}' khai là chưa có nhưng caps đã có action {act} — xoá khỏi tu_vung.yaml")


def test_ngoai_caps_dung_la_ngoai_caps():
    for dev in TU_VUNG["model"]["ngoai_caps"]:
        d = CAPS.devices.get(dev)
        assert d is None or d.cloud_only or not d.support, (
            f"'{dev}' khai là ngoài caps nhưng caps có và dùng được — "
            "xoá khỏi tu_vung.yaml, nếu không lệnh của model bị bỏ oan")


def test_model_alias_tro_toi_action_co_that():
    for cu, moi in TU_VUNG["model"]["action"].items():
        for m in (moi if isinstance(moi, list) else [moi]):
            assert m in caps_actions(), f"model {cu} -> {m}: caps không có {m}"


# --------------------------------------------------------------------- bộ đo
def test_sent_va_commands_dung_la_hai_thu_khac_nhau():
    """`commands` đếm cả query, `sent` thì không. Dùng nhầm là sai cả phép đo —
    đã dính một lần, nên chốt bằng test."""
    from agentcar.agent import Agent
    from agentcar.config import LLMSettings
    from agentcar.evaluate import _actual

    assert set(TU_VUNG["bo_do"]) == {"commands", "sent"}
    got = _actual(Agent(CAPS, llm_settings=LLMSettings()).handle("điều hòa bật chưa"))
    assert got["commands"], "câu hỏi trạng thái phải có lệnh query trong plan"
    assert not got["sent"], "câu hỏi trạng thái KHÔNG được tính là lệnh xuống xe"
