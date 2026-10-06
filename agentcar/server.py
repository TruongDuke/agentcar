"""Giả lập khoang lái chạy tại chỗ: server stdlib + một trang web.

Mục đích là TỰ TEST CHO NHANH — thấy ngay trạng thái thiết bị đổi thế nào sau
mỗi câu, và đổi gear/tốc độ/pin bằng một cú kéo để thử luật an toàn.

Chỉ nghe trên 127.0.0.1. Không có thứ gì ở đây dành cho môi trường thật.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from . import baseline
from .agent import Agent
from .caps import Caps
from .lexicon import DEVICE, MODE, ZONE
from .safety import DEFAULT_STATE_FIELDS, VehicleState
from .state import MockStateProvider

WEB = Path(__file__).resolve().parent / "web"


class Simulator:
    """Giữ agent + trạng thái xe cho phiên giả lập.

    `path` là file trạng thái thiết bị dùng CHUNG với CLI. Có nó thì gõ câu ở
    terminal và xem ở trình duyệt là cùng một xe; trang web tự hỏi lại mỗi giây
    nên thấy ngay. Không có thì phiên này đứng riêng, như trước.
    """

    def __init__(self, caps: Caps, path: Optional[Path | str] = None,
                 start_at_baseline: bool = False):
        self.caps = caps
        self.path = Path(path) if path else None
        # Trang web hỏi snapshot mỗi giây trong khi vẫn có thể đang gửi câu nói.
        # ThreadingHTTPServer chạy hai cái đó ở hai luồng, mà cả hai đều đụng
        # agent.devices — khoá lại, nếu không có lượt ghi bị nuốt.
        self.lock = threading.Lock()
        self.agent = Agent(caps, state_provider=MockStateProvider(caps, self.path))
        self.vehicle = VehicleState()
        if start_at_baseline:
            self.agent.devices.seed(baseline.rows(caps, self.agent.responder))

    # ---------------------------------------------------------------- mô tả xe
    def layout(self) -> dict[str, Any]:
        """Danh mục thiết bị + tên tiếng Việt, để trang web tự dựng giao diện."""
        lex = self.agent.lexicon
        devices = []
        for name, dev in self.caps.devices.items():
            actions = self.caps.effective_actions(dev)
            devices.append({
                "device": name,
                "label": (lex.aliases_of(DEVICE, name) or [name])[0],
                "actions": actions,
                "zones": [{"zone": z, "label": (lex.aliases_of(ZONE, z, device=name) or [z])[0]}
                          for z in dev.zones],
                "default_zone": dev.default_zone,
                "modes": [{"mode": m, "label": (lex.aliases_of(MODE, m) or [m])[0]}
                          for m in dev.modes if m not in dev.exclude],
                "unit": dev.value.default_unit if dev.value and dev.value.is_number else None,
                "range": ([dev.value.unit().lo, dev.value.unit().hi]
                          if dev.value and dev.value.is_number and dev.value.unit() else None),
                "supported": bool(actions),
                "cloud_only": dev.cloud_only,
                "safety_gated": dev.safety_gated,
            })
        return {"model": self.caps.model, "devices": devices,
                "llm": bool(self.agent.cloud),
                # Ngân sách thời gian caps khai cho tầng edge — trang web tô màu
                # theo mốc này chứ không tự bịa một con số "nhanh" nào đó.
                "deadline_ms": (self.caps.gate or {}).get("deadline_ms"),
                "safety": [{"device": r.device, "action": r.action, "verdict": r.verdict,
                            "when": r.when} for r in self.caps.safety]}

    def _reload(self) -> None:
        """Đọc lại file trước khi nhìn vào trạng thái: tiến trình khác có thể vừa đổi."""
        if self.path is not None:
            self.agent.devices = MockStateProvider(self.caps, self.path)

    def baseline(self) -> dict[str, Any]:
        with self.lock:
            self.agent.devices.seed(baseline.rows(self.caps, self.agent.responder))
            return self._snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            self._reload()
            return self._snapshot()

    def _snapshot(self) -> dict[str, Any]:
        return {
            "vehicle": {f: self.vehicle.get(f) for f in DEFAULT_STATE_FIELDS},
            "devices": self.agent.devices.snapshot(),
            "pending": bool(self.agent.pending),
        }

    # ---------------------------------------------------------------- hành động
    def say(self, text: str) -> dict[str, Any]:
        with self.lock:
            self._reload()
            turn = self.agent.handle(text, self.vehicle)
            return self._said(text, turn)

    def _said(self, text: str, turn) -> dict[str, Any]:
        return {
            "turn": {
                "text": text,
                "verdict": turn.verdict,
                "tts": turn.tts,
                "ms": round(turn.ms, 1) if turn.ms is not None else None,
                "path": turn.path,
                "cloud_ms": round(turn.cloud_ms, 1) if turn.cloud_ms is not None else None,
                "cloud_kind": turn.cloud_kind,
                "cloud_error": turn.cloud_error,
                "label": turn.label,
                "trace": turn.trace,
                "unmatched": turn.unmatched,
                "awaiting_confirm": turn.awaiting_confirm,
                "needs_state": turn.needs_state,
                "results": [r.to_dict() for r in turn.results],
            },
            **self._snapshot(),
        }

    def set_vehicle(self, changes: dict[str, Any]) -> dict[str, Any]:
        for key, value in (changes or {}).items():
            if key in ("speed_kmh", "battery_pct"):
                setattr(self.vehicle, key, float(value))
            elif key == "charging":
                self.vehicle.charging = bool(value)
            elif key in ("gear", "parking_brake"):
                setattr(self.vehicle, key, str(value))
        return self.snapshot()

    def reset(self) -> dict[str, Any]:
        with self.lock:
            self.agent.reset()
            self.vehicle = VehicleState()
            return self._snapshot()


def make_handler(sim: Simulator):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):        # bớt ồn, đã có log riêng
            pass

        def _send(self, payload: Any, content_type="application/json", status=200):
            body = (json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    if content_type == "application/json" else payload)
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            # Trang này để SỬA RỒI XEM NGAY. Không có header này thì trình duyệt
            # giữ bản cũ, sửa index.html xong tải lại vẫn thấy y nguyên — mất
            # thời gian đi tìm lỗi ở chỗ không có lỗi.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError:
                return {}

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send((WEB / "index.html").read_bytes(), "text/html")
            if self.path == "/api/layout":
                return self._send(sim.layout())
            if self.path == "/api/snapshot":
                return self._send(sim.snapshot())
            self._send({"error": "không có đường dẫn này"}, status=404)

        def do_POST(self):
            body = self._body()
            if self.path == "/api/say":
                text = (body.get("text") or "").strip()
                if not text:
                    return self._send({"error": "thiếu text"}, status=400)
                print(f"  > {text}")
                result = sim.say(text)
                print(f"    {result['turn']['verdict']}  {result['turn']['tts']}")
                return self._send(result)
            if self.path == "/api/vehicle":
                return self._send(sim.set_vehicle(body))
            if self.path == "/api/reset":
                return self._send(sim.reset())
            if self.path == "/api/baseline":
                return self._send(sim.baseline())
            self._send({"error": "không có đường dẫn này"}, status=404)

    return Handler


def serve(caps: Caps, port: int = 8765, path: Optional[Path | str] = None,
          start_at_baseline: bool = False) -> None:
    sim = Simulator(caps, path=path, start_at_baseline=start_at_baseline)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(sim))
    print(f"Giả lập khoang lái {caps.model}: http://127.0.0.1:{port}")
    print(f"  tầng [2] LLM: {'bật' if sim.agent.cloud else 'tắt'}   (Ctrl+C để dừng)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\ndừng.")
    finally:
        server.server_close()
