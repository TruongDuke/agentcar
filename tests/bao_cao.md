# AgentCar — số đo

`ccfc884` · 2026-10-06T16:45:38 · 24,851 câu (tests/golden_qc.vi.yaml)

## Số chốt

| | | |
|---|---|---|
| **tầng cloud** | **77.2%** ±3.0% | 738 câu |
| tầng trên xe | 54.0% | 24,851 câu |
| độ trễ cloud | 848ms thường · 1057ms chậm nhất trong 9/10 lần | hạn 1200ms |

**Hai dòng đầu không so với nhau được.** Mỗi câu nói ra đều chạy qua tầng trên xe trước; chỉ câu nào nó không hiểu mới gửi lên cloud. Nên 54,0% là trên tất cả 24,851 câu, còn 77,2% chỉ trên 738 câu khó đã bị đẩy lên.

**Vì sao tin được con số cloud:** chúng tôi sửa hệ thống dựa trên một nửa bộ câu, rồi chấm điểm trên nửa còn lại — nửa mà hệ thống chưa từng thấy. Hai nửa cho kết quả gần như nhau (77,7% và 77,2%), nghĩa là nó hiểu thật chứ không phải học thuộc.

**Con số 54,0% thì chưa làm bước đó**, nên nhiều khả năng thực tế thấp hơn. Tầng trên xe do nhóm khác phụ trách.

Phần dưới là chi tiết của ba dòng này.

## Tầng trên xe

| | |
|---|---|
| đúng cả câu | **54.0%** (xuất phát 21.5%) |
| độ phủ | 80.3% |
| precision | 67.2% |
| recall | 54.0% |
| F1 | 59.9% |

precision/recall tính theo **exact match**: sai một trường là sai cả câu.

## Từng trường

| trường | |
|---|---|
| device | 74.9% |
| action | 67.8% |
| zone | 63.0% |
| value | 62.2% |
| step | 70.6% |
| item | 60.2% |
| mode | 61.7% |

## Cổng chặn — câu KHÔNG phải lệnh

**11/137** (8.0%) câu khiến xe làm gì đó dù lẽ ra phải im.

Mẫu lệch nên con số này KHÔNG nằm trong precision ở trên. Trong xe nó quan trọng hơn: không hiểu thì người ta nói lại, ra lệnh oan thì cửa kính tự hạ giữa đường.

## Ba tầng

Hai tầng đầu chạy TRÊN XE (gọi chung là edge), tầng ba ra mạng.

| tầng | chạy ở đâu | độ trễ | cộng dồn đúng cả câu |
|---|---|---|---|
| `[1]` luật + từ điển | trên xe | ~0,5ms | 42.3% |
| `[1b]` model NLU 14,5M tham số | trên xe | ~4ms | **54.0%** |
| `[2]` cloud qwen-plus | ra mạng | trung vị 848ms · p90 1057ms | 69.2% (ước tính) |

Ô cuối cùng **69.2% là PHÉP TÍNH, không phải phép đo**: lấy 54.0% của edge cộng 19.7% × 77.2%. Nó áp tỷ lệ vá của cloud — đo trên câu QC gắn nhãn *cần mạng* — cho toàn bộ phần edge bó tay, trong đó có nhiều câu gắn *trên xe* chưa từng chạy qua cloud. Số đo thật là **77.2%** ở dòng dưới.

Trần của cả hệ thống là 73.6% (54.0% + 19.7%) — đạt được khi cloud đúng 100%. Muốn vượt trần đó thì phải sửa tầng trên xe, không phải sửa cloud.

Model trên xe đóng góp **+11.7%** và kéo độ phủ từ 60.5% lên 80.3% — tức là ngần ấy câu không phải ra mạng.

Tầng `[2]` chỉ chạy khi hai tầng trên bó tay (19.7% số câu), và vá được **77.2%** trong đó (±3.0%, n=738).

Con số cloud đo trên tập QC **chưa hề dùng để chỉnh prompt** (3,000 câu QC cần mạng, chưa dùng để chỉnh prompt). Đo trên tập đã dùng để soi lỗi thì ra 77,7% — chênh 0,5 điểm, nằm trong nhiễu, nên luật là tổng quát chứ không phải vá đúng mấy câu đã nhìn.

| trường (chỉ câu đã lên cloud) | |
|---|---|
| action | 87.4% |
| device | 87.7% |
| item | 80.5% |
| mode | 82.9% |
| step | 85.5% |
| value | 82.3% |
| zone | 87.1% |

Đây là độ chính xác **hiểu câu**, so khớp tuyệt đối với nhãn QC, trên **văn bản đã đúng sẵn**. Chưa có ASR — demo đang mượn của Chrome — nên sai số nhận dạng tiếng nói chưa nằm trong con số này.

## Tiến triển tầng cloud

**Chỉ so hai ô CÙNG CỘT.** Mỗi cột là một bộ câu khác nhau; nối chéo hai cột ra mức tăng không có thật.

| prompt | việc đã làm | mẫu 500 | mẫu 3.600 | tập sạch |
|---|---|---|---|---|
| `9e9de98` | mốc xuất phát của đợt cloud | 67.1% | — | — |
| `fab6ecd` | ghế lạnh là sưởi; vô/exit khỏi X là lệnh | 71.8% | 73.7% | — |
| `5e4c1af` | digest dùng từ người nói; phủ định lấy vế sau | — | 77.7% | 77.2% |

- mẫu 500: 500 câu QC cần mạng, seed 7, n~137, biên ±7,5
- mẫu 3.600: 3.600 câu QC cần mạng, seed 7, n~960, biên ±2,8
- tập sạch: 3.000 câu seed 7 BỎ 3.600 câu đầu — chưa dùng để chỉnh prompt, n=738, biên ±3,0

Mức tăng đo được: **+4.7%** trên mẫu 500, **+4.0%** trên mẫu 3.600. Đừng cộng 4,7 + 4,0. Hai mức tăng đo trên hai mẫu khác nhau, không cộng được.

## Luật UC của BA

**62/71** đạt.

