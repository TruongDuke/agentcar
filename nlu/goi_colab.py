"""Gói những file Colab cần. Sinh dữ liệu ở máy, chỉ đẩy phần train lên."""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Giữ ĐÚNG cây thư mục của repo: train.py tính ROOT theo vị trí của chính nó,
# đặt phẳng ra là nó không tìm thấy tests/golden trên Colab.
CAN = ["nlu/train.py", "nlu/data/synth.jsonl",
       "tests/golden.vi.yaml", "tests/golden_hard.vi.yaml",
       "tests/golden_negative.vi.yaml"]   # 96 câu phải im lặng, doc_golden() cần

out = ROOT / "nlu" / "colab_bundle.zip"
thieu = [f for f in CAN if not (ROOT / f).exists()]
if thieu:
    raise SystemExit("thiếu file: " + ", ".join(thieu) + "\nchạy `python3 nlu/dataset.py` trước")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in CAN:
        z.write(ROOT / f, f)
print(f"{out}  ({out.stat().st_size/1e6:.1f} MB)")
for f in CAN:
    print(f"  {f:28} {(ROOT/f).stat().st_size/1e3:8.1f} KB")
