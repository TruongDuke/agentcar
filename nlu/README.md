# nlu — model NLU chạy trên edge

Grammar ở `agentcar/match.py` là tất định: khớp hoặc trượt, không có khái niệm độ
tin cậy. Bảng định tuyến 5-case cần confidence để rẽ nhánh, nên cần một model.

Không đụng gì tới `agentcar/` — chạy xong mới bàn chuyện cắm vào.

## Ba giai đoạn

```
PhoBERT-base ──(1) MASSIVE vi-VN 16.5k──→ thân quen văn phong ra lệnh tiếng Việt
             ──(2) synth 12.4k từ caps──→ thầy 135M, biết 30 thiết bị VF9
             ──(3) chưng cất───────────→ trò 4 lớp 13M  ← thứ lên xe
```

Thầy **không** lên xe, chỉ chạy lúc train. Đo trên CPU 4 luồng: trò 2,8ms/câu,
thầy 42,8ms. Ngân sách `gate.deadline_ms` trong caps là 1200ms.

## Chạy

```bash
python3 nlu/dataset.py        # sinh nlu/data/synth.jsonl (vài giây, không cần GPU)
python3 nlu/goi_colab.py      # gói 0,1MB để upload lên Colab
```

Rồi mở `nlu/colab_train.ipynb` trên Colab (T4), upload gói, chạy tuần tự.
Ở máy cũng chạy được, chỉ lâu hơn (~60 phút MPS so với ~23 phút T4).

## Chia việc

- **Model** lo ngữ nghĩa: device, action, zone, mode, item, unit.
- **`agentcar.numbers`** lo con số — nó đã đọc đúng "hai mươi ba" → 23. Model bé
  luôn yếu ở số, đừng bắt nó học lại thứ đã có lời giải chính xác.
- **`agentcar.resolve` + `safety`** vẫn kiểm ở hạ nguồn, nên model không bịa được
  thiết bị không có trong caps.

## Hạn chế phải biết trước khi tin số

- Dữ liệu train **toàn bộ là tổng hợp** từ caps + MASSIVE. Không có câu nào do
  người Việt thật nói với xe.
- Nên `val` luôn đẹp vô nghĩa (cùng phân bố). Con số đáng tin duy nhất là
  **GOLDEN** — 160 ca người viết trong `tests/golden*.vi.yaml`.
- v0 mỗi câu ra MỘT frame. Câu nhiều lệnh chưa xử.
