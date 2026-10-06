"""Cấu hình tầng [2] — đọc từ .env, biến môi trường thật được ưu tiên.

Tự parse thay vì thêm python-dotenv: file .env chỉ có dạng KEY=VALUE, không đáng
để thêm một phụ thuộc vào thứ sẽ chạy trên head unit.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .caps import Caps

DEFAULT_ENV = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
DEFAULT_TIMEOUT_MS = 1200


def load_env(path: Path | str = DEFAULT_ENV) -> dict[str, str]:
    """Đọc .env. KHÔNG ghi đè biến môi trường đã có — môi trường thật thắng."""
    values: dict[str, str] = {}
    path = Path(path)
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            values[key.strip()] = value
    return values


@dataclass(frozen=True)
class LLMSettings:
    timeout_source: str = "mặc định"
    api_key: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    enabled: bool = False

    @property
    def usable(self) -> bool:
        """Bật mà thiếu key thì coi như chưa dùng được — không gọi ra ngoài."""
        return self.enabled and bool(self.api_key)

    @property
    def masked_key(self) -> str:
        if not self.api_key:
            return "(chưa có)"
        return f"{self.api_key[:6]}…{self.api_key[-4:]} ({len(self.api_key)} ký tự)"


# Cùng một thứ nhưng người ta quen gọi nhiều tên: DashScope là tên dịch vụ,
# Alibaba là tên nhà cung cấp. Nhận hết để khỏi phải sửa lại file đã dán.
ALIASES = {
    "api_key":  ("DASHSCOPE_API_KEY", "ALIBABA_API_KEY", "ALIBABA_CLOUD_API_KEY", "QWEN_API_KEY"),
    "base_url": ("AGENTCAR_LLM_BASE_URL", "ALIBABA_BASE_URL", "DASHSCOPE_BASE_URL"),
    "model":    ("AGENTCAR_LLM_MODEL", "ALIBABA_MODEL", "DASHSCOPE_MODEL", "QWEN_MODEL"),
    "timeout":  ("AGENTCAR_LLM_TIMEOUT_MS",),
    "enabled":  ("AGENTCAR_LLM_ENABLED",),
}


def _get(env: dict[str, str], field: str) -> Optional[str]:
    """Biến môi trường thật thắng .env; trong cùng một nguồn thì tên nào có trước thắng."""
    for key in ALIASES[field]:
        value = os.environ.get(key)
        if value:
            return value
    for key in ALIASES[field]:
        value = env.get(key)
        if value:
            return value
    return None


def settings(caps: Optional[Caps] = None, path: Path | str = DEFAULT_ENV) -> LLMSettings:
    env = load_env(path)
    timeout, source = _get(env, "timeout"), "cấu hình"
    if timeout is None and caps is not None and caps.gate.get("deadline_ms"):
        timeout, source = str(caps.gate["deadline_ms"]), "gate.deadline_ms trong caps"
    elif timeout is None:
        source = "mặc định"

    enabled = (_get(env, "enabled") or "false").lower() in ("1", "true", "yes", "on")
    return LLMSettings(
        api_key=_get(env, "api_key"),
        base_url=_get(env, "base_url") or DEFAULT_BASE_URL,
        model=_get(env, "model") or DEFAULT_MODEL,
        timeout_ms=int(timeout or DEFAULT_TIMEOUT_MS),
        timeout_source=source,
        enabled=enabled,
    )
