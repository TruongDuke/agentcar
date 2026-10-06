"""Nối tầng [1] hiểu câu với tầng [3][4] kiểm tra, cộng vòng hội thoại xác nhận.

Chưa có tầng [2] (LLM) và tầng [5] (câu TTS cho trường hợp thành công) — câu nào
tầng edge không bắt được thì trả ESCALATE_UNKNOWN, đúng chỗ sau này cắm LLM vào.
Câu thuộc thiết bị cloud_only (nav) trả ESCALATE_ROUTED kèm target — đích đã biết
từ caps nên router chuyển thẳng, không tốn một vòng suy luận.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable, Optional

from .caps import Caps
from .catalog import VALUE_ACTIONS
from .config import LLMSettings
from .config import settings as load_settings
from .engine import decide
from .llm import CloudPath, build_cloud_path
from .lexicon import ZONE, Lexicon, load_lexicon, normalize
from .match import UNMUTE, Matcher
from .monitor import SignalMonitor
from .nlu import JointNlu, co_model, dung_chung, sang_raw
from .reasoning import RuleSet, load_rules
from .resolve import va_lenh_mo_hinh
from .plan import Code, Command, RawCommand, Result, Verdict
from .respond import Responder
from .runner import MockPlanRunner, PlanRunner
from .safety import DEFAULT_STATE_FIELDS, VehicleState, evaluate
from .assistant import Handler, CloudAssistant
from .state import (MockStateProvider, StateProvider, cham_bien,
                    da_dung_trang_thai)
from .telemetry import Recorder
from .triage import Escalation, classify

# Mức độ nghiêm trọng: cái tệ nhất quyết định verdict chung của cả câu
_SEVERITY = [Verdict.DENY, Verdict.NOT_SUPPORT, Verdict.INVALID, Verdict.ASK, Verdict.REPLY,
             Verdict.ESCALATE_UNKNOWN, Verdict.ESCALATE_ROUTED,
             Verdict.CONFIRM, Verdict.CANCELLED, Verdict.OK]

CONFIRM_TTL_S = 30.0
# Chốt 7: tầng edge bỏ qua từ ngần này chữ MANG NỘI DUNG trở lên thì đừng tin lệnh
# nó ghép ra, hỏi tầng [2]. Xem _handle_command để biết vì sao lấy số chữ bỏ qua
# làm thước đo, và tools/score_stress.py để chạy lại bảng được/mất từng ngưỡng.
LOW_COVERAGE = 7

WEEKDAYS_VI = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")


def _kind(outcome) -> str:
    if outcome.commands:
        return "commands"
    for name in ("ask", "reply", "route"):
        if getattr(outcome, name):
            return name
    return "none"

# Lệnh hiểu được nhưng thiếu thông tin — đáng để hỏi tầng suy luận trước khi hỏi
# lại người dùng.
INCOMPLETE = {Code.VALUE_REQUIRED, Code.MODE_REQUIRED, Code.ITEM_REQUIRED,
              Code.NO_DEFAULT_ACTION, Code.NO_PREVIOUS_VALUE,
              # Tầng luật GHÉP được lệnh rồi resolve bác vì một trường sai —
              # "chỉnh hướng gió xuống chân bên phải" ra INVALID_ZONE vì quạt
              # không nhận trái/phải. Cửa gọi cloud là `if not raws`, xét ở bước
              # GHÉP chứ không xét lệnh còn sống hay không, nên cả nhóm này
              # chưa bao giờ được hỏi cloud. Đo trên 120 câu: 4 câu.
              #
              # KHÔNG gộp NOT_SUPPORT vào đây: "xe không có hàng ghế 3" là câu
              # trả lời ĐÚNG, hỏi cloud chỉ tổ để nó bịa ra một vùng không tồn
              # tại. Chỉ nhận nhóm "gần hiểu được".
              Code.INVALID_ZONE, Code.INVALID_UNIT, Code.INVALID_ITEM}


@dataclass
class PendingSlot:
    """Đã hỏi 'bật cái gì?' và đang chờ người ta nói tên thiết bị.

    Phải nhớ ĐỘNG TỪ, nếu không thì "tắt" -> "tắt cái gì?" -> "đèn viền" sẽ chạy
    default_action là BẬT đèn viền, ngược hẳn ý người nói.
    """

    actions: list[str]
    verb: str
    created: float
    ttl: float = 30.0

    def expired(self, now: float) -> bool:
        return now - self.created > self.ttl


@dataclass
class PendingZone:
    """Đã hỏi "vùng nào?" và đang chờ người ta nêu vùng.

    Khác PendingSlot (chờ TÊN THIẾT BỊ) và Pending (chờ ừ/không): ở đây thiết bị
    và hành động đã rõ, chỉ thiếu vùng. Giữ nguyên RawCommand để lượt sau chỉ việc
    điền zone rồi chạy — không dựng lại câu, không đoán lại ý.
    """

    raw: "RawCommand"
    created: float
    ttl: float = 30.0

    def expired(self, now: float) -> bool:
        return now - self.created > self.ttl


@dataclass
class Pending:
    """Lệnh đang chờ người dùng xác nhận."""

    commands: list[Command]
    reason: str
    created: float
    ttl: float = CONFIRM_TTL_S

    def expired(self, now: float) -> bool:
        return now - self.created > self.ttl


@dataclass
class Turn:
    text: str
    verdict: str
    results: list[Result] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    awaiting_confirm: bool = False
    speech: list[str] = field(default_factory=list)
    needs_state: bool = False   # câu truy vấn: thiếu trạng thái thiết bị để trả lời
    # --- số liệu cho telemetry
    ms: Optional[float] = None  # tổng thời gian của lượt, tính cả tầng [2]
    label: str = ""             # nhãn triage
    checkpoint: int = 0         # dừng ở chốt nào trong _handle_command
    cloud_ms: Optional[float] = None
    cloud_kind: Optional[str] = None
    cloud_error: Optional[str] = None

    @property
    def tts(self) -> str:
        return " ".join(self.speech)

    @property
    def path(self) -> str:
        """Fast path lo được, hay đã phải hỏi cloud. Đây là khác biệt tốn tiền."""
        return "cloud" if self.cloud_ms is not None else "edge"

    @property
    def plan(self) -> list[dict]:
        return [r.command.to_dict() for r in self.results if r.ok and r.command]

    def to_dict(self) -> dict:
        out = {"verdict": self.verdict, "results": [r.to_dict() for r in self.results]}
        if self.ms is not None:
            out["ms"] = round(self.ms, 1)
            out["path"] = self.path
        if self.cloud_ms is not None:
            out["cloud_ms"] = round(self.cloud_ms, 1)
            out["cloud_kind"] = self.cloud_kind
        if self.cloud_error:
            out["cloud_error"] = self.cloud_error
        if self.label and self.label != Escalation.NONE:
            out["label"] = self.label
        if self.speech:
            out["tts"] = self.tts
        if self.needs_state:
            out["needs_state"] = True
        if self.awaiting_confirm:
            out["awaiting_confirm"] = True
        if self.unmatched:
            out["unmatched"] = self.unmatched
        return out


def _bo_lenh_bi_de(results: list[Result], trace: list[str]) -> list[Result]:
    """Bỏ lệnh bị lệnh sau trong CÙNG câu đè lên, giữ lệnh cuối.

    Đè nhau khi trùng (thiết bị, vùng) và:
      - cùng nhóm mode loại trừ  ("lấy gió trong" rồi "lấy gió ngoài")
      - cùng đặt mức             ("để 20 độ rồi 24 độ")
    Không đụng tới lệnh khác nhóm: "lấy gió trong" và "thổi mặt" cùng quạt gió nhưng
    hai nhóm khác nhau, phải giữ cả hai.
    """
    def khoa(r: Result):
        c = r.command
        if c is None or not r.ok:
            return None
        if c.mode_group:
            return (c.device, c.zone, "mode", c.mode_group)
        if c.action == "set_level":
            return (c.device, c.zone, "muc")
        return None

    cuoi: dict = {}
    for i, r in enumerate(results):
        k = khoa(r)
        if k is not None:
            cuoi[k] = i
    bo = {i for i, r in enumerate(results)
          if (k := khoa(r)) is not None and cuoi[k] != i}
    if not bo:
        return results
    trace.append("bỏ lệnh bị lệnh sau đè: "
                 + ", ".join(f"{results[i].command.device}/{results[i].command.mode or 'mức'}"
                             for i in sorted(bo)))
    return [r for i, r in enumerate(results) if i not in bo]


def _worst(results: list[Result]) -> str:
    return next((v for v in _SEVERITY if any(r.verdict == v for r in results)), Verdict.OK)


class Agent:
    def __init__(self, caps: Caps, lex: Optional[Lexicon] = None,
                 confirm_ttl_s: float = CONFIRM_TTL_S,
                 clock: Callable[[], float] = time.monotonic,
                 state_provider: Optional[StateProvider] = None,
                 llm: Optional[CloudPath] = None,
                 llm_settings: Optional[LLMSettings] = None,
                 recorder: Optional[Recorder] = None,
                 handlers: Optional[dict[str, Handler]] = None,
                 runner: Optional[PlanRunner] = None,
                 monitor: Optional[SignalMonitor] = None,
                 nlu: Optional["JointNlu"] = None,
                 low_coverage: int = LOW_COVERAGE):
        self.caps = caps
        self.low_coverage = low_coverage
        # Tầng [1b]: model NLU trên xe. Mặc định bật khi có trọng số; thiếu file
        # thì None và agent chạy y như trước. Truyền nlu=False để tắt hẳn.
        self.nlu = (None if nlu is False
                    else nlu if nlu is not None
                    else (dung_chung() if co_model() else None))
        self.lexicon = lex or load_lexicon(caps)
        self.rules: RuleSet = load_rules()
        self.matcher = Matcher(caps, self.lexicon, vague=self.rules.vague)
        self.responder = Responder(caps, self.lexicon)
        self.devices = state_provider if state_provider is not None else MockStateProvider(caps)
        # Không có key hoặc chưa bật thì slow là None — agent không gọi ra ngoài.
        # gate trong caps: câu quá ngắn thì không đoán, không đẩy lên cloud.
        self.gate = dict(caps.gate or {})
        self.vehicle_snapshot: dict = {}
        self.recorder = recorder if recorder is not None else Recorder.from_env()
        self.runner: PlanRunner = runner if runner is not None else MockPlanRunner()
        # Không có monitor thì coi như xe đỗ — đúng mặc định cũ, nên mọi chỗ
        # gọi handle() không truyền state vẫn chạy y như trước.
        self.monitor = monitor
        self.cloud = llm if llm is not None else build_cloud_path(
            caps, self.lexicon, llm_settings or load_settings(caps))

        # Đích khai trong reasoning.vi.yaml thì phải có người nhận, nếu không chuyển
        # đi là chuyển vào chỗ trống và người dùng nghe im lặng.
        self.handlers: dict[str, Handler] = dict(handlers or {})
        if self.rules.route_to and self.rules.route_to not in self.handlers and self.cloud:
            assistant = CloudAssistant(
                client=self.cloud.client, settings=self.cloud.settings,
                city=os.environ.get("AGENTCAR_CITY") or self.rules.city)
            assistant.prefetch()        # thời tiết lấy sẵn ở nền, khỏi bắt chờ
            self.handlers[self.rules.route_to] = assistant
        self.confirm_ttl_s = confirm_ttl_s
        self.clock = clock
        self.last_device: Optional[str] = None
        self.pending: Optional[Pending] = None
        self.pending_slot: Optional[PendingSlot] = None
        self.pending_zone: Optional[PendingZone] = None
        # Mức cuối cùng CHÍNH AGENT đặt cho từng thiết bị. Không phải trạng thái
        # thật của xe: người dùng vặn núm tay thì ở đây không biết. Dùng để khôi
        # phục sau khi tắt tiếng, và chỉ vậy.
        self.last_level: dict[str, float] = {}
        self.history: list[str] = []      # vài lượt gần nhất, gửi kèm cho tầng [2]

    def _voice(self, turn: Turn) -> Turn:
        for result in turn.results:
            state = None
            # Lệnh trùng trạng thái cũng cần state để đọc ra câu trả lời, y như query.
            if result.command is not None and (result.da_dung or result.cham_bien
                                               or result.command.action == "query"):
                state = self.devices.get(result.command.device, result.command.zone)
            speech = self.responder.say(result, state)
            if speech.text:
                turn.speech.append(speech.text)
            if speech.needs_state:
                turn.needs_state = True
        return turn

    def read_state(self) -> VehicleState:
        """Trạng thái xe tại đúng lúc này.

        Người gọi truyền sẵn state thì tôn trọng cái đó — eval và test cần dựng
        tình huống cố định. Không truyền thì hỏi monitor, và hỏi LẠI ở mỗi lượt:
        đó là chỗ duy nhất biết được xe đã chuyển số trong lúc chờ xác nhận.
        """
        return self.monitor.read() if self.monitor is not None else VehicleState()

    # ------------------------------------------------------------ hội thoại
    def handle(self, text: str, state: Optional[VehicleState] = None) -> Turn:
        """Bọc ngoài để đo giờ và ghi telemetry cho mọi đường trả về."""
        started = time.monotonic()
        turn = self._handle(text, state)
        # Trước đây con số này chỉ đi vào telemetry rồi mất. Người gọi cũng cần:
        # caps khai gate.deadline_ms cho tầng edge, không trả ms ra thì không ai
        # đối chiếu được lượt vừa rồi có kịp ngân sách đó không.
        turn.ms = (time.monotonic() - started) * 1000
        self._record(turn, turn.ms)
        return turn

    def _record(self, turn: Turn, ms: float) -> None:
        self.recorder.record({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "label": turn.label or "-",
            "checkpoint": turn.checkpoint,
            "path": "cloud" if turn.cloud_ms is not None else "edge",
            "ms": round(ms, 1),
            "cloud_ms": round(turn.cloud_ms, 1) if turn.cloud_ms is not None else None,
            "cloud_kind": turn.cloud_kind,
            "cloud_error": turn.cloud_error,
            "verdict": turn.verdict,
            "codes": [r.code for r in turn.results if r.code],
            "plan": [{"device": r.command.device, "action": r.command.action}
                     for r in turn.results if r.command],
            "model": self.cloud.settings.model if self.cloud else None,
            "unmatched": len(turn.unmatched),
        }, text=turn.text)

    def _handle(self, text: str, state: Optional[VehicleState] = None) -> Turn:
        state = state if state is not None else self.read_state()
        now = self.clock()
        trace: list[str] = []

        if self.pending is not None and self.pending.expired(now):
            self.pending = None
            trace.append(f"lệnh chờ đã quá hạn {self.confirm_ttl_s:.0f}s, bỏ")

        if self.pending_zone is not None and self.pending_zone.expired(now):
            self.pending_zone = None

        if self.pending_zone is not None:
            zone = self._zone_from(text, self.pending_zone.raw.device)
            if zone is not None:
                waiting, self.pending_zone = self.pending_zone, None
                raw = replace(waiting.raw, zone=zone)
                trace.append(f"điền vùng đã hỏi: {zone}")
                return self._run_raws(text, [raw], state, trace)
            self.pending_zone = None      # nói chuyện khác thì thôi, đừng bám

        if self.pending is not None:
            answer = self.lexicon.answer(text)
            if answer is True:
                return self._apply_pending(text, state, trace)
            if answer is False:
                self.pending = None
                return self._voice(Turn(
                    text=text, verdict=Verdict.CANCELLED, trace=trace + ["người dùng từ chối"],
                    results=[Result(verdict=Verdict.CANCELLED)]))
            # C4: câu HỎI không huỷ lệnh đang chờ — hỏi lại cho rõ rồi mới quyết
            # là hành vi bình thường. Chỉ lệnh mới mới thay thế.
            held, self.pending = self.pending, None
            turn = self._handle_command(text, state, trace)
            if turn.results and all(
                r.command is not None and r.command.action == "query" for r in turn.results
            ):
                self.pending = held
                turn.awaiting_confirm = True
                turn.trace.append("giữ lệnh đang chờ: câu hỏi không huỷ xác nhận")
            else:
                turn.trace.append("câu mới thay thế lệnh đang chờ")
            return turn

        return self._handle_command(text, state, trace)

    def _apply_pending(self, text: str, state: VehicleState, trace: list[str]) -> Turn:
        """Đồng ý rồi vẫn phải KIỂM LẠI trạng thái xe — xe có thể đã chuyển số
        trong lúc chờ, lúc đó lệnh phải bị từ chối chứ không được chạy."""
        pending = self.pending
        assert pending is not None
        self.pending = None
        results = [evaluate(self.caps, cmd, state, confirmed=True) for cmd in pending.commands]
        self._commit(results)
        return self._voice(Turn(
            text=text, verdict=_worst(results), results=results,
            trace=trace + ["xác nhận lệnh đang chờ, kiểm lại trạng thái xe tại thời điểm đồng ý"]))

    def _context(self) -> str:
        """Ngữ cảnh gửi kèm cho tầng [2] — thứ giúp hiểu câu nói tắt.

        Tầng nhận dạng mẫu câu không cần cái này; tầng suy luận thì không có nó là
        chịu chết với "tăng thêm nữa", "cái đó tắt đi", "để lại như lúc nãy".
        """
        # Giờ thì agent biết thừa — gửi kèm để khỏi phải nói "em chưa xem được".
        # Thứ phải ghi BẰNG TIẾNG VIỆT: ghi "(Tuesday)" thì model dịch nhầm thành
        # "thứ Hai" (đã gặp thật).
        now = datetime.now().astimezone()
        lines = [f"Thời điểm: {now:%Y-%m-%d %H:%M}, {WEEKDAYS_VI[now.weekday()]}"]
        lines += ["Trạng thái xe: " + ", ".join(
            f"{f}={self.vehicle_snapshot.get(f)}" for f in DEFAULT_STATE_FIELDS)]

        known = self.devices.snapshot() if hasattr(self.devices, "snapshot") else []
        if known:
            bits = []
            for st in known:
                where = f"/{st['zone']}" if st["zone"] else ""
                what = []
                if st["on"] is not None:
                    what.append("bật" if st["on"] else "tắt")
                if st["value"] is not None:
                    what.append(f"{st['value']}{st['unit'] or ''}")
                what += list(st["modes"].values())
                if st["item"]:
                    what.append(st["item"])
                bits.append(f"{st['device']}{where}={' '.join(what)}")
            lines.append("Thiết bị đang biết: " + "; ".join(bits))
        if self.last_level:
            lines.append("Mức trước khi tắt: " + ", ".join(
                f"{d}={v}" for d, v in self.last_level.items()))
        if self.history:
            lines.append("Mấy lượt gần nhất: " + " | ".join(self.history[-3:]))
        if self.last_device:
            lines.append(f"Thiết bị vừa nhắc tới: {self.last_device}")
        return "\n".join(lines)

    def _tra_loi_tu_nguon(self, text: str, trace: list[str]) -> Optional[Turn]:
        """Trợ lý có nguồn thật cho câu này thì trả lời ngay, không qua cloud."""
        handler = self.handlers.get(self.rules.route_to or "")
        if handler is None or not getattr(handler, "co_nguon", None):
            return None
        if not handler.co_nguon(text):
            return None
        reply = handler.answer(text)
        if not reply:
            return None
        trace.append(f"{self.rules.route_to}: có nguồn thật, trả lời tại chỗ")
        return self._voice(Turn(text=text, verdict=Verdict.REPLY, trace=trace,
                                results=[Result(verdict=Verdict.REPLY, code=Code.REPLY,
                                                reason=reply)]))

    def _khong_co_nguon(self, text: str) -> Optional[str]:
        """Câu hỏi chủ đề cần số liệu sống mà hệ không có nguồn -> trả về tên chủ đề.

        caps khai needs_live_data; trợ lý chung nói nó phục vụ được cái nào. Hiện chỉ
        thời tiết là có nguồn thật.
        """
        bare = normalize(text)
        chu_de = next((k for k in self.rules.needs_live_data if normalize(k) in bare), None)
        if chu_de is None:
            return None
        handler = self.handlers.get(self.rules.route_to or "")
        if handler is not None and getattr(handler, "co_nguon", None) and handler.co_nguon(text):
            return None                      # có nguồn thật -> để trợ lý trả lời
        return chu_de

    def _too_short(self, text: str) -> bool:
        """gate.min_tokens trong caps. Câu rỗng thì luôn chặn, bất kể gate bật hay tắt."""
        count = len(normalize(text).split())
        if count == 0:
            return True
        return bool(self.gate.get("enabled")) and count < int(self.gate.get("min_tokens") or 0)

    def _handle_command(self, text: str, state: VehicleState, trace: list[str]) -> Turn:
        self.vehicle_snapshot = {f: state.get(f) for f in DEFAULT_STATE_FIELDS}
        if self._too_short(text):
            return self._voice(Turn(
                text=text, verdict=Verdict.INVALID,
                label="gate", checkpoint=1,
                trace=trace + [f"gate: câu quá ngắn (min_tokens={self.gate.get('min_tokens')})"],
                results=[Result(verdict=Verdict.INVALID, code=Code.TOO_SHORT,
                                reason="câu quá ngắn để đoán")]))

        match = self.matcher.match(text, previous_device=self.last_device)
        label = classify(match)
        # Ghi rõ dòng trace thuộc bước nào: đọc "không xác định được thiết bị" mà
        # kết quả cuối lại ra hvac thì rất dễ tưởng là lỗi.
        trace = trace + [f"[1] {note}" for note in match.trace]
        raws = match.commands
        unreachable = timed_out = False
        cloud_ms = cloud_kind = cloud_error = None
        checkpoint = 2

        # Trả lời cho câu hỏi "bật cái gì?": chỉ có tên thiết bị, không có động từ.
        slot, self.pending_slot = self.pending_slot, None
        if slot is not None and not slot.expired(self.clock()) and raws and not match.has_verb:
            for raw in raws:
                dev = self.caps.devices.get(raw.device)
                if dev is None:
                    continue
                allowed = self.caps.effective_actions(dev)
                wanted = next((a for a in slot.actions if a in allowed), None)
                if wanted:
                    raw.action = wanted
            trace.append(f"áp động từ đã hỏi: {slot.verb}")

        # Hai lớp dưới đây tự trả lời được, không cần cloud — và nhờ vậy vẫn chạy
        # khi mất mạng. Xem agentcar/triage.py để biết vì sao chỉ hai lớp này.
        if match.conditional:
            return self._voice(Turn(
                text=text, verdict=Verdict.INVALID,
                label=label, checkpoint=3,
                trace=trace + ["điều kiện/hẹn giờ: từ chối tại chỗ, không gọi cloud"],
                results=[Result(verdict=Verdict.INVALID, code=Code.NOT_SCHEDULABLE,
                                reason="câu có điều kiện/hẹn giờ")]))

        # Tham chiếu mơ hồ mà KHÔNG suy ra được thiết bị: hỏi lại tại chỗ, 0ms.
        # Điều kiện "không suy ra được" giữ cho "cái đó tắt đi" vẫn chạy như cũ.
        if not raws and match.vague:
            asked = self._ask_about_last_device(text, match, trace)
            if asked is not None:
                return asked


        # Hỏi số liệu sống mà KHÔNG ai có nguồn thì trả lời thẳng trên xe. Gọi cloud
        # cũng chỉ để nghe "chưa xem được" — tốn ~900ms và tiền cho một câu trả lời
        # biết trước. Thời tiết KHÔNG rơi vào đây vì có nguồn thật (Open-Meteo).
        if not raws:
            # Có nguồn thật (thời tiết) thì gọi thẳng trợ lý, bỏ luôn vòng cloud phân
            # loại: nhận ra câu hỏi thời tiết chỉ là khớp từ khoá, làm được trên xe.
            san = self._tra_loi_tu_nguon(text, trace)
            if san is not None:
                return self._stamp(san, label, 2)

            chua_xem = self._khong_co_nguon(text)
            if chua_xem is not None:
                trace.append(f"hỏi số liệu sống, không có nguồn: '{chua_xem}'")
                return self._stamp(self._voice(Turn(
                    text=text, verdict=Verdict.REPLY, trace=trace,
                    results=[Result(verdict=Verdict.REPLY, code=Code.REPLY,
                                    reason=f"Em chưa xem được {chua_xem} ạ.")])),
                    label, 2)

        # Tầng [1b] — model NLU trên xe, đứng TRƯỚC cloud: ~4ms, không tốn mạng, và
        # bắt đúng nhóm tầng luật bó tay (nói tự nhiên, tiếng lóng, trộn Anh-Việt).
        #
        # TODO: hiện chỉ chạy khi tầng luật ra RỖNG. Tầng luật ra lệnh HỎNG thì nó
        # chặn mất cửa: "sấy cửa kính" bị đọc thành window-không-động-từ trong khi
        # Tầng [1b] — model NLU trên xe, đứng TRƯỚC cloud: ~4ms, không tốn mạng, và
        # bắt đúng nhóm tầng luật bó tay (nói tự nhiên, tiếng lóng, trộn Anh-Việt).
        #
        # TODO: hiện chỉ chạy khi tầng luật ra RỖNG. Tầng luật ra lệnh HỎNG thì nó
        # chặn mất cửa: "sấy cửa kính" bị đọc thành window-không-động-từ trong khi
        # model đọc đúng defrost.turn_on @1.00. Thử cho nhường khi tầng luật hiểu
        # dở dang VÀ model chọn thiết bị khác — vỡ 8 test ở luồng hỏi lại, cần làm
        # cẩn thận hơn nên đã lùi.
        # ĐÃ THỬ, KHÔNG ĂN THUA: lấy kết luận M11 của tầng luật ("nhắc tên thiết bị
        # nhưng đang nói VỀ nó") làm tín hiệu nghi ngờ, để đòi model chắc hơn mới
        # cho ghi đè. Ý tưởng là M11 có ngữ cảnh cả câu, thứ điểm softmax không có.
        # Đo ra: M11 nổ trên 49,3% số câu tầng luật bỏ sót — nó không chỉ ra câu
        # đáng ngờ, nó chỉ ra "câu tầng luật chịu thua", đúng bằng dân số tầng này
        # sinh ra để phục vụ. Siết 0,80->0,85 bên M11 mất 35 câu, nới 0,80->0,65
        # bên còn lại được 45; ròng +10 trên 1828. Số lệnh THẬT SỰ xuống xe ở bộ
        # phủ định đứng yên 15/137 ở cả 0,65 · 0,80 · 0,90. Đừng thử lại bằng M11.
        if not raws and self.nlu is not None and match.mac_ke:
            trace.append("mặc kệ: người nói bảo đừng động vào — tầng [1b] không ghi đè")
        elif not raws and self.nlu is not None and match.orphan_verb:
            # Tầng luật nói rõ "nghe được động từ, KHÔNG rõ thiết bị". Model
            # không có lớp "không phải lệnh" nên nó sẽ đoán một thiết bị nào đó —
            # "bật đèn" ra đèn trần, "tắt phía trước đi" ra một lệnh thật. Chỗ
            # này để cloud lo (có digest, có ngữ cảnh) hoặc hỏi lại người dùng.
            trace.append("thiếu thiết bị: tầng [1b] không đoán thay, để cloud hoặc hỏi lại")
        elif not raws and self.nlu is not None:
            nguong = float(self.caps.nlu.get("nguong", 0.0))
            doc = [sang_raw(self.caps, self.lexicon, c)
                   for c in self.nlu.read(text, nguong=nguong)]
            doc = [r for r in doc if r is not None]
            if doc:
                raws = doc
                trace.append("tầng [1b] NLU: "
                             + ", ".join(f"{r.device}.{r.action}" for r in doc))

        # Tầng [2] chỉ chạy khi tầng edge bó tay — câu thường không tốn vòng gọi nào.
        if not raws and self.cloud is not None:
            outcome = self.cloud.interpret(text, context=self._context())
            note = f"tầng [2] {self.cloud.settings.model}: {outcome.elapsed_ms:.0f}ms"
            trace.append(note if outcome.ok else f"{note} — {outcome.error}")
            raws = outcome.commands
            for r in raws:
                r, sua = va_lenh_mo_hinh(self.caps, r)
                for m in sua:
                    trace.append(f"vá lệnh cloud: {m}")
            unreachable, timed_out = outcome.unreachable, outcome.timed_out

            cloud_ms, cloud_kind, cloud_error = outcome.elapsed_ms, _kind(outcome), outcome.error
            if not raws:
                spoken = self._cloud_reply(text, outcome, trace)
                if spoken is not None:
                    return self._stamp(spoken, label, 5, cloud_ms, cloud_kind, cloud_error)

        # Hỏi lại "bật cái gì?" là NƯỚC CUỐI, không phải nước đầu. Trước đây nhánh
        # này return ngay sau tầng luật, tức chặn mất CẢ tầng [1b] lẫn tầng [2]:
        # "Cho equalizer lên màn hình" bị hỏi lại trong khi cloud đọc đúng
        # screen_control.open item=equalizer, mà cloud chưa bao giờ được gọi.
        # Đo trên 120 câu edge bó tay: 23 câu rơi vào kiểu này.
        #
        # Hỏi lại tốn một lượt nói của người dùng — đắt hơn 900ms chờ cloud.
        if not raws and match.orphan_verb:
            self.pending_slot = PendingSlot(actions=match.orphan_actions,
                                            verb=match.orphan_verb, created=self.clock())
            # chữ gợi ý đã được dùng để dựng câu hỏi, đừng báo là "bỏ qua"
            leftover = [w for w in match.unmatched if w != match.orphan_hint]
            return self._stamp(self._voice(Turn(
                text=text, verdict=Verdict.ASK, trace=trace + ["thiếu thiết bị: hỏi tại chỗ"],
                unmatched=leftover,
                results=[Result(verdict=Verdict.ASK, code=Code.DEVICE_REQUIRED,
                                verb=match.orphan_verb, hint=match.orphan_hint,
                                actions=match.orphan_actions,
                                reason=f"nghe được '{match.orphan_verb}' nhưng chưa rõ thiết bị")])),
                label, 4, cloud_ms, cloud_kind, cloud_error)

        # Chốt 7: tầng edge GHÉP ĐƯỢC lệnh nhưng bỏ qua quá nhiều chữ mang nội dung.
        # "Ghép được lệnh" không đồng nghĩa "hiểu đúng câu": nó chỉ cần nhặt trúng
        # vài từ khoá là ra lệnh, kể cả khi phần quan trọng nhất nằm trong đám chữ
        # bị vứt. Đo trên 500 câu stress: bỏ qua ≤2 chữ thì đúng 76.5%, bỏ qua ≥7
        # chữ chỉ còn 23.8%.
        #
        # Cloud im hoặc mất mạng thì GIỮ NGUYÊN lệnh của tầng edge — ngưỡng này chỉ
        # đổi thứ tự ưu tiên, không được biến mất mạng thành không phản hồi. Cũng
        # chỉ nhận khi cloud trả về LỆNH: để cloud lấy 'reply' đè lên một lệnh fast
        # path đã hiểu đúng thì lợi bất cập hại.
        # cloud_ms is None = chưa gọi cloud lượt này. MỘT lượt nói chỉ được một
        # vòng cloud: caps khai deadline_ms=1200 mà một vòng đo thật đã p50 903ms,
        # p90 1275ms — gọi hai lần là chắc chắn vượt trần, và tốn gấp đôi tiền.
        # Ca dính: câu edge trượt hoàn toàn thì gần như luôn có nhiều chữ không
        # khớp, nên điều kiện low_coverage thoả ngay sau khi nhánh trên vừa gọi.
        if (raws and self.cloud is not None and cloud_ms is None
                and len(match.unmatched) >= self.low_coverage):
            outcome = self.cloud.interpret(text, context=self._context())
            trace.append(f"bỏ qua {len(match.unmatched)} chữ (≥{self.low_coverage})"
                         f" → tầng [2]: {outcome.elapsed_ms:.0f}ms"
                         + ("" if outcome.ok else f" — {outcome.error}"))
            cloud_ms, cloud_kind, cloud_error = outcome.elapsed_ms, _kind(outcome), outcome.error
            if outcome.commands:
                raws = outcome.commands
                checkpoint = 7
            else:
                trace.append("tầng [2] không ra lệnh — giữ lệnh của tầng edge")

        if not raws:
            # Mất mạng khác hẳn "không hiểu": phải nói ra, im lặng là tệ nhất.
            code = (Code.LLM_UNAVAILABLE if unreachable
                    else Code.LLM_TIMEOUT if timed_out
                    else Code.ESCALATE_UNKNOWN)
            reason = ("không gọi được tầng suy luận" if unreachable
                      else "tầng suy luận quá hạn" if timed_out
                      else "tầng edge không khớp — cần tầng suy luận")
            return self._stamp(self._voice(Turn(
                        text=text, verdict=Verdict.ESCALATE_UNKNOWN, trace=trace,
                        unmatched=match.unmatched,
                        results=[Result(verdict=Verdict.ESCALATE_UNKNOWN, code=code, reason=reason)])),
                        label, 5, cloud_ms, cloud_kind, cloud_error)

        results: list[Result] = []
        for raw in raws:
            if raw.action == UNMUTE:
                remembered = self.last_level.get(raw.device)
                if remembered is None:
                    results.append(Result(verdict=Verdict.INVALID, code=Code.NO_PREVIOUS_VALUE,
                                          reason=f"{raw.device}: chưa biết mức trước khi tắt"))
                    self.last_device = raw.device
                    continue
                raw = RawCommand(device=raw.device, action="set_level", zone=raw.zone,
                                 value=remembered, unit=raw.unit)
            results.append(decide(self.caps, raw, state))

        # X4: câu nhiều mệnh đề, có mệnh đề ra lệnh được và mệnh đề chỉ ra lệnh DỞ
        # DANG thì bỏ mệnh đề dở dang. "cái quạt ở nhà anh ĐỂ đâu rồi... bật sưởi ghế
        # lái đi" — chữ "để" bị nhận là set_level nên sinh lệnh quạt thiếu giá trị;
        # hỏi "đặt quạt mức bao nhiêu" trong khi người ta đang nói về ghế là vô nghĩa.
        if len(results) > 1 and any(r.ok for r in results) \
                and any(r.code in INCOMPLETE for r in results):
            dropped = [r for r in results if r.code in INCOMPLETE]
            results = [r for r in results if r.code not in INCOMPLETE]
            trace.append("bỏ mệnh đề dở dang: "
                         + ", ".join(str(r.device) for r in dropped))

        # Hai lệnh trong CÙNG một câu đè lên nhau thì chỉ nói lệnh cuối. "lấy gió
        # trong rồi lấy gió ngoài" — hai chế độ loại trừ nhau, catalog đã biết điều
        # đó qua mode_group. Không gộp thì agent nói "Đã chuyển sang lấy gió trong ạ.
        # Đã chuyển sang lấy gió ngoài ạ." trong khi xe chỉ ở lấy gió ngoài: nói làm
        # hai việc, thực tế một.
        results = _bo_lenh_bi_de(results, trace)

        # Lệnh dở dang mà câu lại có tham chiếu mơ hồ: hỏi xác nhận tại chỗ thay vì
        # hỏi "đặt mức bao nhiêu" — người ta nói "cái kia" là đang chỉ thiết bị, chưa
        # nói mức nào.
        if match.vague and results and all(r.code in INCOMPLETE for r in results):
            asked = self._ask_about_last_device(text, match, trace)
            if asked is not None:
                return asked

        # Fast path ra lệnh DỞ DANG (thiếu giá trị/chế độ/mục) thì nhường tầng [2]:
        # "để lại như lúc nãy" mà hỏi "đặt mức bao nhiêu" là vô nghĩa — cloud có
        # ngữ cảnh nên biết mức cũ là bao nhiêu.
        if (self.cloud is not None and cloud_ms is None
                and results and all(r.code in INCOMPLETE for r in results)
                and not self._vung_xe_khong_co(raws)):
            outcome = self.cloud.interpret(text, context=self._context())
            trace.append(f"lệnh dở dang → tầng [2]: {outcome.elapsed_ms:.0f}ms"
                         + ("" if outcome.ok else f" — {outcome.error}"))
            cloud_ms, cloud_kind, cloud_error = outcome.elapsed_ms, _kind(outcome), outcome.error
            checkpoint = 6
            if outcome.commands:
                results = [decide(self.caps, raw, state) for raw in outcome.commands]
            else:
                spoken = self._cloud_reply(text, outcome, trace)
                if spoken is not None:
                    return self._stamp(spoken, label, 6, cloud_ms, cloud_kind, cloud_error)

        self._commit(results)

        self.history.append(f"'{text}' -> " + (", ".join(
            f"{r.command.device}.{r.command.action}" for r in results if r.command) or "không có lệnh"))
        self.history = self.history[-5:]

        verdict = _worst(results)
        awaiting = False
        if verdict == Verdict.CONFIRM:
            need = [r for r in results if r.verdict == Verdict.CONFIRM and r.command]
            self.pending = Pending(commands=[r.command for r in need], reason=need[0].reason,
                                   created=self.clock(), ttl=self.confirm_ttl_s)
            awaiting = True

        return self._stamp(
            self._voice(Turn(text=text, verdict=verdict, results=results, trace=trace,
                             unmatched=match.unmatched, awaiting_confirm=awaiting)),
            label, 5 if cloud_ms is not None and checkpoint not in (6, 7) else checkpoint,
            cloud_ms, cloud_kind, cloud_error)

    # ĐÃ THỬ, HOÀ: khi cloud chọn một tên gần nghĩa (journey thay vì
    # trip_settings, chime thay vì ring), tin CHUỖI KHỚP của tầng luật hơn —
    # tầng luật khớp chuỗi nên ở đúng chỗ này nó không suy diễn nhầm.
    #
    # Ba ca mẫu sửa đúng hết, nhưng đo trên 400 câu: luật nổ 39 lượt, 15 ĐƯỢC,
    # 11 MẤT, 13 sai cả hai. Gần như tung đồng xu, và chỉ số chung tụt 1 điểm.
    #
    # Vì sao: điều kiện "câu chứa ĐÚNG MỘT tên khác" thoả GIẢ TẠO. "Bật điều
    # hòa khu đằng sau tài xế" có hai chữ chỉ vùng, mà tầng luật chỉ quét ra
    # "tài xế" — thấy đúng một nên sửa rear thành driver, hỏng. Muốn làm được
    # thì phải biết CHỮ NÀO gắn với thiết bị nào trong câu, tức phải phân tích
    # cú pháp, chứ không đếm được là xong.
    def _vung_xe_khong_co(self, raws) -> bool:
        """Câu nêu một vùng mà XE KHÔNG CÓ (hàng ghế 3, ghế giữa).

        Hai loại "vùng không hợp lệ" trông giống nhau ở mã VA_INVALID_ZONE nhưng
        phải xử khác hẳn:

          "chỉnh hướng gió xuống chân BÊN PHẢI" — bên phải có thật, chỉ là quạt
              không nhận. Hỏi cloud là đúng, nó biết quy về vùng hợp lệ.
          "bật sưởi ghế HÀNG 3"                 — xe không có hàng 3. Từ chối là
              câu trả lời ĐÚNG; hỏi cloud chỉ tổ để nó bịa ra một vùng khác rồi
              sưởi nhầm ghế. (Đã lọt một lần đúng như vậy.)

        Phân biệt bằng chính caps: vùng nào không thuộc `zones` của BẤT KỲ thiết
        bị nào thì xe không có nó, chấm hết.
        """
        khong_co = self.lexicon.vung_xe_khong_co
        return any(r.zone in khong_co for r in raws if r.zone)

    def _ask_about_last_device(self, text: str, match, trace: list[str]) -> Optional[Turn]:
        """'chỉnh cái kia lên' -> "Anh/chị muốn chỉnh đèn viền phải không ạ?"

        Nếu dựng được lệnh hoàn chỉnh thì đưa vào hàng chờ xác nhận, để người dùng
        trả lời "ừ" là chạy luôn — dùng lại đúng cơ chế xác nhận an toàn.
        """
        if not self.last_device:
            return None
        allowed = self.caps.effective_actions(self.caps.devices[self.last_device])
        seen = list(match.orphan_actions) + list(match.verbs)
        # Ưu tiên action không cần giá trị: "chỉnh cái kia lên" thì "lên" (increase)
        # dùng được ngay, còn set_level thì lại phải hỏi thêm mức bao nhiêu.
        # Thiết bị MỞ/ĐÓNG chứ không bật/tắt (cốp, cốp trước, nắp sạc): "bật cái
        # kia lên" nghe ra turn_on, mà cốp trước chỉ có `open`. Không quy đổi thì
        # không chọn được action nào, không dựng được lệnh, không đặt hàng chờ —
        # và câu "ừ" sau đó rơi vào hư không. _build đã quy đổi chỗ khác rồi,
        # nhánh hỏi lại này trước nay thì chưa.
        quy_doi = {"turn_on": "open", "turn_off": "close"}
        seen = [a if a in allowed else quy_doi.get(a, a) for a in seen]
        action = next((a for a in seen if a in allowed and a != "set_level"), None) \
            or next((a for a in seen if a in allowed), None)
        verb = match.orphan_verb or (match.verb_words[0] if match.verb_words else "")
        label = (self.lexicon.aliases_of("device", self.last_device) or [self.last_device])[0]
        question = (f"Anh/chị muốn {verb} {label} phải không ạ?" if verb
                    else f"Anh/chị đang nói tới {label} phải không ạ?")

        if action:
            probe = decide(self.caps, RawCommand(device=self.last_device, action=action))
            if probe.command is not None:
                self.pending = Pending(commands=[probe.command], reason=question,
                                       created=self.clock(), ttl=self.confirm_ttl_s)
                trace.append(f"tham chiếu mơ hồ → hỏi xác nhận {self.last_device}.{action}")
                return self._stamp(self._voice(Turn(
                    text=text, verdict=Verdict.ASK, trace=trace, awaiting_confirm=True,
                    results=[Result(verdict=Verdict.ASK, code=Code.VAGUE_REFERENCE,
                                    device=self.last_device, reason=question)])),
                    "vague", 4)

        trace.append("tham chiếu mơ hồ → hỏi lại, chưa dựng được lệnh")
        return self._stamp(self._voice(Turn(
            text=text, verdict=Verdict.ASK, trace=trace,
            results=[Result(verdict=Verdict.ASK, code=Code.VAGUE_REFERENCE,
                            device=self.last_device, reason=question)])), "vague", 4)

    @staticmethod
    def _stamp(turn: Turn, label: str, checkpoint: int, cloud_ms=None, cloud_kind=None,
               cloud_error=None) -> Turn:
        turn.label, turn.checkpoint = label, checkpoint
        turn.cloud_ms, turn.cloud_kind, turn.cloud_error = cloud_ms, cloud_kind, cloud_error
        return turn

    def _cloud_reply(self, text: str, outcome, trace: list[str]) -> Optional[Turn]:
        """Cloud trả về lời nói hoặc chuyển tiếp thay vì lệnh."""
        if outcome.route:
            # Đích hợp lệ = thiết bị cloud_only trong caps, HOẶC trợ lý chung đã khai
            # trong reasoning.vi.yaml. Ngoài hai cái đó thì model tự đặt ra, bỏ.
            target = outcome.route.strip()
            dev = self.caps.devices.get(target)
            if (dev is not None and dev.cloud_only) or target == self.rules.route_to:
                handled = self._hand_off(text, target, trace)
                if handled is not None:
                    return handled
                trace.append(f"tầng [2] chuyển tiếp: {target}")
                return self._voice(Turn(
                    text=text, verdict=Verdict.ESCALATE_ROUTED, trace=trace,
                    results=[Result(verdict=Verdict.ESCALATE_ROUTED, code=Code.ESCALATE_ROUTED,
                                    target=target, device=target,
                                    reason=f"{target} do cloud xử lý")]))
            trace.append(f"tầng [2] đòi chuyển tới '{target}' — caps không công nhận, bỏ")

        if outcome.ask:
            return self._voice(Turn(
                text=text, verdict=Verdict.ASK, trace=trace, awaiting_confirm=False,
                results=[Result(verdict=Verdict.ASK, code=Code.ASK, reason=outcome.ask)]))
        # Có trợ lý chung thì câu trả lời bằng lời cũng chuyển sang đó, kể cả khi
        # model quên dùng route: nội dung để bên đã kiểm duyệt chịu trách nhiệm.
        if outcome.reply and self.rules.route_to:
            handled = self._hand_off(text, self.rules.route_to, trace)
            if handled is not None:
                return handled
            trace.append(f"tầng [2] định tự trả lời → chuyển {self.rules.route_to}")
            return self._voice(Turn(
                text=text, verdict=Verdict.ESCALATE_ROUTED, trace=trace,
                results=[Result(verdict=Verdict.ESCALATE_ROUTED, code=Code.ESCALATE_ROUTED,
                                target=self.rules.route_to, reason="câu ngoài miền xe")]))
        if outcome.reply:
            return self._voice(Turn(
                text=text, verdict=Verdict.REPLY, trace=trace,
                results=[Result(verdict=Verdict.REPLY, code=Code.REPLY, reason=outcome.reply)]))
        return None

    def _hand_off(self, text: str, target: str, trace: list[str]) -> Optional[Turn]:
        """Giao câu cho đích đã đăng ký. Không ai nhận thì trả None để giữ hành vi cũ."""
        handler = self.handlers.get(target)
        if handler is None:
            return None
        started = self.clock()
        reply = handler.answer(text)
        trace.append(f"{target}: {(self.clock() - started) * 1000:.0f}ms"
                     + ("" if reply else " — không trả lời được"))
        if not reply:
            # Đã giao cho người nhận mà họ không trả lời được thì PHẢI nói ra —
            # trả None ở đây là để rơi xuống ESCALATE_ROUTED và người dùng nghe im lặng.
            return self._voice(Turn(
                text=text, verdict=Verdict.REPLY, trace=trace,
                results=[Result(verdict=Verdict.REPLY, code=Code.NO_ANSWER, target=target,
                                reason="")]))
        return self._voice(Turn(
            text=text, verdict=Verdict.REPLY, trace=trace,
            results=[Result(verdict=Verdict.REPLY, code=Code.REPLY, target=target,
                            reason=reply)]))

    def _zone_from(self, text: str, device: str) -> Optional[str]:
        """Câu này có phải chỉ nêu một VÙNG của thiết bị đang treo không."""
        dev = self.caps.devices.get(device)
        if dev is None:
            return None
        hits = {e.target for e in self.lexicon.lookup(text, ZONE)
                if e.device in (None, device) and e.target in dev.zones}
        return next(iter(hits)) if len(hits) == 1 else None

    def _run_raws(self, text: str, raws: list[RawCommand], state: VehicleState,
                  trace: list[str]) -> Turn:
        """Chạy lệnh đã dựng sẵn — dùng cho lượt trả lời "vùng nào?"."""
        results = [decide(self.caps, raw, state) for raw in raws]
        self._commit(results)
        return self._stamp(self._voice(Turn(
            text=text, verdict=_worst(results), results=results, trace=trace)),
            "none", 4)

    def _hoi_vung_duoc(self, result: Result) -> bool:
        """BA sheet 3.2 #46: lệnh MỨC, không nêu vùng, và CHẮC CHẮN mọi vùng đang tắt.

        "Chắc chắn" là bắt buộc — vung_dang_bat() trả None khi chưa biết, và lúc đó
        phải cứ gửi lệnh: thà thừa còn hơn hỏi một câu vô duyên rồi nuốt mất lệnh.
        """
        cmd = result.command
        if cmd is None or cmd.action not in VALUE_ACTIONS or not result.zone_mac_dinh:
            return False
        if not hasattr(self.devices, "vung_dang_bat"):
            return False
        return self.devices.vung_dang_bat(cmd.device) is False

    def _commit(self, results: list[Result]) -> None:
        """Gửi lệnh xuống xe rồi ghi nhận hệ quả. Phải gọi từ CẢ hai đường — lệnh
        thường và lệnh chạy sau khi người dùng xác nhận."""
        for result in results:
            if result.command is not None:
                self.last_device = result.command.device
            # Vùng nhập nhằng: treo lệnh lại, lượt sau người ta nói vùng là chạy.
            if result.cho_vung is not None:
                self.pending_zone = PendingZone(raw=result.cho_vung, created=self.clock())
                self.last_device = result.cho_vung.device

        # Thiết bị đã ở đúng trạng thái xin thì NÓI CHO BIẾT, đừng gửi lại lệnh rồi
        # báo như mới. "bật điều hòa" khi nó đang bật không phải lỗi — chỉ là không
        # có gì để làm.
        for result in results:
            if not (result.ok and result.command is not None
                    and result.command.action != "query"):
                continue
            state = self.devices.get(result.command.device, result.command.zone)
            if da_dung_trang_thai(self.caps, result.command, state):
                result.da_dung = True
            elif self._hoi_vung_duoc(result):
                result.hoi_vung = True
                cmd = result.command
                self.pending_zone = PendingZone(
                    raw=RawCommand(device=cmd.device, action=cmd.action, zone=None,
                                   value=cmd.value if cmd.value is not None else cmd.step,
                                   unit=cmd.unit),
                    created=self.clock())
            else:
                result.cham_bien = cham_bien(self.caps, result.command, state)

        # Chỉ gửi lệnh đã qua tầng an toàn. Câu hỏi trạng thái không phải lệnh, và
        # lệnh trùng trạng thái cũng không cần gửi.
        runnable = [r for r in results
                    if r.ok and r.command is not None and r.command.action != "query"
                    and not r.da_dung and not r.cham_bien and not r.hoi_vung]
        if not runnable:
            return

        outcomes = self.runner.execute([r.command for r in runnable])
        for result, outcome in zip(runnable, outcomes):
            if not outcome.ok:
                # Xe từ chối: KHÔNG cập nhật trạng thái, và phải nói ra.
                result.verdict = Verdict.INVALID
                result.code = Code.EXEC_FAILED
                result.reason = outcome.detail or "xe không thực hiện được"
                result.device = result.command.device
                continue
            self._remember(result)
            if hasattr(self.devices, "apply"):
                self.devices.apply(result.command)

    def _remember(self, result: Result) -> None:
        """Chỉ nhớ mức khác 0 — nếu nhớ cả mức 0 thì 'bật tiếng lại' sẽ khôi phục
        đúng cái trạng thái tắt vừa rồi."""
        cmd = result.command
        if result.ok and cmd and cmd.action == "set_level" and cmd.value:
            self.last_level[cmd.device] = cmd.value

    def reset(self) -> None:
        self.last_device = None
        if hasattr(self.runner, "reset"):
            self.runner.reset()
        self.pending = None
        self.pending_slot = None
        self.last_level.clear()
        if hasattr(self.devices, "reset"):
            self.devices.reset()
