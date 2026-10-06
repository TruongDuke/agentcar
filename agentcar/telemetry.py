"""Ghi số liệu mỗi lượt để ĐẾM, không phải để soi từng câu.

Mọi con số trong README tới giờ đều lấy từ ngữ liệu tự soạn. Cái này để thay bằng
số đo trên câu thật.

Riêng tư: MẶC ĐỊNH KHÔNG ghi câu nói của người dùng — trong xe người ta nói cả tên
người, địa chỉ, chuyện nhà. Muốn ghi thì phải bật AGENTCAR_LOG_TEXT=1 một cách có
chủ ý.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "logs" / "turns.jsonl"


@dataclass
class Recorder:
    path: Optional[Path] = DEFAULT_PATH
    keep_text: bool = False
    enabled: bool = True
    # Nguồn của lượt này. Rỗng = người dùng thật. Script đo phải tự khai
    # AGENTCAR_LOG_TAG, nếu không số liệu thật sẽ lẫn hàng trăm lượt giả.
    tag: str = ""

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "Recorder":
        env = env if env is not None else os.environ
        raw = env.get("AGENTCAR_LOG", "")
        if raw.lower() in ("0", "off", "false"):
            return cls(path=None, enabled=False)
        return cls(
            path=Path(raw) if raw else DEFAULT_PATH,
            keep_text=env.get("AGENTCAR_LOG_TEXT", "").lower() in ("1", "true", "yes"),
            tag=env.get("AGENTCAR_LOG_TAG", ""),
        )

    def record(self, event: dict[str, Any], text: str = "") -> None:
        """Ghi hỏng thì thôi — telemetry không bao giờ được làm sập agent."""
        if not self.enabled or self.path is None:
            return
        if self.tag:
            event = {**event, "tag": self.tag}
        if self.keep_text and text:
            event = {**event, "text": text}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            pass


# ----------------------------------------------------------------- tổng hợp
def load(path: Path | str = DEFAULT_PATH) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue           # dòng hỏng thì bỏ, đừng làm hỏng cả báo cáo
    return rows


def _pct(n: int, total: int) -> str:
    return f"{n / total:5.1%}" if total else "    —"


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * q), len(ordered) - 1)]


def only_real(rows: list[dict]) -> list[dict]:
    """Bỏ các lượt do script đo sinh ra."""
    return [r for r in rows if not r.get("tag")]


def summarize(rows: list[dict]) -> str:
    if not rows:
        return "chưa có số liệu nào (chạy vài câu rồi xem lại)"

    total = len(rows)
    cloud = [r for r in rows if r.get("path") == "cloud"]
    tagged = len(rows) - len(only_real(rows))
    out = [f"{total} lượt  |  lên cloud {len(cloud)} ({_pct(len(cloud), total)})"]
    if tagged:
        out.append(f"CẢNH BÁO: {tagged} lượt do script đo sinh ra — dùng --real để loại")

    def group(key: str, title: str) -> None:
        counts: dict[Any, int] = {}
        for r in rows:
            counts[r.get(key)] = counts.get(r.get(key), 0) + 1
        out.append(f"\n{title}")
        for value, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            out.append(f"  {str(value):20} {n:5}  {_pct(n, total)}")

    group("label", "Nhãn (lý do tầng edge trượt)")
    group("checkpoint", "Dừng ở chốt nào")
    group("verdict", "Kết quả")

    latency = [r["ms"] for r in rows if isinstance(r.get("ms"), (int, float))]
    out.append(f"\nĐộ trễ cả lượt   p50 {_quantile(latency, .5):.0f}ms  "
               f"p90 {_quantile(latency, .9):.0f}ms  max {max(latency, default=0):.0f}ms")
    if cloud:
        cms = [r["cloud_ms"] for r in cloud if isinstance(r.get("cloud_ms"), (int, float))]
        out.append(f"Riêng vòng cloud p50 {_quantile(cms, .5):.0f}ms  "
                   f"p90 {_quantile(cms, .9):.0f}ms  max {max(cms, default=0):.0f}ms")
        kinds: dict[Any, int] = {}
        for r in cloud:
            kinds[r.get("cloud_kind")] = kinds.get(r.get("cloud_kind"), 0) + 1
        out.append("Cloud trả về:    " + ", ".join(f"{k}={n}" for k, n in kinds.items()))

        # Câu hỏi quan trọng nhất: model đề xuất rồi bị caps chặn bao nhiêu lần?
        rejected = [r for r in cloud if r.get("cloud_kind") == "commands"
                    and r.get("verdict") == "INVALID"]
        out.append(f"Cloud bịa/sai bị chặn: {len(rejected)}/{len([r for r in cloud if r.get('cloud_kind') == 'commands'])}"
                   " lệnh — quyết định có đáng làm vòng sửa lỗi không")
        errors = [r["cloud_error"] for r in cloud if r.get("cloud_error")]
        if errors:
            out.append(f"Lỗi cloud: {len(errors)} lượt")
    return "\n".join(out)
