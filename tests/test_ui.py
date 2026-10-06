"""Tầng hiển thị: trang web và các header server gửi kèm.

441 dòng index.html trước nay không có test nào, và trong một buổi đã lòi ra
bốn lỗi ở đây — cốp trước viết cứng "không hỗ trợ", thẻ nhiều vùng chỉ đọc
vùng mặc định, thiếu Cache-Control nên sửa xong tải lại vẫn thấy bản cũ, và
Enter hai lần gửi hai lượt. Bộ đo 24.851 câu không bắt được cái nào: nó chấm
JSON của lệnh, không mở trình duyệt.

Phần dựng giao diện kiểm bằng Node (tests/ui/), vì nó là JavaScript. Ở đây chỉ
gọi sang và kiểm nốt phần Python lo.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TRANG = ROOT / "agentcar" / "web" / "index.html"


@pytest.mark.skipif(shutil.which("node") is None, reason="không có node")
def test_render_js():
    """Chạy bộ kiểm JavaScript, in nguyên đầu ra khi hỏng."""
    r = subprocess.run(["node", str(ROOT / "tests" / "ui" / "render.test.mjs")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, "\n" + r.stdout + r.stderr


def test_page_sends_no_store():
    """Trang để SỬA RỒI XEM NGAY. Thiếu header này thì trình duyệt giữ bản cũ và
    người sửa đi tìm lỗi ở chỗ không có lỗi — đúng chuyện đã xảy ra."""
    from agentcar.server import Simulator  # noqa: F401  (chỉ để chắc import được)

    src = (ROOT / "agentcar" / "server.py").read_text(encoding="utf-8")
    assert "Cache-Control" in src and "no-store" in src


def test_mic_reports_its_errors():
    """Không có onerror thì mọi thất bại của micro bị nuốt im lặng: nút hết đỏ
    rồi thôi, người dùng tưởng hệ thống điếc."""
    src = TRANG.read_text(encoding="utf-8")
    assert "rec.onerror" in src
    for ma in ("not-allowed", "no-speech", "audio-capture", "network"):
        assert ma in src, f"thiếu lời giải thích cho lỗi micro {ma!r}"


def test_enter_twice_sends_once():
    """say() từng đặt BUSY = true mà không ai kiểm, nên Enter lần hai gửi thêm
    một lượt nữa."""
    src = TRANG.read_text(encoding="utf-8")
    assert "if (BUSY) return;" in src, "thiếu chốt chặn gửi trùng trong say()"
