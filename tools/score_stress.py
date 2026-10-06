"""Chấm agent trên tests/stress_test_gpt_v2.jsonl (500 câu tiếng Việt, nhãn theo caps VF9).

Cách chấm: so khớp TRỌN lệnh — device + action + các slot có trong nhãn. Một câu chỉ
tính đúng khi mọi lệnh của nó đúng và đúng số lượng.

Mấy chỗ quy đổi, ghi rõ vì nhãn của bộ này đọc caps trực tiếp nên lệch với vài quyết
định của agent:
  volume.mute           ≡ volume.set_level(0)          (D4: agent bỏ action mute)
  turn_on + value       ≡ set_level(value)              (nhãn gọi "bật 22 độ" là turn_on)
  turn_on + mode        ≡ set_mode(mode)                 (91 nhãn — agent gọi set_mode)
  turn_on + set_mode(X) ≡ một lệnh turn_on(mode=X)       (cùng hiệu quả, khác cách tách)
  scene_mode.set_mode   ≡ scene_mode.<tên mode>        (D3: tên mode làm action)
  zone=null             ≡ zone mặc định của thiết bị
  out_of_scope / device=None  → phải KHÔNG ra lệnh nào
Thứ tự lệnh KHÔNG tính — nhãn của bộ này nhiều chỗ đảo thứ tự so với câu nói.
  frunk/hud/tire_pressure     → phải trả NOT_SUPPORT
  nav                          → phải trả ESCALATE_ROUTED
"""
from __future__ import annotations

import collections
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentcar.agent import Agent                      # noqa: E402
from agentcar.caps import load_caps                   # noqa: E402
from agentcar.config import LLMSettings, settings as load_settings  # noqa: E402
from agentcar.lexicon import load_lexicon             # noqa: E402
from agentcar.llm import build_cloud_path              # noqa: E402
from agentcar.safety import VehicleState              # noqa: E402
from agentcar.telemetry import Recorder               # noqa: E402

UNSUPPORTED = {"frunk", "hud", "tire_pressure", "auto_highbeam"}


class _Cmd:
    """Lệnh đã quy chuẩn, đủ trường để matches() đọc như RawCommand."""

    def __init__(self, device=None, action=None, zone=None, value=None, mode=None, item=None):
        self.device, self.action, self.zone = device, action, zone
        self.value, self.mode, self.item = value, mode, item


def expected(row: dict) -> list[dict]:
    out = []
    for c in row["commands"]:
        sl = c["slots"]
        if not sl["device"] or c["intent"] == "out_of_scope":
            continue
        out.append({"device": sl["device"], "action": c["intent"], "zone": sl["zone"],
                    "value": sl["value"], "mode": sl["mode"], "item": sl["item"]})
    return out


def canon(cmds: list) -> list:
    """Gộp hai bên về một cách viết trước khi so.

    Nhãn viết "bật chế độ X" thành turn_on(mode=X); agent viết set_mode(mode=X).
    Agent đôi khi tách thành turn_on rồi set_mode(X) — cùng hiệu quả. Không quy về
    một dạng thì 91 nhãn bị trừ điểm chỉ vì tên action.
    """
    out = []
    for c in cmds:
        action, mode = c["action"], c["mode"]
        if action == "turn_on" and mode is not None:
            action = "set_mode"
        out.append({**c, "action": action})
    # bỏ turn_on trơn khi cùng thiết bị đã có set_mode
    moded = {c["device"] for c in out if c["action"] == "set_mode" and c["mode"]}
    return [c for c in out
            if not (c["action"] == "turn_on" and c["device"] in moded
                    and c["value"] is None and c["mode"] is None and c["item"] is None)]


def as_dict(c) -> dict:
    return {f: getattr(c, f) for f in ("device", "action", "zone", "value", "mode", "item")}


def matches(want: dict, got, caps) -> bool:
    if got.device != want["device"]:
        return False
    action, mode = want["action"], want["mode"]
    if action == "mute":                      # D4
        action, want = "set_level", {**want, "value": 0}
    if action == "turn_on" and want["value"] is not None:
        action = "set_level"
    if action == "set_mode" and got.device == "scene_mode":   # D3
        action = mode
    if got.action != action:
        return False
    dev = caps.devices.get(want["device"])
    if want["zone"] is not None and got.zone != want["zone"]:
        return False
    if want["zone"] is None and dev is not None and dev.zones and got.zone != dev.default_zone:
        return False
    for field in ("value", "mode", "item"):
        if want[field] is not None and getattr(got, field) != want[field]:
            return False
    return True


def run(use_llm: bool, limit: int | None = None, timeout_ms: int | None = None):
    caps = load_caps(ROOT / "caps" / "vf9.yaml")
    lex = load_lexicon(caps)
    # Một Agent mới mỗi câu để không dính ngữ cảnh lượt trước, nhưng dùng lại
    # đúng một kết nối cloud — mở lại 500 lần thì phần lớn thời gian là bắt tay TLS.
    settings = load_settings(caps)
    if timeout_ms:
        settings = replace(settings, timeout_ms=timeout_ms)
    slow = build_cloud_path(caps, lex, settings) if use_llm else None
    if slow is not None:
        slow.client.warmup()
    rows = [json.loads(l) for l in (ROOT / "tests" / "stress_test_gpt_v2.jsonl")
            .read_text(encoding="utf-8").splitlines()]
    if limit:
        rows = rows[:limit]

    stats = collections.Counter()
    latency: list[float] = []
    by_difficulty = collections.defaultdict(collections.Counter)
    by_language = collections.defaultdict(collections.Counter)
    misses = []

    for row in rows:
        agent = Agent(caps, lex=lex, llm=slow, llm_settings=LLMSettings(),
                      recorder=Recorder(path=None, enabled=False))
        turn = agent.handle(row["text"], VehicleState())
        if turn.cloud_ms is not None:
            latency.append(turn.cloud_ms)
            stats["cloud"] += 1
            if turn.cloud_error:
                stats["cloud_error"] += 1
        got = [r.command for r in turn.results if r.command]
        want = expected(row)

        if not want:                                   # câu out_of_scope
            ok = not got
        elif all(w["device"] in UNSUPPORTED for w in want):
            ok = turn.verdict == "NOT_SUPPORT"
        elif all(w["device"] == "nav" for w in want):
            ok = turn.verdict == "ESCALATE_ROUTED"
        else:
            # Ghép không theo thứ tự: mỗi lệnh nhãn phải tìm được một lệnh agent
            # chưa dùng khớp với nó.
            want = canon(want)
            got = [type("C", (), c)() if False else _Cmd(**c) for c in canon([as_dict(g) for g in got])]
            pool = list(got)
            ok = len(got) == len(want)
            for w in want:
                hit = next((g for g in pool if matches(w, g, caps)), None)
                if hit is None:
                    ok = False
                    break
                pool.remove(hit)

        stats["ok" if ok else "miss"] += 1
        by_difficulty[row["difficulty"]]["ok" if ok else "miss"] += 1
        by_language[row["language"]]["ok" if ok else "miss"] += 1
        if not ok:
            misses.append((row, turn, got, want))

    total = stats["ok"] + stats["miss"]
    print(f"{'CÓ CLOUD' if use_llm else 'CHỈ FAST PATH'}: {stats['ok']}/{total} = {stats['ok']/total:.1%}")
    if latency:
        latency.sort()
        pick = lambda q: latency[min(len(latency) - 1, int(len(latency) * q))]
        over = sum(1 for ms in latency if ms > 1200)
        print(f"cloud: gọi {stats['cloud']} · lỗi {stats['cloud_error']} · "
              f"p50 {pick(0.5):.0f}ms p95 {pick(0.95):.0f}ms · "
              f"quá deadline 1200ms: {over}/{len(latency)}")
    print()
    for name, table in (("độ khó", by_difficulty), ("ngôn ngữ", by_language)):
        print(f"theo {name}:")
        for key, c in sorted(table.items()):
            n = c["ok"] + c["miss"]
            print(f"   {key:12} {c['ok']:4}/{n:4} = {c['ok']/n:6.1%}")
        print()
    return misses


if __name__ == "__main__":
    use_llm = "--llm" in sys.argv
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    tmo = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--timeout-ms=")), None)
    misses = run(use_llm, limit, tmo)
    show = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--show=")), 0)
    for row, turn, got, want in misses[:show]:
        print(f"── {row['id']} [{row['difficulty']}/{row['language']}] {row['text'][:88]}")
        print(f"   cần : {[(w['device'], w['action'], w['zone'], w['value'], w['mode'], w['item']) for w in want]}")
        print(f"   được: {[(g.device, g.action, g.zone, g.value, g.mode, g.item) for g in got] or turn.verdict}")
