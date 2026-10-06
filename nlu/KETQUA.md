# Kết quả train model NLU cho edge

Hai lần train, tháng 09/2026. Ghi lại làm mốc — **không lần nào đủ để dùng thật**.

## Mốc so sánh: grammar hiện tại

Chấm bằng cùng thước với model (166 câu phải ra frame, 109 câu phải từ chối):

| | frame chặt | từ chối đúng |
|---|---|---|
| grammar `agentcar/match.py` | **94,6%** | **100,0%** |

⚠️ `golden*.vi.yaml` là bộ câu người ta dùng để **phát triển** grammar — đây là sân
nhà của nó. Đừng lấy 94,6% làm ngưỡng model phải vượt.

## Lần 1 — chưa có mẫu âm, phép chấm lỏng

Thước: 160 câu, chỉ tính `device`+`action`, không đo sự im lặng.

| | frame (lỏng) |
|---|---|
| train từ số 0, không có bước 1 | 40,0% |
| thầy PhoBERT 135M | 71,3% |
| trò 13M | 60,6% |

Cho thấy chuỗi ba giai đoạn có tác dụng (40% → 60,6%). Nhưng confidence tách chỉ
0,12 (tin-khi-đúng 0,76 / tin-khi-sai 0,64) — không đặt được ngưỡng.

## Lần 2 — thêm 4.132 mẫu âm, phép chấm chặt

Thước: 166 câu phải ra frame (mọi trường bộ chuẩn khai đều phải khớp) + 109 câu
phải từ chối.

| | frame chặt | device+action | từ chối đúng |
|---|---|---|---|
| thầy PhoBERT 135M | 57,2% | 66,3% | 75,2% |
| **trò 13M (lên xe)** | **52,4%** | 56,0% | **88,1%** |

Từng trường của trò: `zone` 88% · `device` 75% · `item` 57% · `action` 54% ·
`mode` 33% (chỉ 21 ca, nhiễu) · `unit` không đo được (golden không khai ca nào).

### Đường cong ngưỡng — phần quan trọng nhất

| ngưỡng | trò: phủ | trò: đúng | thầy: phủ | thầy: đúng |
|---|---|---|---|---|
| ≥0,5 | 91% | 70,8% | 76% | 75,7% |
| ≥0,7 | 75% | 77,7% | 64% | 78,5% |
| ≥0,9 | 59% | 79,6% | 49% | 82,8% |

**Đường cong quá phẳng.** Siết từ 0,5 lên 0,9 chỉ nâng độ đúng 70,8% → 79,6% mà
mất một phần ba lưu lượng. Kể cả chỉ nhận câu model tự tin nhất, **cứ 5 lệnh thì
1 sai** — không chấp nhận được với lệnh điều khiển xe.

Luật A trong đặc tả định tuyến **vẫn chưa thực thi được**.

## Hai điều học được

**Mẫu âm có tác dụng đúng như dự đoán.** Lần 1 model chưa bao giờ thấy câu ngoài
miền nên buộc phải chọn một trong 25 thiết bị cho mọi câu. Thêm 4.132 câu ngoài
miền → từ chối đúng 88,1%. Trò còn từ chối tốt hơn thầy, vì chưng cất cho nó gặp
nhiều câu ngoài miền hơn.

**Con số đẹp giữa chừng là ảo giác.** Bản chạy dở (5k mẫu, 3 epoch) cho
`≥0,8: phủ 30% đúng 90%`. Train đủ thì mất — model chưa xong thì ít tự tin nên
ngưỡng cao lọc được; train xong nó **tự tin cả khi sai**.

## Chặn ở đâu

`action` 54% là nút thắt: model nhận ra *thiết bị nào* khá tốt nhưng không biết
người ta muốn **làm gì** với nó. Trong dữ liệu tổng hợp, action chỉ được biểu đạt
bằng vài alias động từ lấy từ lexicon — model học được cách nói của chính lexicon,
không khái quát ra cách người ta thật sự nói.

Confidence phẳng vì dữ liệu chỉ có hai thái cực: đúng hoàn toàn, hoặc ngoài miền.
Không có vùng xám — không có ví dụ "gần đúng nhưng sai" để model học cách lưỡng lự.

Cả hai đều quy về một chỗ: **chưa có câu người Việt thật nói với xe.** Hai vòng
train đã dùng hết những gì suy được từ caps + MASSIVE.
