# AgentCar

Trợ lý giọng nói tiếng Việt điều khiển thiết bị trên ô tô. Người dùng nói tự
nhiên — *"nóng quá, ghế lái lạnh ngang, tăng thêm 1 mức"* — hệ thống dịch thành
lệnh có cấu trúc rồi kiểm tra an toàn trước khi cho chạy.

30 thiết bị, 146 ý định, bộ test 24.851 câu.

## Bài toán

Ba ràng buộc kéo ngược nhau:

- **Độ trễ.** Người ta nói xong là muốn xe phản ứng. Ngân sách 1.200ms, tính cả
  mạng.
- **Mạng chập chờn.** Xe đi vào hầm. Không thể phụ thuộc hoàn toàn vào cloud.
- **Ra lệnh oan nguy hiểm hơn không hiểu.** Không hiểu thì người ta nói lại.
  Hiểu nhầm thì cửa kính tự hạ giữa đường.

Ràng buộc thứ ba quyết định toàn bộ thiết kế: hệ thống **thà im còn hơn đoán**.

## Kiến trúc

Ba tầng, câu nào xử lý được sớm thì dừng sớm.

```
câu nói
   │
   ├─ [1]  luật + từ điển          ~0,5ms   trên xe
   │       khớp mẫu, không học máy. Xử lý 80% lưu lượng.
   │
   ├─ [1b] BERT 14,5M tham số      ~4ms     trên xe
   │       gán nhãn BIO theo token → nhiều lệnh trong một câu
   │
   └─ [2]  LLM qwen-plus           ~850ms   cloud
           chỉ gọi khi hai tầng trên bó tay (~20% câu)
   │
   ▼
resolve → safety → thực thi
```

Ba tầng không thay thế nhau mà **lọc dần**: tầng luật nhanh và chắc chắn nhưng
cứng; tầng model mềm nhưng chậm và đắt. Cái khó không nằm ở từng tầng mà ở chỗ
**quyết định khi nào leo tầng**.

Sau cả ba tầng vẫn còn hai cửa:

- `resolve` — đối chiếu lệnh với năng lực thật của xe. Model nói "bật sưởi hàng
  ghế 3" mà xe không có hàng 3 thì sửa hoặc bỏ, không chuyển xuống.
- `safety` — luật vật lý. Không mở cốp khi xe đang chạy 72 km/h, bất kể cần số
  đang ở đâu.

## Xử lý câu nhiều lệnh

Tầng `[1b]` gán nhãn **theo từng token** chứ không phân loại cả câu, nên một câu
ra được nhiều lệnh và biết tham số nào thuộc lệnh nào:

```
bật điều hòa 22 độ    rồi    mở cửa kính bên lái
└── B-hvac.set ───┘    O     └── B-window.open ──┘

→ hvac.set    {value: "22 độ"}
→ window.open {zone: "bên lái"}
```

Chỗ cắt do chính model chỉ ra — mỗi nhãn `B-` mở một lệnh mới. Cách phân loại cả
câu thì biết *có những ý định nào* nhưng không biết *"22 độ" thuộc lệnh nào*.

## Kết quả

| | | |
|---|---|---|
| **tầng cloud** | **77,2%** | 738 câu |
| tầng trên xe | 54,0% | 24.851 câu |
| độ trễ | 848ms thường · 1.057ms chậm nhất trong 9/10 lần | hạn 1.200ms |

"Đúng" ở đây nghĩa là **đúng cả câu** — sai một trường là trượt. Đúng thiết bị
nhưng nhầm vùng vẫn tính sai, vì lệnh sai một trường là lệnh sai.

Cả hai con số đo trên bộ test 24.851 câu, bằng `tools/score_fields.py` và
`tools/score_cloud.py`.

## Chạy thử

```bash
pip install -r requirements.txt

python -m agentcar run "bật sưởi ghế lái mức 2"
python -m agentcar run "mở cửa kính" --gear D --speed 40 --trace
python -m agentcar repl                    # gõ liên tục
python -m agentcar serve                   # giao diện web, có nút mic

pytest -q                                  # 1.281 test
python tools/score_fields.py               # chấm tầng trên xe
python tools/score_cloud.py --mau 500      # chấm tầng cloud (cần API key)
```

Tầng cloud cần `DASHSCOPE_API_KEY` trong `.env` — xem `.env.example`. Không có
key thì hai tầng đầu vẫn chạy bình thường.

## Cấu trúc

```
agentcar/     caps, lexicon, match, nlu, llm, resolve, safety, agent
caps/         năng lực xe + từ điển tiếng Việt, khai báo bằng YAML
tools/        bộ chấm điểm và sinh báo cáo
tests/        1.281 test, bộ golden 24.851 câu
nlu/          dữ liệu và mã huấn luyện model trên xe
```

Logic nghiệp vụ nằm trong `caps/*.yaml`, không nằm trong code. Thêm một thiết bị
là thêm một khối YAML, không phải sửa Python.
