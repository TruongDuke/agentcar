"""Tầng [2] — tầng cloud trên Alibaba Cloud DashScope (Qwen, endpoint OpenAI-compatible).

Nguyên tắc: LLM CHỈ được đề xuất slot thô. Mọi đề xuất đi qua đúng tầng [3][4] như
đường grammar, nên model không thể tạo ra lệnh mà caps không xác nhận. Đây là chỗ
thực thi "#2-defense" mà comment trong caps nói tới.

Dùng urllib của stdlib thay vì thêm SDK: chỉ là một POST JSON, và thứ này sẽ chạy
trên head unit nên càng ít phụ thuộc càng tốt.
"""
from __future__ import annotations

import http.client
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, Protocol

from .caps import Caps
from .config import LLMSettings
from .lexicon import DEVICE, MODE, ZONE, Lexicon
from .reasoning import RuleSet, load_rules, render as render_rules
from .plan import RawCommand

MAX_COMMANDS = 4

# Qwen là model Trung Quốc và thỉnh thoảng lẫn chữ Hán vào câu tiếng Việt — đã gặp
# thật: "cập nhật giá vàng 实时". Câu này sẽ được ĐỌC TO cho người dùng nghe nên
# phải lọc. Mất quá nhiều chữ thì bỏ hẳn câu, thà nói "chưa trả lời được".
_FOREIGN = re.compile(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
                      r"\uf900-\ufaff\uff00-\uffef\u0400-\u04ff\u0600-\u06ff]+")
MAX_FOREIGN_RATIO = 0.15


def clean_speech(text: Optional[str], limit: int = 300) -> Optional[str]:
    """Lọc chữ nước ngoài khỏi câu sắp đọc cho người dùng."""
    if not text:
        return None
    original = text.strip()
    cleaned = _FOREIGN.sub(" ", original)
    if len(original) and (len(original) - len(cleaned.replace("  ", " "))) / len(original) > MAX_FOREIGN_RATIO:
        return None
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", re.sub(r"\s+", " ", cleaned)).strip()
    return cleaned[:limit] or None          # câu dài hơn thế gần như chắc chắn là model đi lạc
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class CloudError(RuntimeError):
    """Máy chủ trả về mã khác 200. Mang theo mã và lời nhắn của nó."""

    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status, self.message = status, message


class RateLimited(CloudError):
    """429 - gọi quá dày. Khác hẳn đứt mạng: chờ một nhịp là gọi lại được."""

SYSTEM = """Bạn là tầng suy luận của trợ lý trên xe {model}. Người dùng nói tiếng Việt.

Tầng nhận dạng mẫu câu ở trước đã BÓ TAY với câu này, nên nó là câu khó: nói vòng,
nói cảm giác, nói tắt theo ngữ cảnh, nhiều ý trong một câu, hoặc không thuộc phạm vi.

TRẢ VỀ JSON THUẦN, không giải thích, theo đúng khung sau (bỏ hẳn khoá không dùng):

{{"commands": [{{"device","action","zone","value","unit","mode","item"}}],
  "ask": "câu hỏi lại nếu THIẾU thông tin",
  "reply": "câu trả lời nếu không có lệnh nào để chạy",
  "route": "nav"}}

XÉT TRƯỚC TIÊN — điều kiện và hẹn giờ:
Nếu câu có "khi nào", "lúc", "sau khi", "nếu", "lát nữa", "phút nữa"... thì việc đó
KHÔNG được làm bây giờ. Dùng reply nói rõ xe chưa hẹn giờ được. Quy tắc này thắng
mọi quy tắc khác, kể cả khi câu có nhắc tới địa điểm:
  "mở cửa sổ trời khi nào tới nhà" -> reply (KHÔNG phải route nav, KHÔNG mở ngay)

CHỌN MỘT trong bốn — nhưng KHÔNG ngang hàng: `commands` là mặc định.
Việc nào làm được bằng một lệnh trong danh sách dưới thì PHẢI ra `commands`.
`reply` chỉ dùng khi KHÔNG thiết bị nào trong danh sách làm nổi việc đó.
1. commands — hiểu rõ muốn làm gì. Chỉ dùng device/action/zone/mode/item có trong
   danh sách dưới, TUYỆT ĐỐI không bịa. Tối đa {max_commands} lệnh, xếp đúng thứ tự.
2. ask — hiểu ý nhưng thiếu thông tin và ĐOÁN BỪA THÌ NGUY HIỂM (xem mục Quy tắc
   bên dưới để biết chữ nào là mơ hồ). Khi liệt kê lựa chọn, CHỈ nhắc thiết bị có
   trong danh sách dưới — nhắc thứ xe không có là làm người dùng tưởng có.
3. reply — không có lệnh nào để chạy: hỏi kiến thức, tán gẫu, hoặc yêu cầu xe chưa
   làm được. TRẢ LỜI nếu biết (xem Quy tắc bên dưới), nói rõ là chưa biết nếu không.
   Ngắn gọn 1-2 câu, xưng "em", gọi "anh/chị", kết bằng "ạ".
   TUYỆT ĐỐI KHÔNG dùng reply để nói rằng đã LÀM XONG một việc. Viết "em đã mở
   phần thiết lập gương ạ" mà không kèm commands là nói dối người lái — xe
   không hề làm gì. Làm được thì ra commands; không làm được thì nói là không.
   Cũng KHÔNG dùng reply để nói trạng thái thiết bị: bạn không đọc được trạng
   thái, chỉ xe mới đọc được. "Đang ở phần hành trình à" -> commands query,
   KHÔNG phải reply "dạ đang ở phần hành trình ạ".
4. route: "nav" — dẫn đường, tìm địa điểm, hỏi đường đi. KHÔNG tự sinh lệnh.

Quy tắc:
{rules}
- Dùng NGỮ CẢNH bên dưới để hiểu câu nói tắt: "tăng thêm nữa", "cái đó tắt đi",
  "ghế bên kia cũng vậy", "để lại như lúc nãy".
- Hỏi trạng thái thiết bị CÓ trong danh sách thì LUÔN là commands với action
  "query", không bao giờ là reply. Kể cả khi câu hỏi nghe như tán gẫu:
  "bluetooth không thấy phản hồi vậy" -> commands query bluetooth.
- PHỦ ĐỊNH. "đừng bật X", "không cần X", "khỏi bật X" nghĩa là TẮT X, không
  phải không làm gì. Và phủ định CHỈ huỷ vế của nó:
  "đừng bật đèn trước, bật đèn sau" -> một lệnh BẬT đèn SAU. Không phải tắt
  đèn trước, cũng không phải bỏ cả câu.
  Phủ định một CHẾ ĐỘ thì dùng clear_mode, không phải set_mode:
  "đừng bật đồng bộ nhiệt độ" -> hvac clear_mode.
- BƯỚC hay MỨC ĐÍCH. Có chữ chỉ lượng thêm bớt — "thêm", "bớt", "cộng", "nữa",
  "hơn", "nhích", "đi N" — thì đó là BƯỚC: dùng increase/decrease, con số vào
  ô "value" như bình thường. Không có chữ đó mà nêu con số thì là mức đích:
  dùng set_level.
  "cộng thêm 2 mức sưởi" -> increase. "nhẹ hơn" -> decrease. "để 22 độ" -> set_level.
- SỐ ÂM giữ nguyên dấu, KHÔNG đổi thành số dương và KHÔNG đổi chiều lệnh.
  "nhích âm lượng -3 mức" -> increase với value -3, KHÔNG phải decrease 3.
  "đặt mức -15" -> set_level value -15. Người ta nói sao thì ghi vậy; xe tự lo
  phần hợp lệ.
- BA KÊNH ÂM THANH dễ lẫn vì tiếng Việt đều có chữ "chuông" hoặc "gọi":
    ring   chuông REO KHI CÓ NGƯỜI GỌI TỚI — "chuông cuộc gọi", "chuông gọi
           tới", "chuông điện thoại", "nhạc chuông". Có chữ "chuông" + "gọi"
           thì là ring, KHÔNG phải call.
    call   âm thanh TRONG LÚC ĐANG NÓI CHUYỆN — "âm thanh thoại", "loa đàm
           thoại", "tiếng cuộc gọi". Không có chữ "chuông".
    chime  tiếng bíp CẢNH BÁO CỦA XE — "âm báo", "chuông cảnh báo". Không
           liên quan điện thoại.
- Câu nêu RÕ một kênh âm thanh thì PHẢI điền zone, đừng để trống thành "all".
  "tiếng nhạc" -> media. "tiếng trợ lý", "tiếng Vivi" -> va.
- "MÀN HÌNH X" thì PHẢI điền item là X, đừng để trống. Không tìm thấy X trong
  danh sách items thì chọn mục gần nhất, vẫn hơn bỏ trống.
- "TỐI THIỂU", "NHỎ NHẤT", "BÉ NHẤT" là số ĐẦU của dải ghi trong danh sách,
  KHÔNG phải 0. Cửa sổ trời ghi "percent 1-100" thì tối thiểu là 1.
  "TỐI ĐA", "KỊCH TRẦN", "FULL", "HẾT GA", "HẾT CỠ" là số CUỐI của dải.
- MÀU và KIỂU là CHẾ ĐỘ, không phải bật/tắt: "đèn viền màu xanh" -> set_mode
  với mode màu đó, không phải turn_on.
- "MÀN HÌNH X" / "GIAO DIỆN X" / "ĐANG HIỆN X" nói về MÀN HÌNH đang mở, không
  nói về thiết bị X. Dùng screen_control với item là X, đừng dùng chính X:
  "màn hình bluetooth đang hiện hả"  -> screen_control query item bluetooth
  "âm lượng hiện trên màn hình hả"   -> screen_control query item volume_settings
  "hiện là trang thông tin xe à"     -> screen_control query item about_settings
  Chỉ khi câu KHÔNG nhắc màn hình/giao diện/trang thì mới là thiết bị X:
  "bluetooth đang bật không" -> bluetooth query.
- "SƯỞI" nói trống, không kèm "điều hòa" hay "vô lăng", là SƯỞI GHẾ
  (seat_heating): "dừng sưởi", "boost heating thêm 2 nấc".
- GHẾ có BA thứ chỉnh riêng, đừng lẫn:
    ghế NÓNG  -> seat_cooling (làm mát ghế).  ghế LẠNH -> seat_heating (sưởi ghế).
    Người ta nói CẢM GIÁC HIỆN TẠI, mình làm điều NGƯỢC LẠI để chữa nó.
    "ghế lạnh ngang, tăng thêm 1 mức" -> TĂNG SƯỞI, không phải tăng làm mát.
    ghế YẾU / MẠNH / "cấp độ" / "cường độ" -> seat_massage, không phải nhiệt.
- Câu "ĐỪNG <làm A>, <làm B>" chỉ sinh MỘT lệnh, và mọi tham số (vùng, item,
  mức) phải lấy từ vế B - vế SAU dấu phẩy. Vế A bị bỏ đi hoàn toàn.
    "Đừng bật đèn sương SAU, bật phía TRƯỚC" -> fog_light zone=front.
    "Không cần đèn vàng TRƯỚC, chỉ bật đèn SAU" -> fog_light zone=rear.
  Lỗi hay gặp: lấy nhầm vùng của vế bị phủ định.
- "ĐỪNG ĐỂ <chỗ nào> <cảm giác> NỮA" là BẬT thiết bị CHỮA cảm giác đó, không
  phải tắt thiết bị cùng tên:
    "Đừng để ghế phụ NÓNG nữa"  -> turn_on seat_cooling zone=passenger
    "Đừng để ghế lái LẠNH nữa"  -> turn_on seat_heating zone=driver
- Mấy cách nói VÀO / RA một màn hình hay ứng dụng, đều là lệnh open/close:
    vào, vô, kéo qua, đưa tôi tới, cho X lên màn hình, mở X ra   -> open
    exit khỏi, thoát khỏi, chuyển khỏi, cất X đi, đóng X lại     -> close
  Câu dùng từ lóng hay trộn tiếng Anh vẫn là lệnh: "Vô phần trợ lý giọng nói
  với nờ", "Exit khỏi contact list", "Cho tui vô media".

Danh sách thiết bị:
{digest}"""


@dataclass
class LLMOutcome:
    commands: list[RawCommand] = field(default_factory=list)
    ask: Optional[str] = None       # cloud hỏi lại
    reply: Optional[str] = None     # cloud trả lời bằng lời
    route: Optional[str] = None     # chuyển cho agent khác (nav)
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    raw: str = ""
    unreachable: bool = False    # lỗi mạng, khác hẳn "model trả rác"
    timed_out: bool = False      # model chậm — mạng vẫn tốt, đừng nói "mất kết nối"

    @property
    def ok(self) -> bool:
        return self.error is None


class LLMClient(Protocol):
    def complete(self, system: str, user: str, timeout_s: float) -> str:
        ...


class DashScopeClient:
    """OpenAI-compatible chat completions, GIỮ KẾT NỐI giữa các lượt.

    Mỗi lần mở kết nối mới phải bắt tay TLS lại, tốn vài trăm ms — đủ để đẩy một
    câu vốn kịp hạn thành quá hạn. Giữ một kết nối sống và mở lại khi nó đứt.
    """

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        parts = urllib.parse.urlsplit(settings.base_url)
        self._host = parts.netloc
        self._path = parts.path.rstrip("/") + "/chat/completions"
        self._conn: Optional[http.client.HTTPSConnection] = None

    def _connection(self, timeout_s: float) -> tuple[http.client.HTTPSConnection, bool]:
        """Trả kèm cờ 'vừa mở' — kết nối mới mà hỏng thì thử lại vô ích."""
        fresh = self._conn is None
        if fresh:
            self._conn = http.client.HTTPSConnection(self._host, timeout=timeout_s)
        self._conn.timeout = timeout_s
        return self._conn, fresh

    def warmup(self) -> bool:
        """Mở sẵn kết nối lúc khởi động. Câu ĐẦU TIÊN vốn phải trả tiền bắt tay
        TLS (~400ms) — đủ để nó vượt hạn trong khi mọi câu sau đều kịp."""
        try:
            self._connection(self.settings.timeout_ms / 1000)[0].connect()
            return True
        except OSError:
            self.close()
            return False

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def complete(self, system: str, user: str, timeout_s: float) -> str:
        body = json.dumps({
            "model": self.settings.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.api_key}",
            "Connection": "keep-alive",
        }

        for attempt in (1, 2):
            conn, fresh = self._connection(timeout_s)
            try:
                conn.request("POST", self._path, body=body, headers=headers)
                resp = conn.getresponse()
                raw, status = resp.read().decode("utf-8"), resp.status
                break
            except (http.client.HTTPException, socket.timeout, OSError):
                self.close()
                # Chỉ thử lại khi dùng lại kết nối CŨ (phía kia có thể đã đóng).
                # Kết nối vừa mở mà hỏng thì mạng đang hỏng — thử lại chỉ làm
                # người dùng chờ gấp đôi deadline rồi vẫn thất bại.
                if fresh or attempt == 2:
                    raise
        if status != 200:
            try:
                loi = json.loads(raw)["error"]["message"]
            except Exception:                         # noqa: BLE001 - body lỗi không theo khuôn
                loi = raw[:200]
            raise (RateLimited if status == 429 else CloudError)(status, loi)
        return json.loads(raw)["choices"][0]["message"]["content"]


# Vùng theo VỊ TRÍ thì mã đã tự nói ra nghĩa — gắn thêm "driver(ghế lái)" chỉ
# tốn chữ. Vùng của âm lượng thì không: ring, chime, call đều là "chuông" hoặc
# "gọi" trong tiếng Việt, model đoán sai thật.
VUNG_TU_HIEU = frozenset({"all", "driver", "passenger", "rear", "front",
                          "rear_left", "rear_right", "left", "right"})


def render_digest(caps: Caps, lex: Lexicon) -> str:
    """Bản tóm tắt caps đưa vào prompt. Chỉ liệt kê thứ thực sự dùng được."""
    lines = []
    for name, dev in caps.devices.items():
        actions = caps.effective_actions(dev)
        if not actions:
            continue
        # ĐÃ THỬ, KHÔNG ĐO THẤY: cho digest mang 4 tên gọi thay vì 1, để model
        # biết "đèn sương mù" còn gọi là "đèn gầm", "đèn mù". Lý do nghe hợp lý
        # — 11 câu cloud chịu thua phần lớn vì không nhận ra tên dân dã.
        # Đo ra +1,5 điểm, mà nhiễu giữa hai lượt CÙNG cấu hình là ±3 điểm
        # (64,2 / 66,4 / 65,7). Không kết luận được, trong khi tốn thật 800 ký
        # tự mỗi lượt gọi. Muốn thử lại thì phải chạy --lan 3 cả hai phía.
        vi = (lex.aliases_of(DEVICE, name) or [name])[0]
        bits = [f"{name} ({vi}): {' '.join(actions)}"]
        # Mã vùng và mã chế độ phải KÈM NGHĨA. Trước đây in trần:
        #   zones=all,va,call,ring,media,navigation,chime
        # Model phải tự đoán ring khác chime khác call ở chỗ nào — và nó đoán
        # sai thật: "chuông cuộc gọi điện thoại" ra call, "tiếng nhạc" ra all.
        # Chỉ gắn nghĩa khi mã KHÁC tên tiếng Việt (driver/passenger thì ai
        # cũng hiểu, gắn thêm chỉ tốn chữ).
        def _glo(kind, ids, bo_qua=(), so_ten=1):
            ra = []
            for i in ids:
                if i in bo_qua:
                    ra.append(i)
                    continue
                ten = lex.aliases_of(kind, i, device=name) or lex.aliases_of(kind, i)
                ten = [t for t in ten[:so_ten] if t != i]
                ra.append(f"{i}({'/'.join(ten)})" if ten else i)
            return ra

        if dev.zones:
            bits.append("zones=" + ",".join(_glo(ZONE, dev.zones, VUNG_TU_HIEU)))
        if dev.value is not None and dev.value.is_number:
            unit = dev.value.unit()
            if unit is not None:
                bits.append(f"{unit.name} {_num(unit.lo)}-{_num(unit.hi)}")
        modes = [m for m in dev.modes if m not in dev.exclude]
        if modes:
            bits.append("modes=" + ",".join(_glo(MODE, modes, so_ten=3)))
        if dev.items:
            bits.append(f"items={','.join(dev.items)}")
        lines.append(" | ".join(bits))
    return "\n".join(lines)


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


class CloudPath:
    def __init__(self, caps: Caps, lex: Lexicon, client: LLMClient, settings: LLMSettings,
                 clock=time.monotonic, breaker_after: int = 2, breaker_cooldown_s: float = 30.0,
                 rules: Optional[RuleSet] = None):
        self.caps = caps
        self.client = client
        self.settings = settings
        self.clock = clock
        # Cầu dao: mất mạng thì mỗi câu phải chờ hết deadline rồi mới thất bại.
        # Hỏng liên tiếp mấy lần thì ngưng gọi một lúc, thất bại ngay lập tức.
        self.breaker_after = breaker_after
        self.breaker_cooldown_s = breaker_cooldown_s
        self.failures = 0
        self.open_until = 0.0
        # Luật suy luận SINH từ caps/reasoning.vi.yaml, đã lọc theo dòng xe này.
        self.rules = rules if rules is not None else load_rules()
        self.system = SYSTEM.format(model=caps.model, digest=render_digest(caps, lex),
                                    max_commands=MAX_COMMANDS,
                                    rules=render_rules(caps, self.rules))

    @property
    def breaker_open(self) -> bool:
        return self.clock() < self.open_until

    def _failed(self) -> None:
        self.failures += 1
        if self.failures >= self.breaker_after:
            self.open_until = self.clock() + self.breaker_cooldown_s

    def interpret(self, text: str, context: str = "") -> LLMOutcome:
        if self.breaker_open:
            left = self.open_until - self.clock()
            return LLMOutcome(error=f"tạm ngưng gọi cloud thêm {left:.0f}s (mạng đang lỗi)",
                              unreachable=True)

        started = self.clock()
        try:
            prompt = f"{context}\n\nCâu vừa nói: {text}" if context else text
            raw = self.client.complete(self.system, prompt, self.settings.timeout_ms / 1000)
        except RateLimited as exc:
            # Vẫn mở cầu dao — đang bị chặn thì gọi tiếp chỉ tốn thêm. Nhưng nói
            # đúng lý do, để người đọc log không đi sửa nhầm chỗ.
            self._failed()
            return LLMOutcome(elapsed_ms=self._since(started), unreachable=True,
                              error=f"quá hạn mức gọi: {exc.message}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self._failed()
            return LLMOutcome(elapsed_ms=self._since(started), unreachable=True,
                              error=f"không gọi được: {exc}")
        except Exception as exc:                      # noqa: BLE001 - model lỗi thì thôi, không sập agent
            self._failed()
            return LLMOutcome(elapsed_ms=self._since(started), error=str(exc))

        elapsed = self._since(started)
        if elapsed > self.settings.timeout_ms:
            # KHÔNG mở cầu dao: model chậm một lượt khác hẳn mất mạng. Mở cầu dao
            # vì một câu chậm sẽ giết luôn mấy câu sau dù mạng vẫn tốt.
            return LLMOutcome(elapsed_ms=elapsed, raw=raw, timed_out=True,
                              error=f"quá hạn {self.settings.timeout_ms}ms")

        self.failures = 0                             # gọi được thì đóng cầu dao lại
        self.open_until = 0.0
        commands, error, ask, replytext, route = self.parse(raw)
        return LLMOutcome(commands=commands, ask=ask, reply=replytext, route=route,
                          elapsed_ms=elapsed, raw=raw, error=error)

    def parse(self, raw: str):
        """Chỉ lấy đúng các trường mình biết. Thứ khác model nói thì bỏ."""
        match = _JSON_RE.search(raw or "")
        if match is None:
            return [], "không tìm thấy JSON trong câu trả lời", None, None, None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            return [], f"JSON hỏng: {exc}", None, None, None

        text_of = lambda key: clean_speech(str(data[key])) if data.get(key) else None
        ask, replytext = text_of("ask"), text_of("reply")
        route = str(data["route"]).strip() if data.get("route") else None

        out: list[RawCommand] = []
        for item in self._commands_in(data)[:MAX_COMMANDS]:
            value = item.get("value")
            out.append(RawCommand(
                device=str(item["device"]),
                action=str(item["action"]) if item.get("action") else None,
                zone=str(item["zone"]) if item.get("zone") else None,
                value=float(value) if isinstance(value, (int, float)) else None,
                unit=str(item["unit"]) if item.get("unit") else None,
                mode=str(item["mode"]) if item.get("mode") else None,
                item=str(item["item"]) if item.get("item") else None,
            ))
        return out, None, ask, replytext, route

    def _commands_in(self, data: dict) -> list[dict]:
        """Gom lệnh ra khỏi mọi hình dạng model hay trả về.

        Hợp đồng là {"commands": [...]}, nhưng model trả sai khung khá thường:
        đáp án đúng mà parser cũ vứt sạch rồi báo "không hiểu". Đo trên 500 câu
        thì mất 23 câu chỉ vì chuyện này. Nhận thêm ba dạng hay gặp:
            {"screen_control": {...}}          lấy tên thiết bị làm khoá
            {"device": ..., "action": ...}     một lệnh trần, quên bọc
            {"commands": {...}}                quên bọc thành list
        Không đoán xa hơn thế: lấy bừa thì lại thành bịa lệnh.
        """
        got = data.get("commands")
        if isinstance(got, list):
            picked = [c for c in got if isinstance(c, dict) and c.get("device")]
            if picked:
                return picked
        if isinstance(got, dict) and got.get("device"):
            return [got]
        picked = []
        for key, val in data.items():
            if key not in self.caps.devices:
                continue
            if isinstance(val, dict):
                picked.append({**val, "device": key})
            elif isinstance(val, list):
                picked += [{**v, "device": key} for v in val if isinstance(v, dict)]
        if picked:
            return picked
        if data.get("device"):
            return [data]
        return []

    def _since(self, started: float) -> float:
        return (self.clock() - started) * 1000


def build_cloud_path(caps: Caps, lex: Lexicon, settings: LLMSettings) -> Optional[CloudPath]:
    """Chỉ dựng khi vừa bật vừa có key — thiếu một trong hai thì không gọi ra ngoài."""
    if not settings.usable:
        return None
    client = DashScopeClient(settings)
    client.warmup()      # hỏng thì thôi, lần gọi thật sẽ tự mở lại
    return CloudPath(caps, lex, client, settings)
