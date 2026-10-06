"""Cấu hình tầng [2]."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentcar.caps import load_caps
from agentcar.config import DEFAULT_BASE_URL, load_env, settings

ROOT = Path(__file__).resolve().parent.parent
CAPS = load_caps(ROOT / "caps" / "vf9.yaml")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """conftest tắt tầng [2] bằng biến môi trường thật; ở đây phải bỏ nó đi thì
    mới kiểm được chính cơ chế đọc .env."""
    for key in ("AGENTCAR_LLM_ENABLED", "DASHSCOPE_API_KEY", "ALIBABA_API_KEY",
                "AGENTCAR_LLM_MODEL", "AGENTCAR_LLM_BASE_URL", "ALIBABA_BASE_URL"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env_file(tmp_path):
    def write(text: str) -> Path:
        path = tmp_path / ".env"
        path.write_text(text, encoding="utf-8")
        return path
    return write


def test_parses_comments_quotes_and_export(env_file):
    path = env_file('# ghi chú\nexport DASHSCOPE_API_KEY="sk-abc"\nAGENTCAR_LLM_MODEL=\'qwen-max\'\n\n')
    assert load_env(path) == {"DASHSCOPE_API_KEY": "sk-abc", "AGENTCAR_LLM_MODEL": "qwen-max"}


def test_empty_value_is_not_a_setting(env_file):
    """Dòng để trống trong .env.example không được coi là đã cấu hình."""
    assert load_env(env_file("AGENTCAR_LLM_TIMEOUT_MS=\n")) == {}


def test_real_environment_wins(env_file, monkeypatch):
    path = env_file("AGENTCAR_LLM_MODEL=qwen-turbo\n")
    monkeypatch.setenv("AGENTCAR_LLM_MODEL", "qwen-max")
    assert settings(CAPS, path).model == "qwen-max"


def test_timeout_falls_back_to_caps_gate(env_file):
    cfg = settings(CAPS, env_file(""))
    assert cfg.timeout_ms == CAPS.gate["deadline_ms"] == 1200
    assert "caps" in cfg.timeout_source


def test_timeout_from_config_wins_over_caps(env_file):
    cfg = settings(CAPS, env_file("AGENTCAR_LLM_TIMEOUT_MS=2000\n"))
    assert cfg.timeout_ms == 2000 and cfg.timeout_source == "cấu hình"


def test_defaults_without_env_file(tmp_path):
    cfg = settings(CAPS, tmp_path / "khong-co.env")
    assert cfg.base_url == DEFAULT_BASE_URL and cfg.api_key is None and not cfg.enabled


def test_enabled_without_key_is_not_usable(env_file):
    """Bật mà thiếu key thì không được gọi ra ngoài."""
    cfg = settings(CAPS, env_file("AGENTCAR_LLM_ENABLED=true\n"))
    assert cfg.enabled and not cfg.usable


def test_usable_needs_both(env_file):
    cfg = settings(CAPS, env_file("AGENTCAR_LLM_ENABLED=true\nDASHSCOPE_API_KEY=sk-1234567890abcd\n"))
    assert cfg.usable


@pytest.mark.parametrize("name", ["DASHSCOPE_API_KEY", "ALIBABA_API_KEY",
                                  "ALIBABA_CLOUD_API_KEY", "QWEN_API_KEY"])
def test_api_key_aliases(env_file, name):
    """Cùng một thứ nhiều tên gọi — nhận hết, khỏi bắt người dùng sửa lại file."""
    assert settings(CAPS, env_file(f"{name}=sk-xyz\n")).api_key == "sk-xyz"


@pytest.mark.parametrize("name", ["AGENTCAR_LLM_BASE_URL", "ALIBABA_BASE_URL", "DASHSCOPE_BASE_URL"])
def test_base_url_aliases(env_file, name):
    assert settings(CAPS, env_file(f"{name}=https://x/v1\n")).base_url == "https://x/v1"


def test_masked_key_hides_the_middle(env_file):
    cfg = settings(CAPS, env_file("DASHSCOPE_API_KEY=sk-1234567890abcdef\n"))
    assert "1234567890" not in cfg.masked_key and cfg.masked_key.startswith("sk-123")
