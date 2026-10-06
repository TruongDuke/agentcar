# AgentCar — khối tất định

Bước 1–2 của agent điều khiển thiết bị xe: **caps → resolve → safety**.
Không phụ thuộc LLM, không phụ thuộc grammar, không cần xe.

## Chạy

```bash
python -m agentcar lint                       # kiểm tra caps
python -m agentcar caps                       # liệt kê 30 device
python -m agentcar caps --device seat_massage # xem vùng hợp lệ đã suy ra
python -m agentcar check hvac --action set_level --value 22.3
python -m agentcar check window --action open --gear D --speed 40 --json
python -m agentcar lex                        # thống kê từ điển
python -m agentcar lex --device ambient_light # xem alias của 1 device
python -m agentcar lex --lookup "đèn viền"    # tra 1 chuỗi
python -m agentcar run "bật sưởi ghế lái mức 2"
python -m agentcar run "mở cửa kính" --gear D --speed 40 --trace
python -m agentcar run "..." --fresh          # bỏ trạng thái thiết bị đã lưu
python -m agentcar repl                       # gõ liên tục, :set gear=D
python -m agentcar repl --speak               # đọc câu trả lời (giọng vi_VN của macOS)
python -m agentcar repl --scenario scenarios/city_drive.yaml   # xe tự chạy theo kịch bản
python -m agentcar run "gập gương" --scenario scenarios/city_drive.yaml --at 20
python -m agentcar devices                    # bảng trạng thái thiết bị trong terminal
python -m agentcar devices --watch --all      # vẽ lại liên tục, kèm thiết bị chưa biết
python -m agentcar devices --baseline         # đặt mọi thiết bị về mốc xuất phát
python -m agentcar serve --baseline           # khoang lái: http://127.0.0.1:8765, dùng chung state với CLI
python -m agentcar eval                       # độ phủ: 216 câu phải ra lệnh đúng
python -m agentcar eval tests/golden_negative.vi.yaml   # độ chính xác: 81 câu phải im
python -m agentcar config                     # xem cấu hình tầng [2] (key bị che)
python -m agentcar stats --real               # thống kê, bỏ lượt do script đo sinh ra
pytest                                        # 1052 test, không chạm mạng
AGENTCAR_LIVE=1 pytest tests/test_llm_live.py tests/test_hard_live.py  # gọi thật
```

`check` trả exit code 0 khi OK, 2 khi bị chặn/không hợp lệ.

## File

| File | Vai trò |
|---|---|
| `caps/vf9.yaml` | Bản khai năng lực + policy của VF9. **Nguồn sự thật.** |
| `caps/actions.yaml` | Catalog action canonical theo type. Không phụ thuộc dòng xe. |
| `caps/reasoning.vi.yaml` | Luật suy luận cho tầng [2] — prompt sinh từ đây |
| `caps/lexicon.vi.yaml` | Tên tiếng Việt cho device/zone/mode/unit/action. |
| `agentcar/caps.py` | Loader + `effective_actions()` |
| `agentcar/catalog.py` | Loader catalog + nhóm mode loại trừ nhau |
| `agentcar/resolve.py` | Tầng [3]: xác nhận bằng caps + clamp/snap/nudge |
| `agentcar/safety.py` | Tầng [4]: parse `when`, eval theo `VehicleState` |
| `agentcar/engine.py` | `decide()` = resolve + safety |
| `agentcar/lexicon.py` | Chuẩn hoá + index alias + coverage/xung đột |
| `agentcar/numbers.py` | Đọc số tiếng Việt: "hai mươi ba" → 23 |
| `agentcar/match.py` | Tầng [1]: câu tiếng Việt → RawCommand (tầng edge) |
| `agentcar/agent.py` | Nối [1] với [3][4]; vòng xác nhận; không khớp → ESCALATE_UNKNOWN |
| `.env` | Key DashScope — đã gitignore, mẫu ở `.env.example` |
| `agentcar/config.py` | Đọc `.env`; biến môi trường thật thắng |
| `agentcar/assistant.py` | Trợ lý chung: câu ngoài miền xe + nguồn thời tiết |
| `agentcar/reasoning.py` | Nạp luật, lọc theo caps, sinh phần luật trong prompt |
| `agentcar/telemetry.py` | Ghi số liệu mỗi lượt + tổng hợp (`logs/turns.jsonl`) |
| `agentcar/triage.py` | Phân loại LÝ DO tầng edge trượt, trước khi gọi cloud |
| `agentcar/llm.py` | Tầng [2]: DashScope/Qwen, chỉ chạy khi tầng edge bó tay |
| `agentcar/runner.py` | Ranh giới với xe: `PlanRunner` + `MockPlanRunner` |
| `agentcar/state.py` | Trạng thái từng thiết bị + `MockStateProvider` |
| `agentcar/monitor.py` | Ranh giới với xe, chiều đọc: `SignalMonitor` + `MockSignalMonitor` |
| `agentcar/watch.py` | Bảng trạng thái thiết bị cho terminal, đọc qua file nên chạy được liên tiến trình |
| `agentcar/baseline.py` | Mốc xuất phát: đèn tắt, cửa đóng, gương mở — suy từ catalog |
| `scenarios/city_drive.yaml` | Kịch bản lái mẫu, các mốc nằm hai bên ngưỡng của caps |
| `agentcar/respond.py` | Tầng [5]: sinh câu trả lời tiếng Việt từ template |
| `agentcar/server.py` + `web/` | Giả lập khoang lái chạy tại chỗ (chỉ 127.0.0.1) |
| `agentcar/evaluate.py` | Chấm trên `tests/golden.vi.yaml` |
| `agentcar/lint.py` | Linter caps + lexicon |

## Công thức action hợp lệ

```
effective(device) = catalog[type].actions
                  − device.actions.exclude
                  + modes            (nếu type mode_as_action, vd scene_mode)
                  − set_level/increase/decrease  (nếu không có value số)
                  − set_mode/clear_mode          (nếu không có modes)
                  + query                        (nếu readable / query_only)
                  = []                           (nếu support:false / cloud_only)
```

## Quyết định đã chốt trong code

- **Thứ tự value engine**: `snap(resolution)` → `clamp(lo, hi)`. Làm tròn half-up tính từ 0.
- **Query không bị safety chặn** trừ khi rule ghi đích danh `action: query`. Nếu không, `charge_port` với rule `action: "*"` sẽ chặn cả câu hỏi trạng thái.
- **Wildcard `*`** chỉ expand ra action điều khiển, bỏ `query`.
- **DENY > CONFIRM > OK**.
- **Thiếu tín hiệu xe** (vd không đọc được `gear`) → bỏ qua rule đó và ghi note, không tự đoán.
- **`support: false`** → tên vẫn nhận diện được, mọi action trả `VA_NOT_SUPPORT` (không escalate, không gọi LLM).
- **Hai kiểu escalate**, khác nhau ở chỗ đã biết đích hay chưa:
  - `ESCALATE_ROUTED` — caps chỉ rõ ai xử lý (`cloud_only`), Result kèm `target`.
    Router chuyển thẳng, không tốn một vòng suy luận.
  - `ESCALATE_UNKNOWN` — tầng edge không khớp, chưa biết ai xử lý → cần tầng [2].
  Lưu ý: câu "dẫn đường về nhà" nói offline cho ra `ESCALATE_UNKNOWN`, **không phải**
  `ESCALATE_ROUTED` — vì `nav` cố tình không có alias tiếng Việt (caps ghi rõ "KHÔNG
  grammar edge"). `ESCALATE_ROUTED` dùng cho lệnh do tầng trên đề xuất: PlanRunner
  nhận `device: nav` là hợp lệ thay vì coi là cloud bịa.
- **Khớp chữ 3 tầng**, vì tiếng Việt có hai bẫy khác nhau:
  1. *Gộp cách đặt dấu* (tầng chính): `hòa` và `hoà` là một chữ, khoá khớp là
     "chữ đã bỏ dấu + tập dấu thanh", không quan tâm dấu rơi vào nguyên âm nào.
  2. *Bỏ dấu hoàn toàn* (dự phòng): áp cho cả alias **và số đọc bằng chữ**
     ("hai muoi ba do ruoi" = 23,5). Chỉ dùng khi câu vào **vốn không có dấu** —
     tức ASR mất dấu. Nếu không giới hạn thế, "làm gì **đó** đi" sẽ khớp thành
     màu **đỏ**, và `độ`/`đỏ`, `cam`/`câm` lẫn lộn hết.
- **D1 — Mode chia nhóm độc lập**: `fan` có airflow/intake, `ambient_light` có color/effect.
  Đặt mode nhóm này không xoá mode nhóm kia; command trả kèm `mode_group`.
- **D2 — `exclude` thắng `modes`** khi caps khai cả hai (`fx_none`) → `VA_MODE_EXCLUDED`,
  tách khỏi `VA_INVALID_MODE` để trả lời cho đúng. *Tạm chốt.*
- **D3 — `scene_mode`**: bật bằng tên mode (`camp`), tắt bằng `turn_off(mode=camp)`, bắt buộc kèm mode.
- **D4 — `volume` không có mute/unmute**: "tắt tiếng" = `set_level(0)`. "Bật tiếng lại" cần
  nhớ mức cũ — việc của tầng agent, không phải action thiết bị. *Tạm chốt.*
- **D5 — `screen_control` chỉ có `open`**; `app_control` có cả `open` và `close`.
- **D6 — Làm tròn half-up** tính từ 0, rồi mới clamp.
- **M3 — tuyệt đối hay tương đối phân biệt bằng từ nối, không bằng động từ**:
  "giảm điều hoà xuống 20 độ" → `set_level(20)`; "giảm 2 độ" → `decrease(2)`.
- **M5 — kế thừa thiết bị** chỉ khi câu trông như mảnh lệnh (có động từ hoặc số),
  nên "dẫn đường về nhà" không dính thiết bị của lượt trước mà rơi xuống escalate.
- **T1 — Phân loại lý do trượt TRƯỚC khi gọi cloud** (`triage.py`). Đo trên 130 câu:
  80% tầng edge lo được; trong 26 câu trượt thì `off_domain` 77%, `device` 15%,
  `not_now` 8%, `slot` **0%**.
  - `slot` rỗng **do cấu trúc**: hễ câu nhắc được tên thiết bị thì tầng edge đã ghép
    được lệnh. Nên ý "rút gọn digest theo thiết bị được nhắc" không có lưu lượng.
  - `off_domain` **không tách nhỏ được bằng từ điển**: "nóng quá" và "hôm nay trời
    đẹp quá" cùng không có alias, không có động từ. Lớp này vẫn phải gọi cloud.
  - Chỉ `device` + `not_now` xử tại chỗ. Lợi ích thật không phải 750ms mà là
    **vẫn trả lời được khi mất mạng**.
- **M5b — Chỉ kế thừa thiết bị khi thiết bị đó LÀM ĐƯỢC việc đang nói.** Telemetry
  bắt được ngay ở phiên chạy thật đầu tiên: sau "mở spotify", câu "tắt tiếng" bị gán
  vào `app_control` rồi đẩy lên cloud, "bật đèn" cũng vậy. Sửa xong tỉ lệ lên cloud
  giảm từ 31% xuống 19% trên cùng kịch bản.
- **T4 — Tham chiếu mơ hồ ("cái kia", "cái đó") mà KHÔNG suy ra được thiết bị →
  hỏi xác nhận tại chỗ, 0ms, không gọi cloud.** Danh sách từ mơ hồ khai ở
  `caps/reasoning.vi.yaml` và dùng cho hai việc: sinh vào prompt (gợi ý cho model)
  và làm điều kiện cho chốt tất định này.
  - Điều kiện "**không** suy ra được" là chỗ quan trọng: `"cái đó tắt đi"` sau
    `"bật đèn viền"` vẫn chạy thẳng ở chốt 2, không bị hỏi.
  - Câu hỏi dựng bằng **đúng chữ người ta nói** + tên thiết bị vừa nhắc, rồi đưa
    vào hàng chờ xác nhận — trả lời "ừ" là chạy, "thôi" là huỷ.
  - Chọn action **ưu tiên loại không cần giá trị**: "chỉnh cái kia lên" dùng
    `increase`, vì `set_level` lại phải hỏi thêm "mức bao nhiêu".
- **T2 — Hỏi lại phải kèm lựa chọn, sinh từ caps**: "bật đèn" → "đèn viền, đèn trần
  hay đèn sương mù?". Không bao giờ nhắc thứ xe không có (`auto_highbeam`).
- **T3 — Nhớ động từ đã hỏi.** "tắt" → "tắt cái gì?" → "đèn viền" phải ra `turn_off`.
  Không nhớ thì rơi vào `default_action` là **bật**, ngược hẳn ý người nói.
- **L8 — Luật suy luận là DỮ LIỆU, không phải văn xuôi trong prompt.**
  `caps/reasoning.vi.yaml` khai "cảm giác → việc cần làm" và "hoàn cảnh → việc cần
  làm"; prompt **sinh từ đó**, đã lọc theo caps của xe. Ba cái được:
  - Luật trỏ tới thiết bị xe không có thì **bị loại khỏi prompt + linter báo**,
    thay vì âm thầm dạy model làm việc không làm được.
  - **Cue trùng nhau là ERROR.** Văn xuôi không cho thấy điều đó: luật hẹn giờ từng
    nằm hai lần trong cùng một prompt mà không ai biết.
  - Thêm dòng xe mới thì luật tự lọc: với `tests/fixtures/mini.yaml` (chỉ có
    `window`), 13/14 luật tự biến mất khỏi prompt.
  Cách làm việc: có case khó mới → thêm case vào `golden_hard.vi.yaml` cho nó fail,
  rồi thêm **một dòng dữ liệu**. Không sửa văn xuôi nữa.
- **L9 — Câu hỏi chung thì PHẢI trả lời, không từ chối máy móc.** Trước đây prompt
  dạy model "không có lệnh nào chạy được thì nói chưa làm được", nên nó từ chối cả
  `"thủ đô nước Pháp là gì"`. Giờ tách hai loại, khai ở `caps/reasoning.vi.yaml`:
  - trả lời được từ kiến thức → cứ trả lời, ngắn gọn
  - cần số liệu **cập nhật theo thời gian** (thời tiết, giao thông, tỉ giá, tin tức…)
    → nói rõ chưa xem được, **tuyệt đối không bịa số liệu**
  `"mấy giờ rồi"` và `"hôm nay thứ mấy"` KHÔNG thuộc loại hai: agent gửi kèm thời
  điểm hiện tại trong ngữ cảnh. Thứ phải ghi **bằng tiếng Việt** — ghi `(Tuesday)`
  thì model dịch nhầm thành "thứ Hai" (đã gặp thật).
- **A1 — Trợ lý chung tách khỏi tầng [2].** Prompt điều khiển xe đã 6000 ký tự và
  phải giữ kỷ luật "chỉ dùng thiết bị trong caps"; nhồi thêm hỏi đáp chung vào đó
  vừa phình vừa dễ khiến model lẫn hai vai. Tách ra thì mỗi bên một prompt ngắn, và
  trợ lý chung có chỗ riêng để cắm **nguồn dữ liệu** — thứ model không tự biết.
- **A2 — Câu hỏi thời tiết nhận ra bằng TỪ KHOÁ, khỏi gọi model để quyết định**:
  3200ms → một lượt HTTP. Cùng nguyên tắc "tất định ở đâu được thì làm ở đó".
- **A3 — Thời tiết lấy sẵn ở nền lúc khởi động**, cache 10 phút. Gọi lúc người ta
  hỏi thì mất 1–3s và **đã timeout thật** một lần. Hết hạn mà lấy lại không được thì
  dùng số cũ, còn hơn nói "chưa lấy được".
- **A4 — Giao rồi mà bên nhận không trả lời được thì PHẢI nói một câu.** Trước đó
  `"kể chuyện cười đi"` rơi vào im lặng vì handler trả None rồi fallback về
  `ESCALATE_ROUTED` (vốn cố ý im).
- **A5 — Vị trí là giả định tạm.** caps không có GPS nên `knowledge.city` khai tay
  (đổi bằng `AGENTCAR_CITY`). Bỏ bảng `CITIES` đi khi nền tảng đích cấp toạ độ thật.
- **L10 — Chỗ cắm trợ lý chung.** `knowledge.route_to` trong `reasoning.vi.yaml`:
  để trống thì tầng [2] tự trả lời (đang chạy vậy); điền tên trợ lý chung thì mọi
  câu ngoài miền xe được **chuyển sang đó** — nội dung do bên đã kiểm duyệt chịu
  trách nhiệm, không phải model của mình. Agent chuyển **kể cả khi model quên dùng
  `route`**. Lưu ý: vẫn tốn một lượt gọi để phân loại, vì không thể biết câu nào là
  hỏi chung trước khi gọi. Đổi một dòng config, không sửa code.
- **L0 — Tầng [2] là TẦNG SUY LUẬN, không phải "bộ parse dự phòng".** Nó nhận đúng
  những câu edge grammar bó tay: nói vòng, nói cảm giác, nói tắt theo ngữ cảnh,
  nhiều ý một câu, ngoài phạm vi. Contract có bốn nhánh, chọn một:
  `commands` / `ask` (thiếu thông tin, hỏi lại) / `reply` (trả lời bằng lời)
  / `route` (chuyển NavAgent).
- **L0b — Gửi kèm NGỮ CẢNH**: trạng thái xe, trạng thái thiết bị đang biết, mức
  trước khi tắt, 3 lượt gần nhất, thiết bị vừa nhắc tới. Không có nó thì chịu chết
  với "tăng thêm nữa", "cái đó tắt đi", "để lại như lúc nãy".
- **L0c — `route` chỉ nhận đích caps công nhận là `cloud_only`.** Model không tự
  đặt ra được agent mới.
- **L0d — Fast path ra lệnh DỞ DANG thì nhường tầng [2]** (thiếu giá trị/chế độ/mục).
  Hỏi lại tại chỗ chỉ là phương án cuối khi cloud im hoặc không gọi được.
- **M9 — Câu có điều kiện/hẹn giờ thì KHÔNG chạy ngay.** "Mở cửa sổ trời khi nào
  tới nhà" mà mở luôn là sai nguy hiểm.
- **L1 — LLM chỉ được đề xuất slot thô.** Đề xuất đi qua đúng tầng [3][4] như đường
  grammar, nên model không tạo được lệnh caps không xác nhận, không vượt được luật
  an toàn, và giá trị vẫn bị clamp. Tầng [2] chỉ chạy khi tầng edge bó tay.
- **L2 — Prompt chỉ liệt kê thứ xe làm được**: `support:false`, `cloud_only` và mode
  bị exclude đều không có trong digest, model khỏi phải đoán.
- **L3 — Thiếu key hoặc `ENABLED=false` thì không dựng tầng cloud**, không có đường
  nào gọi ra ngoài. `tests/conftest.py` chặn hai lớp để pytest không bao giờ tốn tiền.
- **L4 — Giữ kết nối TLS giữa các lượt, và mở sẵn lúc khởi động.** Đo VN → Singapore,
  qwen-plus: mở lại kết nối mỗi lượt cho p50 1170ms / max 2066ms (rớt 3/10 ở mốc
  1200ms); giữ kết nối cho **p50 747ms / max 838ms, rớt 0/10**. Nhờ vậy giữ được
  đúng `gate.deadline_ms: 1200` của caps thay vì phải nới deadline.
- **L5 — Mất mạng phải NÓI RA.** Im lặng là tệ nhất: người dùng không biết xe có
  nghe thấy không và sẽ nói lại nhiều lần. Lỗi mạng (`VA_LLM_UNAVAILABLE`) khác hẳn
  "model hiểu nhưng không có lệnh" (im lặng, để tầng trên trả lời).
- **L6 — Cầu dao.** Hỏng 2 lần liên tiếp thì ngưng gọi 30s, thất bại ngay lập tức
  thay vì bắt người dùng chờ hết deadline mỗi câu. Gọi được một lần là đóng lại.
  Model trả rác KHÔNG mở cầu dao — đó không phải lỗi mạng.
- **L7 — Không thử lại kết nối vừa mở.** Chỉ thử lại khi dùng lại kết nối cũ
  (phía kia có thể đã đóng). Kết nối mới mà hỏng nghĩa là mạng hỏng; thử lại chỉ
  làm người dùng chờ gấp đôi deadline rồi vẫn thất bại.
- **L5b — Chiều của lệnh là thứ tầng [3][4] không bắt được.** "lạnh quá → giảm nhiệt độ"
  vẫn là lệnh hợp lệ. Chỉ `tests/golden_llm.vi.yaml` (chạy thật) mới bắt được.
- **R1 — Câu trả lời ghép từ template, không dùng mô hình sinh**: tất định, số liệu
  lấy thẳng từ command nên không thể nói một đằng làm một nẻo, và xong trong vài µs.
  DENY/CONFIRM dùng nguyên `reason` của caps — câu đó do bên định nghĩa xe viết.
- **R2 — Alias đầu tiên trong từ điển là tên hiển thị**, nên thứ tự khai trong
  `lexicon.vi.yaml` có ý nghĩa. Ví dụ zone `rear` phải để "phía sau" trước
  "hàng ghế sau", vì `defrost`/`fog_light` cũng dùng zone đó.
- **R3 — "Bật tiếng lại" là state của hội thoại, không phải action của thiết bị**
  (hệ quả D4). Agent nhớ mức cuối cùng **chính nó** đặt và khôi phục về mức đó.
  Giới hạn: người dùng vặn núm tay thì agent không biết, vì chưa có state provider.
  Không có gì để nhớ thì hỏi lại chứ không đoán.
- **S1 — Hai loại trạng thái tách bạch**: `VehicleState` là 5 tín hiệu an toàn của
  cả xe (gear, speed, pin…) dùng cho tầng [4]; `DeviceState` là trạng thái từng
  thiết bị dùng để trả lời câu hỏi. Không trộn.
- **X1 — Chỉ cập nhật trạng thái KHI XE XÁC NHẬN.** Trước đây agent tự ghi trạng
  thái ngay khi tầng an toàn cho phép — tức tin rằng lệnh đã chạy trong khi chưa ai
  gửi nó xuống xe. Với xe thật, lệnh có thể bị CAN từ chối hoặc ACK muộn: agent đã
  nói "đã bật" và đã ghi trạng thái, **sai hai lần**. Giờ plan đi qua `PlanRunner`,
  xe từ chối thì không ghi gì và nói `VA_EXEC_FAILED`.
- **X2 — Câu hỏi trạng thái không gửi xuống xe.** `query` không phải lệnh.
- **X3 — Bộ test hợp đồng sinh từ caps** (`tests/test_contract.py`, 184 ca). Ngày có
  adapter thật, thêm nó vào `PROVIDERS`/`RUNNERS` là biết ngay đúng/sai, thay vì dò
  tay 30 thiết bị. Hợp đồng tách rõ: lệnh tuyệt đối thì "chạy xong phải đọc lại
  được", còn `increase`/`decrease`/`clear_mode` là lệnh delta — chưa biết mức cũ thì
  **không được đoán**.
- **S3 — Trạng thái thiết bị ghi ra `logs/device-state.json` khi chạy qua CLI.**
  Mỗi lần `agentcar run` là một tiến trình mới; không lưu thì câu hỏi trạng thái
  luôn trả "chưa biết" và `run` thành vô dụng cho truy vấn. **Mặc định trong thư
  viện là KHÔNG ghi file** — chỉ CLI bật, để test không sinh rác. `--fresh` để bỏ.
- **S2 — `MockStateProvider` chỉ biết cái agent đã đặt.** Người dùng vặn núm tay thì
  nó không biết, và nó nói "chưa biết" chứ không đoán. Tăng/giảm khi chưa biết mức
  cũ cũng không suy ra mức mới. Adapter thật chỉ cần cài đúng `StateProvider`.
- **C4 — Câu hỏi không huỷ lệnh đang chờ xác nhận**; chỉ lệnh mới mới thay thế.
- **C1 — Đồng ý không phải giấy thông hành**: khi người dùng xác nhận, trạng thái xe
  được **kiểm lại tại thời điểm đó**; xe tăng tốc trong lúc chờ thì lệnh bị từ chối.
  `confirmed=True` chỉ bỏ qua CONFIRM, **không bao giờ bỏ qua DENY**.
- **C2 — Lệnh chờ hết hạn sau 30s**, và câu mới bất kỳ sẽ thay thế lệnh đang chờ.
- **C3 — Câu trả lời đồng ý/từ chối so khớp TRỌN câu**: "không" một mình là từ chối,
  còn "cửa kính mở không" vẫn là câu hỏi.
- **M6 — "…không / …chưa" cuối câu là câu hỏi**, thắng cả động từ đứng trước.
- **M16 — Hư từ cũng phải so trên dạng BỎ DẤU.** Mọi tập từ chức năng (từ nối,
  giới từ đích, từ sửa ý, từ hỏi, trợ từ giục) trước đây so chuỗi có dấu, nên câu
  ASR mất dấu đi qua hết: `"tang dieu hoa len 24 do"` ra `increase step=24` thay vì
  `set_level=24`; `"...voi ca den tran"` mất hẳn lệnh thứ hai; `"a nham 26"` bị bỏ qua.
  - **M17 — Dạng kết hợp của số** (`lăm`, `nhăm`, `tư`) chỉ là số khi đứng sau
    `mười`/`mươi`. Đứng một mình thì không: `nhăm` bỏ dấu trùng `nhầm` (sửa ý), nên
    `"điều hoà nhầm rồi"` từng bị đọc thành **đặt mức 5**. Nhưng `một`/`mốt` cùng ra
    `mot` nên KHÔNG chặn được `mot`.
  - **Từ sửa ý cũng chỉ tính khi là chữ lẻ**: `"bật điều hoà hai mươi nhăm độ"` từng
    bị cắt mất số, vì `nhăm` bị nhận là `nhầm`.
  - **Nhưng từ hỏi thì chỉ tính khi là CHỮ LẺ**, không nằm trong alias nào:
    `"máy"` trong `"máy lạnh"` bỏ dấu thành `"may"`, trùng `"mấy"` → `"bật máy lạnh
    lên 26 độ"` từng biến thành câu **hỏi**. Cùng họ bẫy `đỏ`/`độ`, `cam`/`câm`.
- **M20 — Động từ YẾU phải có số đi kèm mới là lệnh.** `để` là alias của
  `set_level` vì `"để 22 độ"` là lệnh thật, nhưng phần lớn thời gian nó là liên từ
  mục đích hoặc nằm trong danh từ ghép. Trong 500 câu `stress_test_gpt_v2`, `để`
  xuất hiện 41 lần và **không lần nào** đứng trước một con số. Hại thật:
  `"cái chỗ ĐỂ đồ phía trước ấy, mở nó ra giùm"` (xin mở cốp trước) — `để` làm tập
  thiết bị của vùng `front` hẹp lại còn mỗi `fan` (`defrost`/`fog_light` không
  `set_level` được), lọt qua cả M18, và xe **bật quạt**.
- **M19 — Từ sửa ý LẺ chỉ tính khi ngay sau nó là alias hoặc số.**
  `"thôi đóng lại"` là sửa thật; `"cho KHÔNG gian thêm hứng khởi"` thì `không` chỉ
  là nửa của `không gian`. Trước đây `"mở ứng dụng nhạc lên cho không gian thêm
  hứng khởi"` bị cắt mất nửa đầu, nên `nhạc` rơi về nghĩa thứ hai (kênh âm lượng
  của `volume`) và agent đi **tăng âm lượng** thay vì mở app. Cụm hai chữ
  (`à không`, `không phải`) vẫn đi đường CORRECTION như cũ.
- **M18 — Vùng chỉ suy ra thiết bị khi DUY NHẤT**, đúng như M2 nói — nhưng trước
  đây chỉ MODE bị kiểm tra. `phía trước` thuộc cả `fan`/`defrost`/`fog_light` nên
  thứ tự chèn alias quyết định. Nhập nhằng thì trả về không biết, để tầng trên hỏi
  lại hoặc cloud suy; im lặng chọn bừa rồi chạy luôn là kiểu sai tệ nhất.
- **X4 — Câu nhiều mệnh đề: bỏ mệnh đề ra lệnh DỞ DANG nếu mệnh đề khác đã ra lệnh
  được.** `"cái quạt ở nhà anh ĐỂ đâu rồi... à mà bật sưởi ghế lái đi"` — chữ `để`
  bị nhận là `set_level` nên sinh thêm lệnh quạt thiếu giá trị; hỏi "đặt quạt mức bao
  nhiêu" trong khi người ta đang nói về ghế là vô nghĩa.
- **M15b — Sửa ý có thể đổi cả THIẾT BỊ và VÙNG**, không chỉ tham số:
  `"bật sưởi ghế à không làm mát ghế"` → `seat_cooling`;
  `"sưởi ghế lái mức 2 à nhầm ghế phụ"` → `zone=passenger`.
  Chỉ giữ tên thiết bị/vùng ở phần đầu khi phần SAU không nêu cái mới.
- **M15 — Sửa ý giữa câu: chỉ xét phần SAU từ sửa.** `"bật điều hòa 24 độ à không
  22 thôi"` từng đặt **24**. Tên thiết bị ở phần đầu vẫn giữ (`điều hòa`), chỉ tham
  số bị thay. `"thôi"` chỉ tính là sửa ý khi **còn chữ đằng sau** — `"mở cốp thôi"`,
  `"bật điều hòa đi thôi"` là giục, không phải sửa.
- **M12 — Chọn thiết bị theo MỆNH ĐỀ CÓ ĐỘNG TỪ, không phải "alias nào thấy trước".**
  `"hôm nay tắc đường kinh khủng mà trời nóng nên bật điều hòa 22 độ đi"` từng ra
  **hạ cửa kính** — chữ `"kinh"` trong `"kinh khủng"` là alias của cửa kính và đứng
  trước. Thứ tự quyết định: ứng viên **làm được** việc đang nói → ứng viên **gần
  động từ** nhất → ưu tiên tên thiết bị > mục > chế độ > vùng. Lớp này (`needle`)
  lấy từ bảng phân loại Audio2Tool.
- **M13 — Mảnh không có thiết bị VÀ không có động từ là THAM SỐ của mảnh trước**,
  không phải lệnh mới: `"massage ghế với mức 2"` là một lệnh.
- **M14 — Động từ áp cho cả hai vế.** `"tắt đèn viền với cả đèn trần"` — vế sau
  không có động từ, dùng `default_action` là **bật** thì ngược hẳn ý người nói.
- **M11 — Nhắc tên thiết bị mà KHÔNG có động từ, câu lại còn nhiều chữ lạ → không
  phải lệnh.** `"cái quạt ở nhà hỏng rồi"` từng bật quạt; `"bạn có hiểu tiếng Việt
  không"` từng truy vấn âm lượng (vì `"tiếng"` là alias). Hư từ (`đang`, `rồi`,
  `giúp`, `cho`…) **không tính là chữ lạ**, nếu không thì `"sưởi ghế đang mức mấy"`
  cũng bị chặn oan.
- **M10 — Chế độ gọi bằng MỘT chữ không được dùng để suy thiết bị.** "vàng", "đỏ",
  "cam", "nâu", "nhảy", "morse" đều là từ thường ngày: `"giá vàng hôm nay"` từng bị
  hiểu thành **chuyển đèn viền sang màu vàng**, `"đèn đỏ phía trước"` thành bật đèn
  đỏ. Cụm hai chữ trở lên ("lấy gió trong", "cắm trại", "làn sóng") thì đủ đặc thù
  để tin. `"đèn viền màu vàng"` vẫn chạy vì có tên thiết bị.
- **A6 — Model chỉ có một tool thì nó dùng bừa.** `"giá vàng hôm nay"` từng được trả
  lời bằng **thời tiết**. Chỉ tin `tool: weather` khi câu thật sự hỏi thời tiết.
- **A7 — Lọc chữ nước ngoài trước khi đọc.** Qwen là model Trung Quốc và có lẫn chữ
  Hán: *"cập nhật giá vàng 实时"*. Câu sẽ được đọc to nên phải lọc; mất quá 15% ký tự
  thì bỏ hẳn câu.
- **M8 — Nghe rõ động từ mà không biết thiết bị thì HỎI LẠI tại chỗ**, đừng gọi cloud:
  model cũng không đoán được "bật" là bật cái gì. Chỉ áp dụng khi câu gần như chỉ có
  mỗi động từ; câu còn nhiều chữ lạ ("mở hết cỡ đi") vẫn để tầng [2] thử.
- **G1 — `gate.min_tokens` trong caps**: câu ngắn hơn ngưỡng thì không đoán, không
  đẩy lên cloud. Câu rỗng luôn bị chặn, bất kể gate bật hay tắt. VF9 đang để
  `enabled: false` nên chỉ chặn câu rỗng.
- **M7 — quét lại khi thiếu thông tin bắt buộc**: longest-match làm "tắt tiếng" nuốt
  mất "tiếng" (volume). Chỉ chạy khi không xác định được thiết bị/mục, nên không phá M1.
- **Longest match** khi tra alias: `độ sáng màn hình` thắng `màn hình`,
  `màn hình áp suất lốp` thắng `áp suất lốp`. 230 cặp lồng nhau, linter liệt kê hết.

Tất cả đều đảo được bằng cách sửa 1 hàm; không rải rác trong code.

## Giả lập khoang lái

`python -m agentcar serve` → mở http://127.0.0.1:8765. Dùng để **tự test cho nhanh**:

- Sơ đồ khoang lái: 4 ghế (sưởi/mát/massage/nhiệt độ), 4 cửa kính đổ mực theo % mở,
  cửa sổ trời, rèm, gương, cốp, nắp sạc — tất cả vẽ từ `MockStateProvider`.
- Thanh trạng thái xe: gear / tốc độ / pin / sạc / phanh tay, đổi một cú kéo, và
  hiện luôn luật an toàn nào đang kích hoạt.
- Gõ lệnh hoặc **bấm mic nói tiếng Việt** (Web Speech API của trình duyệt, không
  cần ASR bên ngoài); bật "đọc trả lời" thì nghe được câu trả lời.
- Nhật ký từng lượt: verdict, câu nói ra, plan JSON và trace.

Server chỉ nghe trên `127.0.0.1` và không có gì ở đây dành cho môi trường thật.

## Làm sao biết output đi đúng tầng

Ba cách, từ thủ công tới tự động:

1. **`--trace`** trên `run`/`repl`: in ra suy thiết bị kiểu gì, có gọi cloud không, mất bao lâu.
2. **Trường trong `Turn`**: `checkpoint` (1 gate · 2 tầng edge · 3 điều kiện · 4 hỏi
   tại chỗ · 5–6 cloud), `label`, `cloud_ms`, `cloud_kind`. Dùng để kiểm bằng code.
3. **Telemetry + `stats`**: xem phân bố trên nhiều lượt.

Và quan trọng nhất: **hai bộ golden khoá luôn tầng**, vì kết quả đúng mà đi sai
đường vẫn là sai — câu thường lọt lên cloud thì vừa chậm vừa tốn tiền, câu cần suy
luận mà bị tầng edge chộp thì ra lệnh sai.

```yaml
# golden.vi.yaml — khoá các tầng tại chỗ
- { say: "bật điều hòa",            expect: { checkpoint: 2, path: local, label: none } }
- { say: "5 phút nữa bật điều hòa", expect: { checkpoint: 3, path: local, label: not_now } }
- { say: "bật đèn",                 expect: { checkpoint: 4, path: local, label: device } }

# golden_hard.vi.yaml — khoá tầng cloud
- { path: cloud, say: "nóng quá", kind: commands, device: hvac }
```

## Hai thước đo, không phải một

| | Đo gì | Hiện tại |
|---|---|---|
`golden.vi.yaml` | **độ phủ** — câu có lệnh thì bắt được không | 216/216 |
`golden_negative.vi.yaml` | **độ chính xác** — câu KHÔNG phải lệnh thì im được không | 89/89 |

Trong xe, **ra lệnh oan tệ hơn không hiểu**: không hiểu thì người ta nói lại, còn
ra lệnh oan thì cửa kính tự hạ giữa đường. Tập âm gồm: từ thường ngày trùng alias
(`giá vàng`, `kinh khủng`, `quả cam`), nói với người trong xe, đọc biển báo, tán
gẫu, ASR nhiễu, việc ngoài khả năng của xe.

Lần đầu chạy tập âm ra **95,1%** — 4 câu ra lệnh oan, tất cả cùng một nguyên nhân
(xem M11).

## Dùng dataset ngoài để biết mình THIẾU gì

`data/` (gitignore) chứa hai bộ tải về: **MAC-SLU** (20.542 câu tiếng Trung, có gán
nhãn intent/slot) và **Audio2Tool** (tiếng Anh, 86 tool cho xe, chia 8 tầng độ khó).

Không dùng làm dữ liệu test — sai ngôn ngữ, sai tập thiết bị. Dùng để **đối chiếu**:

- **Bảng phân loại case khó** (Audio2Tool 8 tier) → lộ ra 3 lớp mình chưa test và
  sai cả ba: `needle` (M12), `blending` (M13+M14), `correction` (M15).
- **Bảng thiết bị** (MAC-SLU, 389 loại) → caps VF9 phủ 79%; thiếu chỉnh vị trí ghế,
  khoá–mở cửa xe, đèn pha/cos.
- **tier4_implicit** (166 câu tả cảm giác, không nêu tên thiết bị) → đúng bộ test cho
  tầng [2]. Đối chiếu thì luật của mình phủ 6/12 thiết bị → thêm 4 luật có bằng chứng.

Nguyên tắc: **thêm luật chỉ khi có bằng chứng ngoài**, không phải mình nghĩ ra rồi vá.

## Telemetry

Mỗi lượt ghi một dòng JSON vào `logs/turns.jsonl`: nhãn triage, dừng ở chốt nào,
có lên cloud không, độ trễ, verdict, mã lỗi, plan. `python -m agentcar stats` tổng hợp.

- **Mặc định KHÔNG ghi câu nói.** Trong xe người ta nói cả tên người, địa chỉ,
  chuyện nhà. Muốn ghi phải bật `AGENTCAR_LOG_TEXT=1` một cách có chủ ý.
- `AGENTCAR_LOG=off` tắt hẳn; test luôn chạy với cờ này để không làm bẩn số liệu.
  **Bộ live test phải tự đặt lại cờ này** vì nó ghi đè fixture của conftest — đã
  từng rò và nhồi mấy chục lượt giả vào log.
- `AGENTCAR_LOG_TAG=...` cho script đo tự khai nguồn. Lượt **không có tag** mới là
  lượt thật; `stats --real` lọc phần còn lại, và `stats` cảnh báo nếu log bị lẫn.
- Telemetry hỏng thì thôi, không bao giờ được làm sập agent (có test riêng).

Câu hỏi nó sinh ra để trả lời: **model bịa lệnh sai bao nhiêu phần trăm** — con số
quyết định có đáng làm vòng sửa lỗi (gửi lỗi validate ngược lại cho model) hay không.

## Chưa làm (chờ chốt)

- Adapter `StateProvider` thật (thay `MockStateProvider`) — phụ thuộc nền tảng đích
- Adapter PlanRunner thật — `MockPlanRunner` đã chạy, `Command.to_dict()` vẫn là schema giả định
- Xác nhận D2 và D4 với bên định nghĩa xe (linter đang nhắc mỗi lần chạy)
