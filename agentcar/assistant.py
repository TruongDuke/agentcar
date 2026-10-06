"""Trợ lý chung — nhận câu ngoài miền xe mà tầng [2] chuyển sang.

Vì sao tách khỏi tầng [2]: prompt điều khiển xe đã 6000 ký tự và phải giữ kỷ luật
"chỉ dùng thiết bị trong caps". Nhồi thêm việc hỏi đáp chung vào đó vừa làm prompt
phình vừa dễ khiến model lẫn hai vai. Tách ra thì mỗi bên một prompt ngắn, và trợ
lý chung có chỗ riêng để cắm NGUỒN DỮ LIỆU — thứ model không tự biết.

Khi nền tảng đích có trợ lý chung thật, thay class này bằng adapter gọi sang đó;
giao diện `answer()` không đổi.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional, Protocol

from .config import LLMSettings
from .lexicon import normalize
from .llm import clean_speech

_JSON = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM = """Bạn là trợ lý chung trên xe. Người dùng nói tiếng Việt.

Câu này KHÔNG phải lệnh điều khiển xe — phần đó đã có agent khác lo. Việc của bạn
là trả lời như một trợ lý bình thường.

TRẢ VỀ JSON THUẦN, chọn một:
  {{"reply": "câu trả lời ngắn 1-2 câu"}}
  {{"tool": "weather"}}      CHỈ khi câu hỏi về THỜI TIẾT hiện tại

Quy tắc:
- Biết thì trả lời, ngắn gọn. Xưng "em", gọi "anh/chị", kết bằng "ạ".
- CHỈ dùng chữ tiếng Việt. Không lẫn chữ Hán, chữ Trung, tiếng Anh không cần thiết.
- KHÔNG bịa số liệu. Thứ cần cập nhật theo thời gian mà không có tool thì nói thẳng
  là chưa xem được. Ví dụ giá vàng, tỉ giá, tin tức, kết quả bóng đá: bạn không có
  tool nào cho mấy thứ đó, ĐỪNG dùng tool weather thay thế.
- Không nhận lệnh điều khiển xe. Nếu người ta nhờ làm gì trên xe, nói họ nói lại rõ hơn.

Thời điểm: {now}
Nơi đang ở (tạm khai trong cấu hình): {city}"""

# Vị trí: caps không có GPS nên phải khai tạm. Khi nền tảng đích cấp được toạ độ
# thì bỏ bảng này đi.
CITIES = {
    "Hà Nội": (21.028, 105.854), "Hải Phòng": (20.865, 106.684),
    "Đà Nẵng": (16.054, 108.202), "Huế": (16.463, 107.590),
    "Nha Trang": (12.239, 109.197), "Đà Lạt": (11.940, 108.458),
    "TP Hồ Chí Minh": (10.823, 106.630), "Cần Thơ": (10.045, 105.746),
}

# WMO weather code -> tiếng Việt (nhóm lại cho gọn, không cần đủ 100 mã)
WEATHER = {
    0: "trời quang", 1: "trời ít mây", 2: "trời nhiều mây", 3: "trời u",
    45: "có sương mù", 48: "sương mù đóng băng",
    51: "mưa phùn nhẹ", 53: "mưa phùn", 55: "mưa phùn dày",
    61: "mưa nhẹ", 63: "mưa", 65: "mưa to",
    71: "tuyết nhẹ", 73: "tuyết", 75: "tuyết dày",
    80: "mưa rào nhẹ", 81: "mưa rào", 82: "mưa rào rất to",
    95: "có dông", 96: "dông kèm mưa đá", 99: "dông mạnh kèm mưa đá",
}


def fetch_weather(lat: float, lon: float, timeout_s: float = 3.0) -> Optional[dict]:
    """Open-Meteo: không cần khoá, không cần đăng ký."""
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m,weather_code,relative_humidity_2m")
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as res:
            return json.loads(res.read().decode("utf-8")).get("current")
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None


class Handler(Protocol):
    def answer(self, text: str) -> Optional[str]:
        ...

    def co_nguon(self, text: str) -> bool:
        """Có nguồn dữ liệu thật cho câu này không.

        Để agent biết trước khi tốn một vòng gọi cloud: câu hỏi số liệu sống mà
        không ai có nguồn thì câu trả lời cuối cùng vẫn là "chưa xem được", nên
        trả lời thẳng trên xe.
        """
        ...


@dataclass
class CloudAssistant:
    """Trả lời bằng chính model của tầng [2], nhưng prompt riêng + có tool."""

    client: object                      # LLMClient
    settings: LLMSettings
    city: str = "Hà Nội"
    weather: Callable[[float, float], Optional[dict]] = fetch_weather
    # Câu hỏi thời tiết nhận ra được bằng từ khoá, khỏi gọi model để quyết định:
    # 3200ms xuống còn ~200ms (chỉ còn một lượt HTTP).
    # Dấu hiệu nhận ra câu hỏi thời tiết, khớp ngay trên xe nên KHÔNG tốn vòng gọi
    # model. Mỗi chuỗi kèm bản không dấu vì ASR trong xe hay trả về câu mất dấu.
    #
    # Chọn chuỗi phải THẬN TRỌNG: cụm quá rộng sẽ cướp mất câu lệnh xe. "lạnh không"
    # trống là hỏng — "trong xe lạnh không" là hỏi điều hoà chứ không phải thời tiết.
    # Nên mọi cụm mới đều neo vào chữ "trời" hoặc "ngoài".
    weather_cues: tuple[str, ...] = (
        "thời tiết", "thoi tiet", "dự báo", "du bao",
        "trời nắng", "troi nang", "trời mưa", "troi mua",
        "trời có mưa", "troi co mua", "trời có nắng", "troi co nang",
        "trời thế nào", "troi the nao", "trời hôm nay", "troi hom nay",
        "trời đẹp không", "troi dep khong", "trời lạnh không", "troi lanh khong",
        "nóng bao nhiêu độ", "nong bao nhieu do",
        "ngoài trời", "ngoai troi", "bên ngoài", "ben ngoai")
    # Thời tiết không đổi trong mươi phút, mà mỗi lượt gọi Open-Meteo mất ~1s.
    cache_ttl_s: float = 600.0
    clock: Callable[[], float] = time.monotonic
    _cache: dict = field(default_factory=dict)

    def prefetch(self) -> None:
        """Lấy sẵn thời tiết ở nền ngay khi khởi động.

        Gọi lúc người ta hỏi thì mất 1-3s và có lần timeout hẳn — thời tiết là dữ
        liệu nền, không có lý gì để người dùng phải chờ nó.
        """
        coords = CITIES.get(self.city)
        if coords is None:
            return

        def work():
            # Chạy ở nền: hỏng kiểu gì cũng phải im, không được ném lên thread chính.
            try:
                current = self.weather(*coords)
            except Exception:           # noqa: BLE001
                return
            if current:
                self._cache[self.city] = (self.clock(), current)

        threading.Thread(target=work, daemon=True).start()

    def _prompt(self) -> str:
        return SYSTEM.format(now=f"{datetime.now().astimezone():%Y-%m-%d %H:%M}", city=self.city)

    def _is_weather_question(self, text: str) -> bool:
        bare = normalize(text, keep_diacritics=True)
        stripped = normalize(text)
        return any(cue in bare or normalize(cue) in stripped for cue in self.weather_cues)

    def co_nguon(self, text: str) -> bool:
        """Chỉ thời tiết là có nguồn thật (Open-Meteo). Giá vàng, tỉ giá, tin tức,
        giao thông... thì không ai cấp số liệu, hỏi cloud cũng chỉ nghe 'chưa xem
        được'."""
        return self._is_weather_question(text)

    def answer(self, text: str) -> Optional[str]:
        if self._is_weather_question(text):
            return self._say_weather()

        try:
            raw = self.client.complete(self._prompt(), text, self.settings.timeout_ms / 1000)
        except Exception:               # noqa: BLE001 — trợ lý chung hỏng thì thôi
            return None

        match = _JSON.search(raw or "")
        if match is None:
            return self._salvage(raw)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return self._salvage(raw)

        if data.get("tool") == "weather":
            # Model chỉ có một tool nên hay dùng bừa: "giá vàng hôm nay" từng được
            # trả lời bằng thời tiết. Chỉ tin nếu câu thật sự hỏi thời tiết.
            if self._is_weather_question(text):
                return self._say_weather()
            return None
        return clean_speech(str(data["reply"])) if data.get("reply") else None

    @staticmethod
    def _salvage(raw: str) -> Optional[str]:
        """Model trả lời bằng văn xuôi thay vì JSON thì vẫn dùng được — thà nói câu
        nó viết còn hơn im lặng."""
        text = (raw or "").strip()
        if not text or text.startswith("{"):
            return None
        return clean_speech(text)

    def _say_weather(self) -> str:
        """Câu thời tiết ghép bằng template — số liệu thật, không qua model lần nữa."""
        coords = CITIES.get(self.city)
        if coords is None:
            return f"Em chưa biết toạ độ của {self.city} nên chưa xem được thời tiết ạ."
        cached = self._cache.get(self.city)
        if cached and self.clock() - cached[0] < self.cache_ttl_s:
            current = cached[1]
        else:
            current = self.weather(*coords)
            if current:
                self._cache[self.city] = (self.clock(), current)
            else:
                # Hết hạn mà lấy lại không được thì dùng số cũ, kèm lời rào.
                if cached:
                    self._cache[self.city] = (self.clock(), cached[1])
                    current = cached[1]
        if not current:
            return "Em chưa lấy được thông tin thời tiết lúc này ạ."

        temp = current.get("temperature_2m")
        sky = WEATHER.get(current.get("weather_code"), "")
        humidity = current.get("relative_humidity_2m")
        bits = [f"{self.city} đang {temp:.0f} độ" if temp is not None else self.city]
        if sky:
            bits.append(sky)
        if humidity is not None:
            bits.append(f"độ ẩm {humidity:.0f}%")
        return ", ".join(bits) + " ạ."
