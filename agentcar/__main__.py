"""CLI: python -m agentcar <lint|caps|check>"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .caps import load_caps
from .config import settings
from .engine import decide
from .agent import Agent
from .evaluate import evaluate, load_cases
from .server import serve
from .telemetry import DEFAULT_PATH as LOG_PATH
from .telemetry import load as load_log
from .telemetry import only_real
from .state import MockStateProvider
from .telemetry import summarize
from .evaluate import format_report as format_eval
from .lexicon import DEVICE, load_lexicon, normalize
from .lint import ERROR, format_report, lint
from .monitor import MockSignalMonitor
from . import baseline
from .respond import Responder
from .watch import render
from .plan import RawCommand
from .safety import VehicleState

DEFAULT_CAPS = Path(__file__).resolve().parent.parent / "caps" / "vf9.yaml"


def _state_from_args(args) -> VehicleState:
    return VehicleState(
        gear=args.gear,
        speed_kmh=args.speed,
        battery_pct=args.battery,
        charging=args.charging,
        parking_brake=args.parking_brake,
    )


def cmd_lint(args) -> int:
    caps = load_caps(args.caps)
    lex = None if args.no_lexicon else load_lexicon(caps)
    findings = lint(caps, lex)
    print(format_report(caps, findings))
    return 1 if any(f.level == ERROR for f in findings) else 0


def cmd_caps(args) -> int:
    caps = load_caps(args.caps)
    if args.device is None:
        print(f"{caps.model} v{caps.version} — {len(caps.devices)} devices")
        for name, dev in caps.devices.items():
            flags = [f for f, on in (("unsupported", not dev.support), ("cloud", dev.cloud_only),
                                     ("readable", dev.readable), ("gated", dev.safety_gated)) if on]
            print(f"  {name:18} {dev.type:18} {','.join(flags)}")
        return 0

    dev = caps.devices.get(args.device)
    if dev is None:
        print(f"không có thiết bị '{args.device}'", file=sys.stderr)
        return 1

    star = lambda z: z + "*" if z == dev.default_zone else z
    print(f"{dev.name} (type={dev.type})  support={'no' if not dev.support else 'yes'}  "
          f"readable={'yes' if dev.readable else 'no'}  safety_gated={'yes' if dev.safety_gated else 'no'}")
    print(f"  actions : {' '.join(caps.effective_actions(dev)) or '(none)'}")
    if dev.zones:
        print(f"  zones   : {' '.join(star(z) for z in dev.zones)}     (* = default)")
    if dev.value and dev.value.is_number:
        for u in dev.value.units.values():
            bits = [f"{u.name} {u.lo}..{u.hi}"]
            for label in ("resolution", "nudge", "comfort_default"):
                if getattr(u, label) is not None:
                    bits.append(f"{label}={getattr(u, label)}")
            print(f"  value   : {'  '.join(bits)}")
    if dev.items:
        print(f"  items   : {len(dev.items)} mục")
    if dev.modes:
        print(f"  modes   : {' '.join(dev.modes)}")
    if dev.default_action:
        print(f"  default_action: {dev.default_action}")
    rules = [r for r in caps.safety if r.device == dev.name]
    for r in rules:
        print(f"  safety  : {r.action} -> {r.verdict} when {r.when}")
    return 0


def cmd_check(args) -> int:
    caps = load_caps(args.caps)
    raw = RawCommand(device=args.device, action=args.action, zone=args.zone,
                     value=args.value, unit=args.unit, mode=args.mode, item=args.item)
    result = decide(caps, raw, _state_from_args(args))
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        print(f"verdict  {result.verdict}" + (f"  ({result.code})" if result.code else ""))
        if result.command:
            print(f"plan     {json.dumps(result.command.to_dict(), ensure_ascii=False)}")
        if result.reason:
            print(f"reason   {result.reason}")
        for n in result.notes:
            print(f"  · {n}")
    return 0 if result.ok else 2


def cmd_lex(args) -> int:
    caps = load_caps(args.caps)
    lex = load_lexicon(caps)

    if args.lookup:
        hits = lex.lookup(args.lookup)
        print(f"'{args.lookup}' → {normalize(args.lookup, keep_diacritics=True)} / {normalize(args.lookup)}")
        if not hits:
            print("  không khớp gì")
        for e in hits:
            print(f"  {e.kind:7} {e.target}" + (f"  (trong {e.device})" if e.device else ""))
        return 0 if hits else 1

    if args.device:
        dev = caps.devices.get(args.device)
        if dev is None:
            print(f"không có thiết bị '{args.device}'", file=sys.stderr)
            return 1
        print(f"{dev.name}: {', '.join(lex.aliases_of(DEVICE, dev.name)) or '(chưa có tên)'}")
        for zone in dev.zones:
            print(f"  zone {zone:11} {', '.join(lex.aliases_of('zone', zone, device=dev.name))}")
        for mode in dev.modes:
            print(f"  mode {mode:11} {', '.join(lex.aliases_of('mode', mode))}")
        for item in dev.items:
            print(f"  item {item:11} {', '.join(lex.aliases_of('item', item, device=dev.name))}")
        return 0

    by_kind: dict[str, int] = {}
    for e in lex.entries:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
    print(f"{lex.path}: {len(lex.entries)} alias")
    for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:8} {n}")
    return 0


VOICE = "Linh"     # giọng vi_VN có sẵn trên macOS


def speak(text: str) -> None:
    """Đọc câu trả lời bằng TTS của hệ điều hành.

    Chỉ để nghe thử cho giống thật — trên xe thì head unit có engine riêng, agent
    chỉ đưa chuỗi text cho nó.
    """
    if not text or not shutil.which("say"):
        return
    subprocess.Popen(["say", "-v", VOICE, text],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _print_turn(turn, show_trace: bool, voice: bool = False,
                one_shot: bool = False) -> None:
    print(f"verdict  {turn.verdict}")
    for r in turn.results:
        if r.command:
            print(f"plan     {json.dumps(r.command.to_dict(), ensure_ascii=False)}")
        if r.code:
            print(f"         {r.code}")

    if turn.tts:
        print(f"nói      {turn.tts}")
        if voice:
            speak(turn.tts)
    if turn.needs_state:
        print("         (câu hỏi trạng thái: cần state provider của thiết bị)")
    if turn.awaiting_confirm:
        # "run" là một phát rồi thoát: agent chết theo tiến trình, nên câu "ừ" của
        # lượt sau đến một agent trắng trơn. Bảo người ta trả lời trong chế độ
        # không trả lời được là chỉ dẫn sai.
        print("         → đang chờ xác nhận"
              + (" — dùng `agentcar repl` để trả lời ừ / thôi" if one_shot
                 else " (trả lời: ừ / thôi)"))
    if turn.unmatched:
        print(f"bỏ qua   {' '.join(turn.unmatched)}")
    if show_trace:
        for n in turn.trace:
            print(f"  · {n}")
        for r in turn.results:
            for n in r.notes:
                print(f"  · {n}")


STATE_FILE = Path(__file__).resolve().parent.parent / "logs" / "device-state.json"


def _agent(args) -> Agent:
    """Giả lập: trạng thái thiết bị ghi ra file để sống qua nhiều lần gọi CLI."""
    caps = load_caps(args.caps)
    path = None if getattr(args, "fresh", False) else (os.environ.get("AGENTCAR_STATE") or STATE_FILE)
    scenario = getattr(args, "scenario", None)
    monitor = MockSignalMonitor.from_yaml(scenario) if scenario else None
    return Agent(caps, state_provider=MockStateProvider(caps, path), monitor=monitor)


def cmd_run(args) -> int:
    agent = _agent(args)
    # Có kịch bản thì tín hiệu do monitor cấp, cờ --gear/--speed không còn nghĩa.
    # `run` chỉ chạy một câu nên mặc định đọc ở giây 0; --at nhảy tới mốc khác.
    if agent.monitor is not None:
        state = agent.monitor.at(args.at) if args.at is not None else None
    else:
        state = _state_from_args(args)
    turn = agent.handle(args.text, state)
    if args.json:
        print(json.dumps(turn.to_dict(), ensure_ascii=False))
    else:
        _print_turn(turn, args.trace, args.speak, one_shot=True)
    return 0 if turn.verdict == "OK" else 2


def cmd_repl(args) -> int:
    caps = load_caps(args.caps)
    agent = _agent(args)
    # state=None nghĩa là để agent hỏi monitor ở MỖI lượt — xe đổi trạng thái giữa
    # chừng thì câu sau nhận kết quả khác câu trước.
    state = None if agent.monitor is not None else _state_from_args(args)
    show_trace = args.trace
    if agent.monitor is not None:
        lap = f"  (lặp lại mỗi {agent.monitor.period:g}s)" if agent.monitor.loops else ""
        print("kịch bản " + args.scenario + lap)
        for line in agent.monitor.timeline():
            print("  " + line)
    print(f"{caps.model} — gõ câu tiếng Việt. :set gear=D speed_kmh=45 | :state | :trace | :reset | :q")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in (":q", ":quit", ":exit"):
            return 0
        if line == ":state":
            print(f"  {(state if state is not None else agent.read_state()).describe()}")
            continue
        if line == ":trace":
            show_trace = not show_trace
            print(f"  trace {'bật' if show_trace else 'tắt'}")
            continue
        if line == ":reset":
            agent.reset()
            print("  quên thiết bị của lượt trước và lệnh đang chờ")
            continue
        if line == ":pending":
            print(f"  {agent.pending.commands if agent.pending else 'không có lệnh chờ'}")
            continue
        if line.startswith(":set"):
            if state is None:
                print("  đang chạy kịch bản, tín hiệu do monitor cấp — :set không dùng được")
                continue
            for pair in line[4:].split():
                if "=" not in pair:
                    continue
                key, value = pair.split("=", 1)
                if not hasattr(state, key):
                    state.extra[key] = value
                elif key in ("speed_kmh", "battery_pct"):
                    setattr(state, key, float(value))
                elif key == "charging":
                    state.charging = value.lower() in ("true", "1", "yes")
                else:
                    setattr(state, key, value)
            print(f"  {state.describe()}")
            continue
        _print_turn(agent.handle(line, state), show_trace, args.speak)


def cmd_devices(args) -> int:
    caps = load_caps(args.caps)
    responder = Responder(caps, load_lexicon(caps))
    path = os.environ.get("AGENTCAR_STATE") or STATE_FILE
    monitor = MockSignalMonitor.from_yaml(args.scenario) if args.scenario else None
    if args.baseline:
        MockStateProvider(caps, path).seed(baseline.rows(caps, responder))
        print(baseline.describe(caps, responder))
    previous = None
    try:
        return _draw_loop(args, caps, responder, path, monitor)
    except KeyboardInterrupt:      # Ctrl-C ở giữa lúc vẽ cũng phải thoát êm
        print()
        return 0


def _draw_loop(args, caps, responder, path, monitor) -> int:
    previous = None
    while True:
        # Dựng lại provider mỗi vòng để ĐỌC LẠI file: agent đang chạy ở tiến trình
        # khác, giữ một object cũ thì bảng đứng im mãi mãi.
        snapshot = MockStateProvider(caps, path).snapshot()
        text, previous = render(
            caps, responder, snapshot,
            vehicle=monitor.read() if monitor is not None else None,
            previous=previous, show_all=args.all,
            stamp=datetime.now().strftime("%H:%M:%S"))
        if not args.watch:
            print(text)
            return 0
        print("\033[H\033[J" + text, flush=True)
        time.sleep(args.every)


def cmd_eval(args) -> int:
    caps = load_caps(args.caps)
    cases = load_cases(args.golden) if args.golden else load_cases()
    results = evaluate(caps, cases)
    print(format_eval(results))
    return 0 if all(r.passed for r in results) else 1


def cmd_config(args) -> int:
    caps = load_caps(args.caps)
    cfg = settings(caps)
    print(f"api_key    {cfg.masked_key}")
    print(f"base_url   {cfg.base_url}")
    print(f"model      {cfg.model}")
    print(f"timeout    {cfg.timeout_ms} ms  ({cfg.timeout_source})")
    print(f"enabled    {cfg.enabled}")
    print(f"→ tầng [2] {'dùng được' if cfg.usable else 'CHƯA dùng được'}"
          + ("" if cfg.usable else "  (thiếu key hoặc AGENTCAR_LLM_ENABLED=false)"))
    return 0


def cmd_serve(args) -> int:
    # Dùng chung file trạng thái với CLI: gõ câu ở terminal, xem ở trình duyệt.
    path = None if args.isolated else (os.environ.get("AGENTCAR_STATE") or STATE_FILE)
    serve(load_caps(args.caps), port=args.port, path=path, start_at_baseline=args.baseline)
    return 0


def cmd_stats(args) -> int:
    rows = load_log(args.log or LOG_PATH)
    if args.real:
        rows = only_real(rows)
    print(f"{args.log or LOG_PATH}" + ("  (chỉ lượt thật)" if args.real else ""))
    print(summarize(rows))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agentcar")
    p.add_argument("--caps", default=str(DEFAULT_CAPS))
    sub = p.add_subparsers(dest="cmd", required=True)

    li = sub.add_parser("lint", help="kiểm tra caps + lexicon")
    li.add_argument("--no-lexicon", action="store_true")
    li.set_defaults(func=cmd_lint)

    lx = sub.add_parser("lex", help="xem từ điển tiếng Việt")
    lx.add_argument("--device")
    lx.add_argument("--lookup")
    lx.set_defaults(func=cmd_lex)

    c = sub.add_parser("caps", help="xem vùng hợp lệ đã suy ra")
    c.add_argument("--device")
    c.set_defaults(func=cmd_caps)

    k = sub.add_parser("check", help="resolve + safety cho một command có cấu trúc")
    k.add_argument("device")
    k.add_argument("--action")
    k.add_argument("--zone")
    k.add_argument("--value", type=float)
    k.add_argument("--unit")
    k.add_argument("--mode")
    k.add_argument("--item")
    k.add_argument("--gear", default="P")
    k.add_argument("--speed", type=float, default=0.0)
    k.add_argument("--battery", type=float, default=100.0)
    k.add_argument("--charging", action="store_true")
    k.add_argument("--parking-brake", default="engaged")
    k.add_argument("--json", action="store_true")
    k.set_defaults(func=cmd_check)

    def add_state_flags(sp):
        sp.add_argument("--scenario", help="file kịch bản lái, thay cho --gear/--speed đứng yên")
        sp.add_argument("--gear", default="P")
        sp.add_argument("--speed", type=float, default=0.0)
        sp.add_argument("--battery", type=float, default=100.0)
        sp.add_argument("--charging", action="store_true")
        sp.add_argument("--parking-brake", default="engaged")

    r = sub.add_parser("run", help="chạy một câu tiếng Việt")
    r.add_argument("text")
    r.add_argument("--json", action="store_true")
    r.add_argument("--trace", action="store_true")
    r.add_argument("--speak", action="store_true", help="đọc câu trả lời bằng giọng vi_VN")
    r.add_argument("--fresh", action="store_true", help="bỏ trạng thái thiết bị đã lưu")
    r.add_argument("--at", type=float, help="đọc kịch bản ở giây thứ mấy (cần --scenario)")
    add_state_flags(r)
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("repl", help="gõ câu tiếng Việt liên tục")
    rp.add_argument("--trace", action="store_true")
    rp.add_argument("--speak", action="store_true", help="đọc câu trả lời bằng giọng vi_VN")
    rp.add_argument("--fresh", action="store_true", help="bỏ trạng thái thiết bị đã lưu")
    add_state_flags(rp)
    rp.set_defaults(func=cmd_repl)

    sub.add_parser("config", help="xem cấu hình tầng [2]").set_defaults(func=cmd_config)

    st = sub.add_parser("stats", help="thống kê từ log telemetry")
    st.add_argument("log", nargs="?")
    st.add_argument("--real", action="store_true", help="bỏ các lượt do script đo sinh ra")
    st.set_defaults(func=cmd_stats)

    dv = sub.add_parser("devices", help="bảng trạng thái thiết bị trong terminal")
    dv.add_argument("--watch", action="store_true", help="vẽ lại liên tục cho tới khi Ctrl-C")
    dv.add_argument("--every", type=float, default=1.0, help="giây giữa hai lần vẽ")
    dv.add_argument("--all", action="store_true", help="hiện cả thiết bị chưa biết trạng thái")
    dv.add_argument("--scenario", help="kèm một dòng tín hiệu xe đọc từ kịch bản")
    dv.add_argument("--baseline", action="store_true",
                    help="đặt mọi thiết bị về mốc xuất phát trước khi vẽ")
    dv.set_defaults(func=cmd_devices)

    sv = sub.add_parser("serve", help="giả lập khoang lái trong trình duyệt")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--baseline", action="store_true",
                    help="đặt mọi thiết bị về mốc xuất phát khi khởi động")
    sv.add_argument("--isolated", action="store_true",
                    help="phiên riêng, không dùng chung trạng thái với CLI")
    sv.set_defaults(func=cmd_serve)

    ev = sub.add_parser("eval", help="chấm trên bộ câu chuẩn tiếng Việt")
    ev.add_argument("golden", nargs="?")
    ev.set_defaults(func=cmd_eval)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
