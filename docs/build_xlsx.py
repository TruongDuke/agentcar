# -*- coding: utf-8 -*-
"""Dựng file Excel đặc tả định tuyến edge/cloud cho AgentCar."""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "Arial"
XANH_DAM = "1F4E79"
XANH_NHAT = "DCE6F1"
VANG = "FFF2CC"
XAM = "F2F2F2"
EDGE = "E2EFDA"
CLOUD = "FCE4EC"

vien = Border(*[Side(style="thin", color="BFBFBF")] * 4)


def kieu_tieu_de(ws, hang, so_cot):
    for c in range(1, so_cot + 1):
        o = ws.cell(row=hang, column=c)
        o.font = Font(name=FONT, size=10, bold=True, color="FFFFFF")
        o.fill = PatternFill("solid", fgColor=XANH_DAM)
        o.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
        o.border = vien
    ws.row_dimensions[hang].height = 32


def do_bang(ws, tieu_de, hang_du_lieu, rong, bat_dau=1):
    ws.append([])
    for i, t in enumerate(tieu_de, 1):
        ws.cell(row=bat_dau, column=i, value=t)
    kieu_tieu_de(ws, bat_dau, len(tieu_de))
    for r, hang in enumerate(hang_du_lieu, bat_dau + 1):
        for i, v in enumerate(hang, 1):
            o = ws.cell(row=r, column=i, value=v)
            o.font = Font(name=FONT, size=10)
            o.alignment = Alignment(vertical="top", wrap_text=True)
            o.border = vien
        ws.row_dimensions[r].height = None
    for i, w in enumerate(rong, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return bat_dau + len(hang_du_lieu)


def to_mau_cot(ws, hang_tieu_de, tu_hang, den_hang):
    """Tô Edge xanh / Cloud hồng cho cột 'Chạy ở đâu'.

    TỰ TÌM cột theo tên tiêu đề, không nhận số cột. Truyền số cột cứng đã hỏng bốn
    lần: cứ thêm một cột vào giữa bảng là mọi thứ phía sau dịch chỗ mà không có
    dấu hiệu nào báo — ô vẫn tô, chỉ là tô nhầm cột.
    """
    cot = next((c for c in range(1, ws.max_column + 1)
                if ws.cell(row=hang_tieu_de, column=c).value == "Chạy ở đâu"), None)
    if cot is None:
        return
    for r in range(tu_hang, den_hang + 1):
        v = str(ws.cell(row=r, column=cot).value or "")
        if v.startswith("Edge"):
            mau = EDGE
        elif v.startswith("Cloud"):
            mau = CLOUD
        else:
            continue
        o = ws.cell(row=r, column=cot)
        o.fill = PatternFill("solid", fgColor=mau)
        o.alignment = Alignment(vertical="top", horizontal="center", wrap_text=True)
        o.font = Font(name=FONT, size=10, bold=True)


wb = Workbook()

# ------------------------------------------------------------------ 1. Đọc trước
ws = wb.active
ws.title = "1 · Đọc trước"
ws["A1"] = "ĐỊNH TUYẾN CÂU NÓI — EDGE / CLOUD"
ws["A1"].font = Font(name=FONT, size=16, bold=True, color=XANH_DAM)
ws["A2"] = "AgentCar — VF9 · Trương Công Thái Đức (S.AI.20K) · 25/09/2026"
ws["A2"].font = Font(name=FONT, size=10, italic=True, color="666666")

gioi_thieu = [
    ("", ""),
    ("Tài liệu này mô tả gì", ""),
    ("", "Một câu nói của người dùng đi qua hệ thống theo đường nào: chỗ nào xử lý ngay trên xe "
         "(edge, không cần mạng), chỗ nào phải gọi lên cloud, và vì sao."),
    ("", ""),
    ("Ba tầng, ba loại mệnh đề khác nhau", ""),
    ("1. Cổng vào", "Câu đi QUA nó rồi mới tới case. Cổng có thể sửa đầu vào (gán vùng theo ghế "
                    "người nói) hoặc khoá bớt case (tắt chia sẻ dữ liệu thì không được lên cloud)."),
    ("2. Các case", "LOẠI TRỪ NHAU — đúng một case khớp. Xét từ trên xuống, dừng ở case đầu tiên khớp. "
                    "Thứ tự xét là một phần đặc tả: không có nó thì hai người cài ra hai hệ khác nhau."),
    ("3. Luật cắt ngang", "Áp cho NHIỀU case cùng lúc. Ví dụ an toàn áp cho cả Case 3 lẫn Case 5, "
                          "nên không thể biến nó thành một case riêng."),
    ("", ""),
    ("Quy ước màu", ""),
    ("Edge", "Chạy trên xe. Không cần mạng, không tốn tiền, ~3-10ms."),
    ("Cloud", "Gọi ra ngoài. Cần mạng, tốn tiền, đo thật p50 903ms / p90 1275ms."),
    ("", ""),
    ("Quy ước trạng thái", ""),
    ("✅ Đã có", "Code hiện tại đã làm đúng như mô tả."),
    ("⚠️ Một phần", "Có nhưng chưa đúng hoặc chưa đủ."),
    ("❌ Chưa có", "Chưa cài."),
    ("", ""),
    ("Điểm khác biệt của bản này", ""),
    ("", "Mọi câu mẫu trong sheet '6 · Câu mẫu' đều được CHẠY THẬT qua hệ thống và chép lại nguyên "
         "câu trả lời, không phải viết tay. Cột 'Trạng thái' cũng đối chiếu trực tiếp với code."),
    ("", ""),
    ("Đặc tả này đã bắt được một lỗi thật", ""),
    ("", "Luật C viết 'không bao giờ hai vòng cloud trong một lượt'. Đem đi đối chiếu code thì "
         "phát hiện câu dài nói vòng đang ăn ĐỦ HAI vòng (~1800ms, vượt trần 1200ms của caps). "
         "Lỗi này không lộ ra khi đọc code — phải có đặc tả rồi đi đếm mới thấy. Đã vá 24/09."),
]
RONG_CHU = 130      # số ký tự lọt một dòng khi gộp ô B:E

r = 4
for a, b in gioi_thieu:
    ws.cell(row=r, column=1, value=a).font = Font(name=FONT, size=10, bold=bool(a and not b))
    # Gộp B:E cho chữ có chỗ. Không gộp thì chữ bị bóp vào bề rộng cột B — mà cột
    # B lại do bảng toàn cảnh bên dưới quyết định, nên hai phần giành nhau.
    if b:
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
        o = ws.cell(row=r, column=2, value=b)
        o.font = Font(name=FONT, size=10)
        o.alignment = Alignment(vertical="top", wrap_text=True)
        # Ô gộp không tự giãn chiều cao, phải tính tay.
        ws.row_dimensions[r].height = max(15, (len(b) // RONG_CHU + 1) * 14)
    if a == "Edge":
        ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=EDGE)
    if a == "Cloud":
        ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=CLOUD)
    r += 1

# ---- Toàn cảnh: 15 mục trên một trang, để mở file là thấy hết
r += 1
ws.cell(row=r, column=1, value="TOÀN CẢNH — 15 mục").font = Font(
    name=FONT, size=12, bold=True, color=XANH_DAM)
r += 1
ws.cell(row=r, column=1, value="Chi tiết từng mục ở các sheet sau. Trạng thái đối chiếu trực "
                               "tiếp với code ngày 25/09/2026.").font = Font(
    name=FONT, size=9, italic=True, color="666666")
r += 2

td_tc = ["Thứ tự", "Mục", "Chạy ở đâu", "Câu ví dụ", "Làm gì — nói bằng tiếng thường",
         "Trạng thái"]

# None ở cột đầu = hàng tiêu đề nhóm, gộp ô và tô nền. Ba nhóm dính liền nhau
# thành một khối 15 dòng thì mắt không tách ra được.
NHOM = "__nhom__"
hang_tc = [
    [NHOM, "CỔNG VÀO — chạy trước tiên, với MỌI câu", "", "", "", ""],
    ["", "G1 · Vị trí người nói", "Edge", '(ghế sau nói) "mở cửa sổ"',
     "Biết ai đang nói thì biết mở cửa sổ ghế nào, khỏi hỏi lại.", ""],
    ["", "G2 · Ngắt lời / huỷ", "Edge", '"thôi"',
     "Người dùng đổi ý giữa chừng thì bỏ việc đang làm.", ""],
    ["", "G3 · Quyền chia sẻ dữ liệu", "Edge", "(cài đặt của người dùng)",
     "Người dùng tắt chia sẻ thì CẤM gọi ra mạng, phải tự lo trên xe.", ""],

    [NHOM, "CÁC CASE — xét lần lượt từ trên xuống, gặp cái nào đúng thì DỪNG", "", "", "", ""],
    ["1", "Case 1 · Hỏi trợ lý, không phải lệnh xe", "tuỳ nhánh",
     '"hôm nay trời thế nào" · "giá vàng bao nhiêu"',
     "KHÔNG từ chối. Thời tiết → trả lời bằng số liệu có sẵn. Thứ hệ không xem được "
     "→ nói thẳng \"chưa xem được\", không bịa. Còn lại → trợ lý trả lời.", ""],
    ["2", "Case 2 · Sửa ý giữa câu", "Edge", '"bật sưởi mức 3 à quên mức 1"',
     "Người nói đổi ý giữa câu → nghe vế sau, bỏ vế trước.", ""],
    ["3", "Case 3 · Nối tiếp lượt trước", "Edge", '"đóng lại" (sau "mở cửa kính")',
     "Câu cụt → hiểu theo thiết bị vừa nhắc ở lượt trước.", ""],
    ["4", "Case 4 · Nghi mình hiểu sai", "Cloud",
     '"...nói chuyện công việc mãi thôi bật điều hòa"',
     "Ghép được lệnh nhưng bỏ qua quá nhiều chữ → hỏi mạng kiểm lại. Mạng im thì "
     "giữ nguyên lệnh đã hiểu.", ""],
    ["5", "Case 5 · Lệnh để sau, không phải bây giờ", "Edge",
     '"khi nào tới nhà thì mở cửa sổ trời"',
     "Người dùng muốn HOÃN. Xe không hẹn giờ được → nói thẳng và mời làm ngay. "
     "Quan trọng: chặn để mạng khỏi biến ý định 'để sau' thành hành động 'ngay'.", ""],
    ["6", "Case 6 · Hiểu rõ, làm luôn", "Edge", '"bật sưởi ghế lái mức 2"',
     "Hiểu rõ → kiểm xe có làm được không, có an toàn không, rồi mới làm.", ""],
    ["7", "Case 7 · Việc của hệ khác", "Edge quyết định", '"dẫn đường về nhà"',
     "Thiết bị do hệ khác sở hữu (nav) → chuyển thẳng cho đúng chỗ, biết trước ai làm, "
     "không tốn vòng hỏi mạng.", ""],
    ["8", "Case 8 · Đang đúng sẵn rồi", "Edge", '"bật điều hòa" (đang bật)',
     "Thiết bị đã ở đúng trạng thái → nói cho biết, đừng làm lại.", ""],
    ["9", "Case 9 · Thiếu thông tin", "Edge", '"mở ứng dụng"',
     "Thiếu chi tiết → hỏi lại NGAY TRÊN XE, chỉ hỏi một lần.", ""],
    ["10", "Case 10 · Trên xe chịu, hỏi mạng", "Cloud", '"nóng quá"',
     "Trên xe không hiểu → hỏi mạng. Lệnh mạng trả về VẪN phải qua kiểm an toàn.", ""],

    [NHOM, "LUẬT — áp cho mọi case ở trên, không phải case riêng", "", "", "", ""],
    ["", "A · Bao nhiêu chắc thì mới tự làm", "Edge", "—",
     "Đặt ngưỡng: đủ chắc thì làm, lửng lơ thì hỏi lại, mù mờ thì hỏi mạng.", ""],
    ["", "B · Mất mạng thì sao", "Edge", "(xe vào hầm)",
     "Không gọi được mạng vẫn phải trả lời tử tế, không đoán bừa.", ""],
    ["", "C · Không được chậm", "cả hai", "—",
     "Một câu không quá 1,2 giây. Chỉ được hỏi mạng MỘT lần.", ""],
    ["", "D · An toàn luôn chặn", "Edge", '"gập gương" lúc 40km/h',
     "Xe đang chạy thì chặn, kể cả lệnh do mạng sinh ra. Không đường vòng.", ""],
    ["", "E · Một câu hai việc", "cả hai", '"bật điều hòa và mở cửa kính"',
     "Tách ra làm riêng từng việc. Một vế hỏng không kéo vế kia.", ""],
]

cuoi_tc = do_bang(ws, td_tc, hang_tc, [8, 34, 11, 34, 62, 24], bat_dau=r)

# Tô các hàng tiêu đề nhóm, và nối cột Trạng thái của hàng dữ liệu tới sheet chi tiết
nguon = ([f"'3 · Cổng vào'!F{i}" for i in range(5, 8)]
         + [f"'4 · Các case'!L{i}" for i in range(5, 15)]
         + [f"'5 · Luật cắt ngang'!F{i}" for i in range(5, 10)])
k = 0
for idx, h in enumerate(hang_tc):
    hang_excel = r + 1 + idx
    if h[0] == NHOM:
        ws.cell(row=hang_excel, column=1, value=None)
        ws.merge_cells(start_row=hang_excel, start_column=1, end_row=hang_excel, end_column=6)
        o = ws.cell(row=hang_excel, column=1, value=h[1])
        o.font = Font(name=FONT, size=10, bold=True, color=XANH_DAM)
        o.fill = PatternFill("solid", fgColor=XANH_NHAT)
        o.alignment = Alignment(vertical="center")
        ws.row_dimensions[hang_excel].height = 20
    else:
        ws.cell(row=hang_excel, column=6, value=f"={nguon[k]}")
        k += 1
assert k == len(nguon), (k, len(nguon))   # số hàng dữ liệu phải khớp số nguồn

to_mau_cot(ws, r, r + 1, cuoi_tc)
# ------------------------------------------------------------------ 2. Cổng vào
ws = wb.create_sheet("3 · Cổng vào")
ws["A1"] = "CỔNG VÀO — chạy trước mọi case"
ws["A1"].font = Font(name=FONT, size=13, bold=True, color=XANH_DAM)
ws["A2"] = ("Không phải case. Câu đi qua cổng rồi mới tới case. Cổng sửa đầu vào hoặc "
            "khoá bớt case khả dụng.")
ws["A2"].font = Font(name=FONT, size=10, italic=True, color="666666")

td = ["Cổng", "Ý nghĩa", "Chạy ở đâu", "Điều kiện", "Xử lý chính", "Trạng thái", "Ghi chú"]
hang = [
    ["G1 — Vị trí người nói",
     "Câu phát ra từ ghế nào",
     "Edge",
     "Mỗi lượt nói, nếu hệ thống biết mic nào thu được",
     "Gán zone mặc định theo ghế người nói. \"mở cửa sổ\" từ ghế sau ≠ từ ghế lái. "
     "Giải được ngay trên xe, KHÔNG cần hỏi lại người dùng.",
     "❌ Chưa có",
     "caps đã khai đủ zones (226 alias vùng) nhưng hệ thống chưa có đầu vào nào cho vị trí "
     "người nói — mọi câu đang mặc định coi như từ ghế lái. Cần đội phần cứng xác nhận có "
     "tách được mic theo ghế không."],
    ["G2 — Ngắt lời / huỷ",
     "Người dùng cắt ngang",
     "Edge",
     "Câu chứa từ huỷ: thôi, không phải, huỷ, khỏi",
     "Bỏ lệnh đang chờ xác nhận hoặc đang chạy. Barge-in cắt cả câu TTS đang đọc dở.",
     "⚠️ Một phần",
     "Nhận từ huỷ khi ĐANG có lệnh chờ (trả CANCELLED). Barge-in chưa có. Lưu ý \"thôi\" ở "
     "cuối câu là giục chứ không phải huỷ: \"mở cốp thôi\" = mở cốp."],
    ["G3 — Quyền chia sẻ dữ liệu",
     "Người dùng tắt gửi dữ liệu lên cloud",
     "Edge",
     "Cài đặt của người dùng, không phải nội dung câu",
     "KHOÁ Case 5. Mọi câu phải giải trên xe hoặc từ chối thật thà. Không lén gửi lên cloud.",
     "❌ Chưa có",
     "Là cổng chứ không phải luật, vì nó đổi TẬP CASE khả dụng chứ không chỉ đổi cách xử lý. "
     "Cần quyết định sản phẩm: mặc định bật hay tắt, và nói gì với người dùng khi tắt."],
]
cuoi = do_bang(ws, td, hang, [26, 26, 12, 26, 44, 13, 52], bat_dau=4)
to_mau_cot(ws, 4, 5, cuoi)
ws.freeze_panes = "A5"

# ------------------------------------------------------------------ 3. Các case
ws = wb.create_sheet("4 · Các case")
ws["A1"] = "CÁC CASE — xét từ trên xuống, dừng ở case đầu tiên khớp"
ws["A1"].font = Font(name=FONT, size=13, bold=True, color=XANH_DAM)
ws["A2"] = ("Các case LOẠI TRỪ NHAU. Thứ tự xét là một phần đặc tả — một câu có thể khớp nhiều "
            "case (\"cái đó tắt đi à quên bật lên\" vừa là sửa ý vừa là câu nối tiếp).")
ws["A2"].font = Font(name=FONT, size=10, italic=True, color="666666")

td = ["#", "Case", "Ý nghĩa", "Chạy ở đâu", "Điều kiện kích hoạt", "Xử lý chính",
      "Câu mẫu → kết quả thật", "Kết quả có thể", "Không khớp thì đi đâu",
      "Mã lỗi", "Ngân sách", "Trạng thái", "Ghi chú"]
hang = [
    ["0", "Không phải lệnh điều khiển xe → trợ lý chung",
     "Người ngồi trong xe hỏi gì cũng là hỏi trợ lý: thời tiết, kiến thức, chuyện chung. "
     "KHÔNG từ chối — caps giao hẳn việc này cho trợ lý.",
     "tuỳ nhánh",
     "Không alias thiết bị nào khớp, không động từ điều khiển nào khớp",
     "Chia BA nhánh:\n"
     "0a · HỎI THỜI TIẾT — nhận biết bằng từ khoá ngay trên xe, trả lời bằng số liệu "
     "Open-Meteo lấy sẵn lúc khởi động. KHÔNG gọi LLM. Hết hạn bộ nhớ đệm mà mất mạng "
     "thì nói chưa xem được.\n"
     "0b · CẦN SỐ LIỆU SỐNG MÀ HỆ KHÔNG CÓ NGUỒN (giá cả, tỉ giá, chứng khoán, tỉ số, "
     "lịch chiếu, chuyến bay, giao thông, tin tức) — trả lời \"em chưa xem được\". "
     "TUYỆT ĐỐI KHÔNG BỊA.\n"
     "0c · HỎI CHUNG, trả lời được từ kiến thức — trợ lý trả lời ngắn gọn.",
     "REPLY (0a, 0c) · REPLY \"chưa xem được\" (0b)",
     "VA_REPLY · VA_ESCALATE_ROUTED",
     "0a ~5ms (có đệm) · 0b,0c ~900ms",
     "✅ Đã có (25/09)",
     "Cả ba nhánh đã chạy trên xe, KHÔNG tốn vòng cloud nào. Đo thật:\n"
     "  \"hôm nay trời thế nào\" -> 0 vòng cloud, \"Hà Nội đang 32 độ, trời ít mây...\"\n"
     "  \"giá vàng hôm nay bao nhiêu\" -> 0 vòng cloud, \"Em chưa xem được giá vàng ạ.\"\n"
     "Trước đó cả hai đều tốn một vòng ~900ms: thời tiết tốn vòng chỉ để PHÂN LOẠI câu "
     "rồi mới quay về gọi trợ lý; giá vàng tốn vòng chỉ để nghe đúng câu đã biết trước.\n"
     "Dấu hiệu thời tiết mở rộng từ 8 lên 22 chuỗi (7/7 nhận đúng, 0/8 nhận nhầm câu lệnh "
     "xe). Chọn thận trọng, neo vào \"trời\"/\"ngoài\" — \"lạnh không\" để trống sẽ cướp "
     "mất \"trong xe lạnh không\".\n"
     "Bẫy đã gặp: model chỉ có một công cụ (thời tiết) nên từng trả lời \"giá vàng hôm nay\" "
     "bằng bản tin thời tiết. Code đã chặn bằng cách kiểm lại câu có thật sự hỏi thời tiết."],
    ["1", "Sửa ý giữa câu",
     "Người nói đổi ý giữa chừng",
     "Edge",
     "Dấu hiệu sửa nằm GIỮA câu: à quên, à nhầm, à mà",
     "Bỏ mệnh đề trước, giữ mệnh đề sau, rồi xét lại từ Case 2.",
     "Không tự sinh kết quả — chỉ viết lại đầu vào",
     "—",
     "+0ms",
     "✅ Đã có",
     "\"thôi\" ở CUỐI câu là giục, không phải sửa ý."],
    ["2", "Câu nối tiếp lượt trước",
     "Câu phụ thuộc ngữ cảnh lượt trước",
     "Edge",
     "Frame thiếu device, nhưng lượt trước để lại đúng MỘT thiết bị",
     "Kế thừa thiết bị từ ngữ cảnh. Nếu ngữ cảnh có nhiều ứng viên thì RƠI XUỐNG CASE 4, "
     "không lên cloud.",
     "Tiếp tục như Case 3",
     "—",
     "+0ms",
     "✅ Đã có",
     "Ngữ cảnh chỉ giữ trong phiên, không lưu qua lần khởi động."],
    ["7", "Hiểu được nhưng nghi mình hiểu sai",
     "Edge ghép ĐƯỢC lệnh, nhưng bỏ qua quá nhiều chữ mang nội dung nên không tin chính mình",
     "Cloud",
     "Đã có lệnh, NHƯNG số chữ bị bỏ qua ≥ ngưỡng (caps: 7 chữ)",
     "Hỏi cloud kiểm lại. Cloud ra lệnh khác → dùng lệnh cloud. Cloud im hoặc mất mạng → "
     "GIỮ NGUYÊN lệnh của edge, không vứt đi.",
     "OK (lệnh edge hoặc lệnh cloud)",
     "—",
     "≤ 1200ms",
     "✅ Đã có",
     "Trạng thái thứ tư, không nằm trong ba ô cũ: không phải tự tin (Case 3), không phải "
     "thiếu trường (Case 4), không phải không hiểu (Case 5). Đây là NGHI NGỜ.\n"
     "Ví dụ thật: \"hôm qua anh với mấy ông bạn cũ ngồi quán cà phê nói chuyện công việc mãi "
     "thôi bật điều hòa\" — ghép được lệnh bật điều hòa nhưng bỏ qua 14 chữ.\n"
     "Chính nhánh này gây ra lỗi gọi cloud hai vòng, đã vá 24/09."],
    ["ds", "Lệnh để sau, không phải bây giờ",
     "Người dùng nói một ý định HOÃN: có điều kiện, hoặc hẹn giờ",
     "Edge",
     "Câu có dấu hiệu hoãn: \"khi nào…\", \"lát nữa\", \"5 phút nữa\", \"tới nhà thì…\"",
     "Chặn tại chỗ ở chốt 3. KHÔNG dựng lệnh, KHÔNG gọi cloud. Nói rõ giới hạn VÀ mời làm "
     "ngay: \"Xe chưa hẹn giờ được, anh/chị cần thì bảo em làm ngay ạ.\"",
     "INVALID",
     "VA_NOT_SCHEDULABLE",
     "~1ms",
     "✅ Đã có",
     "Ý nghĩa KHÔNG phải để hẹn giờ — xe không có chức năng đó. Là để CHẶN KHÔNG CHO CHẠY "
     "NGAY.\n"
     "Kiểm bằng cloud giả cố tình trả lệnh mở ngay khi thấy cụm \"mở cửa sổ trời\": câu "
     "\"khi nào tới nhà thì mở cửa sổ trời\" gọi cloud 0 LẦN, không lệnh nào chạy. Không có "
     "case này thì câu rơi xuống \"không hiểu\" → lên cloud → model rất dễ trả về lệnh mở "
     "ngay. Người dùng đang chạy cao tốc mà cửa sổ trời mở ra.\n"
     "triage xếp NOT_NOW TRƯỚC SLOT có chủ ý, comment ghi: \"có nhắc thiết bị nhưng tuyệt "
     "đối không được chạy\"."],
    ["3", "Frame rõ",
     "Câu rõ, đủ thông tin, model tự tin",
     "Edge",
     "Có device + action, độ tin cậy ≥ ngưỡng cao",
     "RA LỆNH: chạy đúng thứ tự resolve (xác nhận bằng caps, clamp/snap giá trị) → safety "
     "(luật an toàn theo trạng thái xe) → runtime (gửi xuống xe).\n"
     "HỎI TRẠNG THÁI (action = query): ĐỌC trạng thái đang giữ, KHÔNG gửi gì xuống xe, và "
     "KHÔNG qua tầng an toàn — xem ngoại lệ ở luật D. Không biết thì thú nhận, không đoán.",
     "OK · CONFIRM · DENY · NOT_SUPPORT · INVALID\n"
     "Riêng câu hỏi: OK kèm câu trả lời, hoặc \"em chưa biết trạng thái…\" (không phải lỗi, "
     "là thú nhận — cùng tinh thần luật B)",
     "VA_SAFETY_DENY · VA_NEED_CONFIRM · VA_NOT_SUPPORT · VA_INVALID_ZONE · VA_EXEC_FAILED",
     "~10ms",
     "✅ Đã có (thiếu độ tin cậy)",
     "Vòng xác nhận: TTL 30 giây; khi người dùng gật thì KIỂM LẠI trạng thái xe tại thời điểm "
     "đồng ý chứ không dùng trạng thái lúc hỏi — xe có thể đã chuyển số trong lúc chờ."],
    ["6", "Lệnh thuộc hệ khác",
     "Thiết bị do một hệ khác sở hữu, không phải xe tự làm",
     "Edge quyết định, hệ khác thực thi",
     "caps khai thiết bị là cloud_only (hiện chỉ có nav)",
     "resolve chặn NGAY bước đầu, trước cả khi kiểm action/vùng/giá trị. Trả kèm target — "
     "không chỉ nói \"tôi không làm được\" mà nói rõ AI làm được. Giao cho handler đã đăng ký; "
     "không ai nhận thì trả ESCALATE_ROUTED lên tầng trên.",
     "ESCALATE_ROUTED kèm target",
     "VA_ESCALATE_ROUTED",
     "~1ms (không gọi suy luận)",
     "✅ Đã có",
     "KHÁC Case 5 ở căn bản: Case 5 là \"không hiểu, nhờ nghĩ hộ\"; Case 6 là \"hiểu rồi, "
     "nhưng việc này không phải của mình\" — đích biết trước từ caps nên KHÔNG tốn vòng suy luận.\n"
     "caps cố tình KHÔNG viết grammar cho nav (NavAgent sở hữu), nhưng vẫn khai nav trong caps "
     "để khi cloud sinh lệnh nav thì hệ biết đó là hợp lệ, không phải model bịa thiết bị.\n"
     "Cloud đòi chuyển tới đích caps KHÔNG khai thì agent bỏ qua — model không tự đặt đích mới được.\n"
     "⚠️ LƯU Ý: lệnh routed KHÔNG đi qua tầng an toàn — decide() trả về ngay khi resolve khác OK. "
     "Với nav thì không sao (caps không có luật an toàn cho nav, hệ nhận tự chịu). Nhưng nếu sau "
     "này có thiết bị cloud_only CÓ ràng buộc an toàn thì thứ tự hiện tại sẽ bỏ qua kiểm. Cần chốt."],
    ["3b", "Trạng thái đã đúng sẵn",
     "Thiết bị đang ở đúng trạng thái được yêu cầu",
     "Edge",
     "Frame hợp lệ, nhưng đọc trạng thái thấy đã đúng rồi",
     "Trả lời bằng câu trạng thái, KHÔNG gửi lệnh xuống xe.",
     "OK (chỉ trả lời)",
     "—",
     "~10ms",
     "✅ Đã có (25/09)",
     "Kiểm thật: \"bật điều hòa\" khi nó đang bật -> gửi xuống xe 0 lệnh, trả lời "
     "\"Điều hòa đang ở 22 độ ạ.\" Dùng lại hàm sinh câu trạng thái sẵn có nên không "
     "phải thêm mẫu câu nào.\n"
     "Chỉ bỏ qua khi CHẮC CHẮN: trạng thái phải đang biết, lệnh không kèm thay đổi nào "
     "khác. Không biết thì vẫn gửi — thà lệnh thừa còn hơn bỏ qua lệnh người dùng thật "
     "sự muốn.\n"
     "Bẫy đã dính: \"bật điều hòa\" mang sẵn value=22 từ comfort_default nên không thể "
     "đòi command.value is None, phải so với mức đang có."],
    ["4", "Lưỡng lự hoặc thiếu trường",
     "Model lưỡng lự, hoặc câu thiếu thông tin bắt buộc",
     "Edge",
     "Độ tin cậy nằm giữa hai ngưỡng · hoặc hai ứng viên đầu gần nhau · hoặc thiếu slot bắt buộc",
     "LOCAL TRƯỚC. Có default/nudge trong caps → tự điền VÀ NÓI RA đã điền gì, không điền ngầm. "
     "Không có → hỏi lại tại chỗ, liệt kê ứng viên LẤY TỪ CAPS chứ không bịa. Retry tối đa 1 "
     "lần và phải là local; hỏng thì sang Case 5.",
     "ASK (hỏi lại) · OK (tự điền)",
     "VA_VALUE_REQUIRED · VA_MODE_REQUIRED · VA_ITEM_REQUIRED · VA_DEVICE_REQUIRED · "
     "VA_VAGUE_REFERENCE",
     "tự điền ~5ms; hỏi lại tốn 1 lượt",
     "⚠️ Một phần",
     "THỨ TỰ ĐANG NGƯỢC: code hiện đẩy mọi mã thiếu-thông-tin lên cloud TRƯỚC khi hỏi lại. "
     "Gộp \"lưỡng lự giữa ứng viên\" vào đây là có chủ ý — edge đã biết đủ để hỏi thì hỏi rẻ "
     "hơn một vòng cloud."],
    ["5", "Cần suy luận",
     "Có nhắc tới xe nhưng không dựng được lệnh chắc chắn",
     "Cloud",
     "Có nhắc tới xe nhưng độ tin cậy dưới ngưỡng thấp / không ra frame · hoặc Case 4 đã retry hỏng",
     "Gọi cloud. Lệnh cloud trả về BẮT BUỘC chạy lại qua resolve + safety, không có đường bypass.",
     "commands · ask · reply · route",
     "VA_ESCALATE_UNKNOWN · VA_ESCALATE_ROUTED",
     "≤ 1200ms (ngân sách caps)",
     "✅ Đã có",
     "Việc bắt lệnh cloud chạy lại qua caps là chỗ chặn model bịa ra thiết bị không tồn tại. "
     "Giữ nguyên, đừng bỏ."],
]
# Câu mẫu gắn ngay cạnh case, để đọc một dòng là thấy luôn ví dụ. Sheet "6 · Câu mẫu"
# giữ bộ đầy đủ 19 câu. Tất cả đều chạy thật ngày 24/09 với tầng cloud tắt.
MAU_CASE_CU = {
    "0": ('"giá vàng hôm nay bao nhiêu" → ESCALATE_UNKNOWN, LÊN CLOUD (sai)\n'
          '"đèn đỏ phía trước kìa" → cùng kết quả — chứng minh Case 1 và Case 9 đang bị gộp'),
    "1": '"bật sưởi ghế mức 3 à quên mức 1" → "Đã chỉnh sưởi ghế mức 1 ạ."',
    "2": '(sau "mở cửa kính") "đóng lại" → "Đã đóng cửa kính ạ."',
    "3": ('"bật sưởi ghế lái mức 2" → "Đã chỉnh sưởi ghế lái mức 2 ạ."\n'
          '(40km/h) "mở cửa kính" → CONFIRM "Xe đang di chuyển, anh/chị chắc muốn mở cửa kính chứ ạ?"\n'
          '(40km/h) "gập gương" → DENY "Xe đang chạy trên 16 km/h, chưa gập gương được ạ."\n'
          '"bật hud" → NOT_SUPPORT "Xe mình không có hud ạ."'),
    "3b": ('(đã bật) "bật điều hòa" → hiện ra "Đã bật điều hòa 22 độ ạ."\n'
           'đáng ra: "Điều hòa đang bật rồi ạ."'),
    "4": ('"mở ứng dụng" → "Anh/chị muốn mở cái gì ạ?"\n'
          '"bật đèn viền" → "Đã bật đèn viền 60 phần trăm ạ." (tự điền, CÓ nói ra)'),
    "ds": ('"khi nào tới nhà thì mở cửa sổ trời" → INVALID, VA_NOT_SCHEDULABLE\n'
           '"Xe chưa hẹn giờ được, anh/chị cần thì bảo em làm ngay ạ."\n'
           'Gọi cloud 0 lần — chặn trước khi model kịp biến ý định hoãn thành lệnh ngay'),
    "5": ('"nóng quá" → lên cloud\n'
          '"cái đó tắt đi" → lên cloud (đáng ra Case 9 nên hỏi lại trước)'),
    "6": ('"dẫn đường về nhà" → ESCALATE_ROUTED, target=\'nav\'\n'
          'chuyển cho NavAgent, KHÔNG gửi xuống CAN, không tốn vòng suy luận'),
    "7": ('"hôm qua anh với mấy ông bạn cũ ngồi quán cà phê nói chuyện công việc mãi '
          'thôi bật điều hòa"\n'
          '→ ghép được lệnh nhưng bỏ qua 14 chữ (ngưỡng 7) → hỏi cloud kiểm lại'),
}
# Nhánh rơi xuống: người đọc phải thấy ĐƯỜNG ĐI, không chỉ thấy điều kiện.
RUNG = {
    "0":  "→ Case 1 (không phải câu ngoài miền thì xét tiếp)",
    "1":  "→ Case 2",
    "2":  "→ Case 3. Ngữ cảnh mơ hồ (nhiều ứng viên) thì NHẢY THẲNG xuống Case 4",
    "3":  "→ Case 4",
    "3b": "→ Case 4",
    "4":  "→ Case 5 (chỉ SAU khi đã hỏi lại 1 lần mà vẫn không đủ)",
    "5":  "hết nhánh. Cloud im/mất mạng → luật B: dùng frame edge nếu đủ tin, "
          "không thì thú nhận không hiểu",
}
SO_MOI = {"0": "1", "1": "2", "2": "3", "7": "4", "ds": "5", "3": "6",
          "6": "7", "3b": "8", "4": "9", "5": "10"}
RUNG_MOI = {
    "1": "→ Case 2",
    "2": "→ Case 3",
    "3": "→ Case 4. Ngữ cảnh mơ hồ (nhiều ứng viên) thì NHẢY THẲNG xuống Case 9",
    "4": "→ Case 5",
    "5": "→ Case 6",
    "6": "→ Case 7",
    "7": "→ Case 8",
    "8": "→ Case 9",
    "9": "→ Case 10 (chỉ SAU khi đã hỏi lại 1 lần mà vẫn không đủ)",
    "10": "hết nhánh. Cloud im/mất mạng → luật B: dùng frame edge nếu đủ tin, "
          "không thì thú nhận không hiểu",
}
MAU_CASE_MOI = {SO_MOI[k]: v for k, v in MAU_CASE_CU.items()}
for h in hang:
    h[0] = SO_MOI[h[0]]
hang.sort(key=lambda h: int(h[0]))
# Vị trí chèn phải khớp với thứ tự trong td: "Câu mẫu" đứng thứ 7 (index 6),
# "Không khớp thì đi đâu" đứng thứ 9 (index 8). Bỏ một cột ở đầu bảng mà quên sửa
# hai số này là toàn bộ cột từ đó trở đi lệch một ô — tiêu đề một đằng, nội dung
# một nẻo, mà Excel không báo gì.
for h in hang:
    h.insert(td.index("Câu mẫu → kết quả thật"), MAU_CASE_MOI[h[0]])
    h.insert(td.index("Không khớp thì đi đâu"), RUNG_MOI[h[0]])
    assert len(h) == len(td), (h[1], len(h), len(td))

cuoi = do_bang(ws, td, hang, [5, 26, 32, 11, 32, 40, 50, 22, 42, 28, 15, 18, 46], bat_dau=4)
to_mau_cot(ws, 4, 5, cuoi)
ws.freeze_panes = "C5"

# ------------------------------------------------------------------ 4. Luật cắt ngang
ws = wb.create_sheet("5 · Luật cắt ngang")
ws["A1"] = "LUẬT CẮT NGANG — áp cho nhiều case cùng lúc"
ws["A1"].font = Font(name=FONT, size=13, bold=True, color=XANH_DAM)
ws["A2"] = ("Không thể biến thành case riêng. Ví dụ an toàn áp cho cả Case 3 lẫn Case 5 — "
            "một câu không phải 'hoặc là frame rõ hoặc là an toàn', nó là cả hai.")
ws["A2"].font = Font(name=FONT, size=10, italic=True, color="666666")

td = ["Luật", "Ý nghĩa", "Áp cho case", "Chạy ở đâu", "Nội dung", "Trạng thái", "Số đo / ghi chú"]
hang = [
    ["A — Ngưỡng tin cậy",
     "Rẽ nhánh theo độ tin cậy, không phải nhị phân",
     "1, 4, 5, 7, 8, 9", "Edge",
     "Hai ngưỡng (cao/thấp) khai trong caps, hiệu chỉnh trên tập held-out, KHÔNG hardcode "
     "trong code. Ngưỡng cao quyết định Case 5; nằm giữa hai ngưỡng là Case 8; dưới ngưỡng "
     "thấp là Case 9 (hoặc Case 1 nếu không nhắc gì tới xe).",
     "❌ Chưa có",
     "CHẶN LỚN NHẤT. Đo trên model vừa train: ngưỡng 0,9 cho phủ 59% / đúng 79,6% — cứ 5 lệnh "
     "thì 1 sai, kể cả ở ngưỡng cao nhất. Không đủ để đặt ngưỡng. Nghẽn ở dữ liệu (toàn bộ tập "
     "train là tự sinh, không có câu người Việt thật nói với xe), không ở kiến trúc."],
    ["B — Cloud không với tới",
     "Mất sóng, timeout, hết quota",
     "4, 5, 8, 9", "Edge",
     "Edge có frame với độ tin cậy ≥ ngưỡng thấp → DÙNG NÓ, và nói rõ đang chạy ngoại tuyến. "
     "Không có → thú nhận không hiểu. KHÔNG ĐOÁN BỪA.",
     "✅ Đã có",
     "Xe vào hầm là gặp, không phải ngoại lệ hiếm. Mã: VA_LLM_UNAVAILABLE, VA_LLM_TIMEOUT."],
    ["C — Ngân sách thời gian",
     "Tổng một lượt không vượt ngân sách",
     "tất cả", "cả hai",
     "Tổng ≤ deadline_ms (caps đang khai 1200ms). Hỏi lại ở Case 8 tối đa 1 lần và phải là "
     "local. KHÔNG BAO GIỜ hai vòng cloud trong một lượt.",
     "⚠️ Một phần",
     "Đo thật: model ~3ms · resolve+safety ~1ms · cloud p50 903ms, p90 1275ms — p90 ĐÃ VƯỢT "
     "trần 1200ms. ĐÃ VÁ ngày 24/09: trước đó câu dài nói vòng ăn đủ HAI vòng cloud (~1800ms) "
     "vì nhánh low_coverage kích hoạt ngay sau nhánh 'không ra lệnh nào'. Giờ một lượt chỉ một "
     "vòng, có test khoá. CÒN THIẾU: chưa giới hạn số lần hỏi lại ở Case 8."],
    ["D — An toàn độc lập",
     "An toàn không phụ thuộc đường đi",
     "5, 6, 9", "Edge",
     "Hàm kiểm an toàn nhận (caps, lệnh, trạng thái xe) và KHÔNG BIẾT lệnh đến từ đâu. Lệnh "
     "nguy hiểm hoặc bị chặn theo trạng thái xe không bao giờ phụ thuộc cloud. Không đường "
     "nào bypass, kể cả lệnh do cloud sinh ra.",
     "✅ Đã có",
     "Đã kiểm trực tiếp trong code: safety.evaluate là hàm thuần, và lệnh cloud trả về đều "
     "chạy qua decide() như lệnh thường.\n"
     "HAI NGOẠI LỆ, cả hai đều CÓ CHỦ ĐÍCH:\n"
     "(1) Lệnh Case 7 (thiết bị cloud_only) không qua tầng an toàn vì decide() trả về ngay khi "
     "resolve khác OK. Với nav thì không sao — hệ này không thực thi lệnh đó. Nhưng nếu sau "
     "này có thiết bị cloud_only CÓ ràng buộc an toàn thì phải đổi thứ tự. CẦN CHỐT.\n"
     "(2) CÂU HỎI TRẠNG THÁI (action = query) đi thẳng, trừ khi caps có rule ghi đích danh "
     "action: query. Lý do trong code: \"nếu không thì 'nắp sạc mở chưa?' sẽ bị DENY lúc xe "
     "chạy\". Kiểm thật ở 40 km/h: \"mở nắp sạc\" ra DENY, còn \"nắp sạc mở chưa\" ra OK. "
     "Bỏ ngoại lệ này là hỏi một câu vô hại cũng bị chặn."],
    ["E — Lệnh ghép",
     "Câu chứa nhiều mệnh đề lệnh",
     "tất cả", "cả hai",
     "Mỗi mệnh đề đi qua bảng ĐỘC LẬP. Một vế hỏng KHÔNG kéo theo vế kia. Câu trả lời nói rõ "
     "vế nào chạy được, vế nào không.",
     "⚠️ Một phần",
     "Grammar tách được mệnh đề và có xử lý mệnh đề dở dang.\n"
     "Vá 25/09: hai lệnh CÙNG NHÓM MODE đè nhau thì chỉ nói lệnh cuối. Trước đó \"lấy gió "
     "trong rồi lấy gió ngoài\" nói cả hai câu trong khi xe chỉ ở lấy gió ngoài — nói làm "
     "hai việc, thực tế một. Khác nhóm thì vẫn giữ cả hai (\"lấy gió trong và thổi mặt\").\n"
     "CÒN THIẾU: model gán nhãn cả câu nên mỗi câu chỉ ra một frame. Model joint-nlu nhận "
     "được ngày 28/09 gán nhãn theo TOKEN nên xử được, eval của họ có tới 4 lệnh một câu."],
]
cuoi = do_bang(ws, td, hang, [24, 34, 16, 12, 56, 15, 62], bat_dau=4)
to_mau_cot(ws, 4, 5, cuoi)
ws.freeze_panes = "A5"

# ------------------------------------------------------------------ 5. Câu mẫu
ws = wb.create_sheet("6 · Câu mẫu")
ws["A1"] = "CÂU MẪU — chạy thật qua hệ thống ngày 24/09/2026"
ws["A1"].font = Font(name=FONT, size=13, bold=True, color=XANH_DAM)
ws["A2"] = ("Mọi câu trả lời dưới đây được CHÉP LẠI từ lần chạy thật, không viết tay. "
            "Chạy với tầng cloud TẮT để thấy rõ edge làm được gì một mình.")
ws["A2"].font = Font(name=FONT, size=10, italic=True, color="666666")

td = ["Case", "Ngữ cảnh", "Câu nói", "Chạy ở đâu", "Kết quả", "Mã", "Câu trả lời thật", "Nhận xét"]
hang = [
    ["Case 1", "—", "đèn đỏ phía trước kìa", "Cloud", "ESCALATE_UNKNOWN",
     "VA_ESCALATE_UNKNOWN", "(im lặng khi tắt cloud)",
     "Có chữ \"đèn\" nhưng là bình luận, không phải lệnh — grammar đúng khi không ghép "
     "thành lệnh bật đèn. Nhánh 0c, trợ lý trả lời. Lưu ý: hiện KHÔNG phân biệt được câu "
     "này với Case 9 (\"nóng quá\") vì cả hai cùng ra ESCALATE_UNKNOWN."],
    ["Case 2", "—", "bật sưởi ghế mức 3 à quên mức 1", "Edge", "OK", "—",
     "Đã chỉnh sưởi ghế mức 1 ạ.",
     "Lấy đúng mệnh đề sau. Grammar xử lý được, không cần model."],
    ["Case 3", "lượt trước: mở cửa kính", "đóng lại", "Edge", "OK", "—",
     "Đã đóng cửa kính ạ.",
     "Kế thừa thiết bị từ lượt trước."],
    ["Case 5", "—", "bật sưởi ghế lái mức 2", "Edge", "OK", "—",
     "Đã chỉnh sưởi ghế lái mức 2 ạ.",
     "Đường chuẩn: hiểu → caps → an toàn → gửi xe. ~10ms."],
    ["Case 5", "xe đang chạy 40 km/h", "mở cửa kính", "Edge", "CONFIRM", "VA_NEED_CONFIRM",
     "Xe đang di chuyển, anh/chị chắc muốn mở cửa kính chứ ạ?",
     "Luật an toàn trong caps yêu cầu xác nhận khi xe không ở số P."],
    ["Case 5", "xe đang chạy 40 km/h, đã hỏi xác nhận", "ừ", "Edge", "OK", "—",
     "Đã mở cửa kính ạ.",
     "Khi gật thì kiểm LẠI trạng thái xe tại thời điểm đồng ý."],
    ["Case 5", "xe đang chạy 40 km/h", "gập gương", "Edge", "DENY", "VA_SAFETY_DENY",
     "Xe đang chạy trên 16 km/h, chưa gập gương được ạ.",
     "Chặn thẳng, không hỏi. An toàn quyết định, không phụ thuộc cloud."],
    ["Case 5", "xe đang chạy 40 km/h", "mở cốp", "Edge", "DENY", "VA_SAFETY_DENY",
     "Xe đang di chuyển, chưa mở cốp được ạ.",
     "Cùng luật D — an toàn chạy ngay trên xe."],
    ["Case 5", "—", "bật hud", "Edge", "NOT_SUPPORT", "VA_NOT_SUPPORT",
     "Xe mình không có hud ạ.",
     "caps khai xe không có thiết bị này. Từ chối tại chỗ, không hỏi cloud."],
    ["Case 5", "đã bật điều hòa", "điều hòa mấy độ rồi", "Edge", "OK", "—",
     "Điều hòa đang ở 22 độ ạ.",
     "Câu hỏi trạng thái, không bị an toàn chặn."],
    ["Case 8", "—", "mở ứng dụng", "Edge", "INVALID", "VA_ITEM_REQUIRED",
     "Anh/chị muốn mở cái gì ạ?",
     "Hỏi lại tại chỗ, đúng như bảng mô tả. Ứng viên lấy từ caps."],
    ["Case 8", "—", "bật đèn viền", "Edge", "OK", "—",
     "Đã bật đèn viền 60 phần trăm ạ.",
     "Có mức mặc định trong caps nên tự điền VÀ nói ra con số."],
    ["Case 9", "—", "nóng quá", "Cloud", "ESCALATE_UNKNOWN", "VA_ESCALATE_UNKNOWN",
     "(im lặng khi tắt cloud)",
     "Đúng chỗ phải lên cloud: có ngụ ý về xe nhưng không dựng được lệnh."],
    ["Case 9", "—", "cái đó tắt đi", "Cloud", "ESCALATE_UNKNOWN", "VA_ESCALATE_UNKNOWN",
     "(im lặng khi tắt cloud)",
     "Mơ hồ, không có ngữ cảnh. Đáng ra Case 4 nên hỏi lại trước khi lên cloud."],
    ["G2", "xe đang chạy 40 km/h · lượt trước \"mở cửa kính\" ra CONFIRM, đang chờ xác nhận", "thôi", "Edge", "CANCELLED", "—",
     "Vâng, em không làm nữa ạ.",
     "Huỷ lệnh đang chờ. Hoạt động đúng."],
    ["Case 6", "cloud sinh lệnh nav", "dẫn đường về nhà", "Edge quyết định",
     "ESCALATE_ROUTED", "VA_ESCALATE_ROUTED", "(chuyển cho NavAgent, target='nav')",
     "caps khai nav là cloud_only nên resolve chặn ngay bước đầu và trả kèm target. "
     "KHÔNG gửi xuống CAN, không tốn vòng suy luận."],
    ["Case 4", "—",
     "hôm qua anh với mấy ông bạn cũ ngồi quán cà phê nói chuyện công việc mãi thôi bật điều hòa",
     "Cloud", "OK", "—", "Đã bật điều hòa 22 độ ạ.",
     "Ghép được lệnh nhưng bỏ qua 14 chữ (ngưỡng 7) nên hỏi cloud kiểm lại. Dừng ở chốt 7."],
    ["Case 1", "có mạng", "thời tiết hôm nay thế nào", "Edge", "REPLY", "—",
     "Hà Nội đang 32 độ, trời ít mây, độ ẩm 70% ạ.",
     "Nhánh 0a — khớp từ khoá ngay trên xe, trả lời bằng số liệu Open-Meteo. KHÔNG gọi LLM."],
    ["Case 1", "mất mạng, bộ đệm rỗng", "thời tiết hôm nay thế nào", "Edge", "REPLY", "—",
     "Em chưa lấy được thông tin thời tiết lúc này ạ.",
     "Thú nhận, không bịa. Đúng luật B."],
    ["Case 1", "—", "hôm nay trời thế nào", "Cloud", "ESCALATE_UNKNOWN", "VA_ESCALATE_UNKNOWN",
     "(im lặng khi tắt cloud)",
     "LỖ HỔNG TỪ KHOÁ: danh sách dấu hiệu thời tiết chỉ có 8 chuỗi (thời tiết, dự báo, "
     "trời nắng, trời mưa không, nóng bao nhiêu độ, ngoài trời...). Câu này trượt nên rơi "
     "xuống 0c, gọi LLM mà LLM không có số liệu thật. Sửa bằng cách bổ sung dấu hiệu — rẻ."],
    ["Case 3", "lượt trước: bật điều hòa", "cái đó tắt đi à quên bật lên", "Edge", "OK", "—",
     "Điều hòa đang ở 22 độ ạ.",
     "KHÓ: vừa sửa ý vừa nối tiếp. Lấy thiết bị từ lượt trước (Case 3) VÀ lấy mệnh đề sau "
     "chỗ sửa ý (Case 2). Rồi rơi tiếp vào Case 8 vì điều hoà ĐANG bật sẵn — ba case nối "
     "nhau trong một câu, đúng ca cho thấy thứ tự xét quyết định kết quả."],
    ["Case 5", "—", "điều hòa 40 độ", "Edge", "OK", "—", "Đã chỉnh điều hòa 32 độ ạ.",
     "KHÓ: vượt dải cho phép (16-32). Kẹp xuống 32 và NÓI RA con số cuối — người dùng "
     "biết mình không được đúng cái đã xin. notes ghi \"clamp 40 -> 32 (range 16..32)\"."],
    ["Case 5", "—", "hạ kính xuống 50", "Edge", "OK", "—", "Đã chỉnh cửa kính 60 phần trăm ạ.",
     "KHÓ: cửa kính chỉnh theo bước 20% nên 50 không hợp lệ. Làm tròn lên 60 và nói ra. "
     "notes ghi \"snap 50 -> 60 (resolution=20)\". CHƯA CÓ: không giải thích VÌ SAO lệch."],
    ["Luật E", "xe đang chạy 40 km/h", "mở cốp và bật điều hòa", "Edge", "DENY",
     "VA_SAFETY_DENY", "Xe đang di chuyển, chưa mở cốp được ạ. Đã bật điều hòa 22 độ ạ.",
     "KHÓ: một vế bị an toàn chặn, vế kia vẫn chạy. Đúng luật E — một vế hỏng không kéo "
     "theo vế kia, và câu trả lời nói rõ vế nào được vế nào không."],
    ["Case 5", "—", "ha kinh xuong mot nua roi bat suoi ghe lai", "Edge", "OK", "—",
     "Đã giảm cửa kính 50 phần trăm ạ. Đã bật sưởi ghế lái mức 2 ạ.",
     "KHÓ: ASR mất dấu HOÀN TOÀN, cộng hai lệnh, cộng số viết bằng chữ (\"một nửa\"). "
     "Grammar xử được cả ba cùng lúc, không cần model."],
    ["Case 5", "—", "sưởi ghế sau bên phải mức hai", "Edge", "OK", "—",
     "Đã chỉnh sưởi ghế sau phải mức 2 ạ.",
     "KHÓ: vùng ba chữ (\"sau bên phải\") + số viết bằng chữ (\"hai\" -> 2)."],
    ["Case 5", "—", "thổi mặt và chân", "Edge", "OK", "—",
     "Đã chuyển quạt gió sang thổi mặt và chân ạ.",
     "KHÓ: chữ \"và\" thường là dấu tách hai lệnh, nhưng ở đây nằm TRONG tên chế độ. "
     "Luật M4: chỉ tách ở từ nối nằm NGOÀI mọi alias đã khớp."],
    ["Case 5", "đã bật điều hòa", "điều hòa mấy độ rồi bật lên 25 đi", "Edge", "OK", "—",
     "Điều hòa đang ở 25 độ ạ. Đã chỉnh điều hòa 25 độ ạ.",
     "KHÓ: một câu vừa HỎI vừa RA LỆNH. ⚠️ Câu trả lời cho phần hỏi báo 25 — là mức MỚI "
     "chứ không phải mức đang có lúc hỏi (22). Người dùng hỏi \"mấy độ rồi\" mà nghe số "
     "sau khi đã đổi. Đáng xem lại thứ tự."],
    ["Case 8", "âm lượng 20 rồi tắt tiếng", "bật tiếng lại", "Edge", "OK", "—",
     "Đã chỉnh âm lượng mức 20 ạ.",
     "KHÓ: khôi phục mức trước khi tắt. Agent nhớ mức khác 0, nên tắt tiếng rồi bật lại thì "
     "về đúng 20. Nếu chưa từng đặt mức nào thì trả VA_NO_PREVIOUS_VALUE và hỏi lại."],
    ["Case 9", "—", "cái kia to lên", "Cloud", "ESCALATE_UNKNOWN", "VA_ESCALATE_UNKNOWN",
     "(im lặng khi tắt cloud)",
     "KHÓ: tham chiếu mơ hồ, không có ngữ cảnh. Grammar KHÔNG đoán bừa — đúng nếp "
     "\"thiếu thông tin thì trả ít lệnh hơn\"."],
    ["Luật C", "—", "khi nào tới nhà thì mở cửa sổ trời", "Edge", "INVALID",
     "VA_NOT_SCHEDULABLE", "Xe chưa hẹn giờ được, anh/chị cần thì bảo em làm ngay ạ.",
     "KHÓ: câu có ĐIỀU KIỆN. Hiểu được nhưng xe không có chức năng hẹn giờ — từ chối tại "
     "chỗ, không tốn vòng cloud. Luật M-triage: NOT_NOW xét trước SLOT."],
    ["Case 8", "đã bật điều hòa", "bật điều hòa", "Edge", "OK", "—",
     "Điều hòa đang ở 22 độ ạ.",
     "VÁ 25/09. Trước đó gửi lại lệnh và báo \"Đã bật điều hòa 22 độ ạ\" như mới. Giờ gửi "
     "xuống xe 0 lệnh."],
    ["Luật E", "—", "lấy gió trong rồi lấy gió ngoài", "Edge", "OK", "—",
     "Đã chuyển quạt gió sang lấy gió ngoài ạ.",
     "VÁ 25/09. Trước đó nói CẢ HAI câu trong khi xe chỉ ở lấy gió ngoài — nói làm hai "
     "việc, thực tế một. Catalog đã biết hai chế độ loại trừ nhau qua mode_group."],
    ["Luật E", "—", "lấy gió trong và thổi mặt", "Edge", "OK", "—",
     "Đã chuyển quạt gió sang lấy gió trong ạ. Đã chuyển quạt gió sang thổi mặt ạ.",
     "KHÁC nhóm thì giữ cả hai — cùng là quạt gió nhưng lấy gió và hướng thổi là hai nhóm "
     "độc lập."],
    ["Case 1", "—", "giá vàng hôm nay bao nhiêu", "Edge", "REPLY", "VA_REPLY",
     "Em chưa xem được giá vàng ạ.",
     "VÁ 25/09: 0 vòng cloud. Trước đó tốn ~900ms chỉ để nghe đúng câu này."],
    ["Luật D", "xe đang chạy 40 km/h", "mở nắp sạc", "Edge", "DENY", "VA_SAFETY_DENY",
     "Xe đang di chuyển, chưa mở nắp sạc được ạ.",
     "RA LỆNH trên thiết bị bị caps chặn khi speed > 0."],
    ["Luật D", "xe đang chạy 40 km/h", "nắp sạc mở chưa", "Edge", "OK", "—",
     "Em chưa biết trạng thái nắp sạc ạ.",
     "CÙNG thiết bị, CÙNG luật an toàn, nhưng là câu HỎI nên đi thẳng — ngoại lệ (2) của "
     "luật D. Không có ngoại lệ này thì hỏi một câu vô hại cũng bị DENY."],
    ["Luật E", "—", "bật điều hòa và mở cửa kính", "Edge", "OK", "—",
     "Đã bật điều hòa 22 độ ạ. Đã mở cửa kính ạ.",
     "Hai mệnh đề, hai lệnh độc lập."],
    ["Luật C", "—", "5 phút nữa bật điều hòa", "Edge", "INVALID", "VA_NOT_SCHEDULABLE",
     "Xe chưa hẹn giờ được, anh/chị cần thì bảo em làm ngay ạ.",
     "Từ chối tại chỗ thay vì lên cloud — xe không có chức năng hẹn giờ."],
]
cuoi = do_bang(ws, td, hang, [9, 30, 32, 14, 20, 24, 46, 54], bat_dau=4)
to_mau_cot(ws, 4, 5, cuoi)
ws.freeze_panes = "D5"

# ------------------------------------------------------------------ 5b. Luồng
ws = wb.create_sheet("2 · Luồng", 1)
ws["A1"] = "LUỒNG — một câu nói đi qua hệ thống theo đường nào"
ws["A1"].font = Font(name=FONT, size=13, bold=True, color=XANH_DAM)
ws["A2"] = ("Đọc từ trên xuống. Gặp ĐÚNG ở bước nào thì làm cột 'Nếu ĐÚNG' rồi DỪNG, "
            "không xét tiếp. Gặp SAI thì đi tiếp bước dưới.")
ws["A2"].font = Font(name=FONT, size=10, italic=True, color="666666")

td = ["Bước", "Thuộc", "Chạy ở đâu", "Câu hỏi hệ thống tự đặt", "Nếu ĐÚNG", "Nếu SAI"]
hang = [
    ["1", "Cổng G1", "Edge", "Biết câu phát ra từ ghế nào không?",
     "Gán vùng mặc định theo ghế đó, rồi xuống bước 2",
     "Coi như từ ghế lái (hiện tại luôn rơi vào nhánh này), xuống bước 2"],
    ["2", "Cổng G2", "Edge", "Câu này là huỷ / ngắt lời?",
     "Bỏ lệnh đang chờ hoặc đang chạy. DỪNG.",
     "Xuống bước 3"],
    ["3", "Cổng G3", "Edge", "Người dùng có tắt chia sẻ dữ liệu không?",
     "Khoá Case 5 — từ đây trở đi không được gọi cloud. Xuống bước 4",
     "Xuống bước 4"],
    ["4", "Case 1", "tuỳ nhánh",
     "Câu có nhắc gì thuộc về xe không? (thiết bị / động từ điều khiển)",
     "KHÔNG nhắc gì → chuyển trợ lý chung, KHÔNG phải từ chối:\n"
     "  hỏi thời tiết → trả lời bằng số liệu đã lấy sẵn, không gọi LLM (Edge)\n"
     "  cần số liệu sống mà không có nguồn → \"em chưa xem được\", không bịa\n"
     "  hỏi chung → trợ lý trả lời từ kiến thức (Cloud)\nDỪNG.",
     "Có nhắc → xuống bước 5"],
    ["5", "Case 2", "Edge", "Có dấu hiệu sửa ý giữa câu? (à quên, à nhầm)",
     "Bỏ mệnh đề trước, giữ mệnh đề sau, quay lại bước 6 với câu mới",
     "Xuống bước 6"],
    ["6", "Case 3", "Edge", "Câu thiếu thiết bị nhưng lượt trước có đúng một thiết bị?",
     "Kế thừa thiết bị đó, xuống bước 7",
     "Nhiều ứng viên → NHẢY THẲNG bước 9. Không có ngữ cảnh → xuống bước 7"],
    ["7", "Case 4", "Cloud",
     "Đã dựng được lệnh, nhưng có bỏ qua ≥ 7 chữ mang nội dung không?",
     "CÓ → không tin chính mình, hỏi cloud kiểm lại. Cloud ra lệnh khác thì dùng lệnh cloud; "
     "cloud im hoặc mất mạng thì GIỮ NGUYÊN lệnh đã hiểu. Rồi xuống bước 8.",
     "Xuống bước 8"],
    ["8", "Case 5", "Edge", "Câu có dấu hiệu HOÃN không? (khi nào…, lát nữa, 5 phút nữa)",
     "CÓ → chặn tại chỗ, không dựng lệnh, KHÔNG gọi cloud. Nói giới hạn và mời làm ngay. DỪNG.",
     "Xuống bước 9"],
    ["9", "Case 6", "Edge", "Độ tin cậy có ≥ ngưỡng cao không?",
     "Xuống bước 10",
     "Xuống bước 11"],
    ["10", "Case 7", "Edge quyết định",
     "caps có khai thiết bị này là cloud_only không? (hiện chỉ nav)",
     "CÓ → chuyển thẳng cho hệ sở hữu kèm target. KHÔNG gọi suy luận, và KHÔNG qua tầng "
     "an toàn (xem lưu ý dưới bảng). DỪNG.",
     "Xuống bước 10"],
    ["11", "Case 8", "Edge",
     "Chạy resolve (caps) → safety (trạng thái xe). Thiết bị đã ở đúng trạng thái chưa?",
     "ĐÃ ĐÚNG → chỉ trả lời, không gửi lệnh. DỪNG.\n"
     "CHƯA → gửi xuống xe. Ra OK / CONFIRM / DENY / NOT_SUPPORT. DỪNG.",
     "(bước này luôn chạy, không có nhánh sai)"],
    ["12", "Case 9", "Edge",
     "Thiếu trường bắt buộc, hoặc lưỡng lự giữa vài ứng viên. Caps có giá trị mặc định không?",
     "CÓ → tự điền VÀ nói ra đã điền gì, quay lại bước 11\n"
     "KHÔNG → hỏi lại tại chỗ, liệt kê ứng viên từ caps. DỪNG, chờ người trả lời.",
     "Đã hỏi lại 1 lần mà vẫn không đủ → xuống bước 13"],
    ["13", "Case 10", "Cloud", "Cổng G3 có khoá cloud không?",
     "KHÔNG khoá → gọi cloud (1 vòng duy nhất, ~900ms)",
     "CÓ khoá → thú nhận không hiểu. DỪNG."],
    ["14", "Case 10", "Edge", "Cloud trả về lệnh?",
     "Lệnh đó quay lại bước 11 — BẮT BUỘC qua resolve + safety, không có đường tắt",
     "Cloud trả lời bằng lời / hỏi lại / chuyển tiếp → đọc ra. DỪNG."],
    ["15", "Luật B", "Edge", "Cloud im, timeout, hoặc mất mạng?",
     "Edge có frame đủ tin → dùng nó, nói rõ đang chạy ngoại tuyến",
     "Không có → thú nhận không hiểu. KHÔNG đoán bừa. DỪNG."],
]
cuoi = do_bang(ws, td, hang, [7, 14, 11, 56, 58, 52], bat_dau=4)
to_mau_cot(ws, 4, 5, cuoi)
ws.freeze_panes = "A5"

r_ghi = cuoi + 2
ws.cell(row=r_ghi, column=1, value="Ba điều luồng này ràng buộc, đọc bảng phẳng không thấy:")
ws.cell(row=r_ghi, column=1).font = Font(name=FONT, size=10, bold=True)
for i, t in enumerate([
    "• Bước 11 là NÚT CỔ CHAI: mọi lệnh đều phải qua đây, kể cả lệnh do cloud sinh ra "
    "(bước 14 vòng ngược lại bước 11). NGOẠI LỆ là bước 10 — lệnh chuyển cho hệ khác không qua tầng an toàn, vì hệ này không thực thi chúng.",
    "• Bước 13 chỉ chạy MỘT LẦN mỗi lượt. Trước 24/09 có đường đi vòng khiến câu dài "
    "ăn hai vòng cloud ~1800ms, vượt trần 1200ms của caps. Đã vá, có test khoá.",
    "• Bước 4 KHÔNG phải cổng từ chối. Caps ghi rõ \"người ta ngồi trong xe hỏi gì cũng là "
    "hỏi trợ lý\" — câu ngoài miền được chuyển sang trợ lý chung, đó là tính năng có chủ đích. "
    "Chỉ nhánh 0b (cần số liệu sống mà hệ không có nguồn) là đáng chặn tại chỗ, và nó chỉ "
    "chiếm ~4% câu ngoài miền.",
], 1):
    o = ws.cell(row=r_ghi + i, column=1, value=t)
    o.font = Font(name=FONT, size=10)
    o.alignment = Alignment(vertical="top", wrap_text=True)
    ws.merge_cells(start_row=r_ghi + i, start_column=1, end_row=r_ghi + i, end_column=6)
    ws.row_dimensions[r_ghi + i].height = 30


# ------------------------------------------------------------------ 6. Quyết định mở
ws = wb.create_sheet("7 · Quyết định mở")
ws["A1"] = "QUYẾT ĐỊNH ĐANG MỞ — cần người quyết"
ws["A1"].font = Font(name=FONT, size=13, bold=True, color=XANH_DAM)
ws["A2"] = "Những chỗ không tự quyết được vì là lựa chọn sản phẩm, không phải kỹ thuật."
ws["A2"].font = Font(name=FONT, size=10, italic=True, color="666666")

td = ["#", "Vấn đề", "Hiện trạng", "Lựa chọn A", "Lựa chọn B", "Nghiêng về", "Ảnh hưởng"]
hang = [
    ["1", "Giá trị xin không nằm trên lưới hợp lệ (value_constraint_violation)",
     "ĐÃ LÀM ĐÚNG phương án A: \"hạ kính xuống 50\" ra \"Đã chỉnh cửa kính 60 phần trăm ạ\" "
     "— sửa VÀ nói ra con số cuối. Kiểm trực tiếp: notes ghi \"snap 50 -> 60 "
     "(resolution=20)\". (Bản trước của tài liệu này ghi nhầm là sửa im lặng.)",
     "Giữ nguyên: sửa và nói ra con số cuối",
     "Nói thêm LÝ DO lệch: \"Cửa kính chỉnh theo bước 20% nên em để 60 ạ\"",
     "A cho lệnh thường, B cho lệch nhiều",
     "Phần CÒN THIẾU là giải thích vì sao lệch. Xin 50 mà nghe 60 thì biết số cuối nhưng "
     "không hiểu tại sao. Lệch một bước thì thôi; lệch nhiều (xin 40 độ được 32) thì nên nói."],
    ["2", "G3 — quyền chia sẻ dữ liệu",
     "Chưa có. Mọi câu không hiểu đều lên cloud.",
     "Mặc định BẬT chia sẻ, cho người dùng tắt",
     "Mặc định TẮT, hỏi khi cần",
     "cần anh quyết",
     "Tắt chia sẻ thì Case 5 bị khoá, tỷ lệ câu xử lý được tụt đáng kể. Cần biết chính sách "
     "công ty trước khi thiết kế."],
    ["3", "Bật thiết bị khi đang bật (Case 7)",
     "Gửi lại lệnh, báo như mới.",
     "Trả lời \"đang bật rồi ạ\", không gửi lệnh",
     "Giữ nguyên, gửi lại cho chắc",
     "A",
     "Rẻ, cải thiện trải nghiệm ngay. Nhưng nếu xe thật cần lệnh lặp để đồng bộ thì phải "
     "giữ B — cần đội phần cứng xác nhận."],
    ["4", "G1 — vị trí người nói",
     "Chưa có đầu vào nào. Mọi câu coi như từ ghế lái.",
     "Tách mic theo ghế, gán vùng tự động",
     "Bỏ qua, luôn hỏi lại khi mơ hồ",
     "A nếu phần cứng cho phép",
     "\"mở cửa sổ\" từ ghế sau khác hẳn từ ghế lái. Cần đội phần cứng xác nhận head unit có "
     "tách được nguồn âm không."],
    ["5", "Hỗ trợ tiếng Anh",
     "Grammar chỉ làm tiếng Việt. Câu tiếng Anh trượt gần 100%.",
     "Chỉ tiếng Việt",
     "Cả hai ngôn ngữ",
     "cần anh quyết",
     "Bộ câu thử nghiệm đang lẫn 35% câu tiếng Anh. Nếu sản phẩm chỉ phục vụ tiếng Việt thì "
     "phải tách bộ câu ra, nếu không mọi số đo đều sai lệch."],
]
cuoi = do_bang(ws, td, hang, [5, 34, 42, 34, 40, 18, 56], bat_dau=4)
ws.freeze_panes = "A5"

# ------------------------------------------------------------------ 7. Số đo
ws = wb.create_sheet("8 · Số đo")
ws["A1"] = "SỐ ĐO — căn cứ cho các quyết định trong đặc tả"
ws["A1"].font = Font(name=FONT, size=13, bold=True, color=XANH_DAM)
ws["A2"] = "Đo trên hệ thống thật, ngày 23-24/09/2026. Không có con số nào là ước lượng."
ws["A2"].font = Font(name=FONT, size=10, italic=True, color="666666")

td = ["Nhóm", "Chỉ số", "Giá trị", "Đo trên", "Ý nghĩa cho đặc tả"]
hang = [
    ["Độ trễ", "Tầng hiểu chạy trên xe (grammar)", "0,56 ms (p50)", "500 câu", "Rẻ đến mức không cần cân nhắc."],
    ["Độ trễ", "Model 4 lớp (nếu có)", "2,8 ms (p50)", "CPU 4 luồng", "Vẫn nằm gọn trong ngân sách 1200ms."],
    ["Độ trễ", "Một vòng cloud", "903 ms (p50)", "78 lượt gọi thật", "Đắt gấp ~300 lần edge."],
    ["Độ trễ", "Một vòng cloud", "1275 ms (p90)", "78 lượt gọi thật", "ĐÃ VƯỢT trần 1200ms — không còn chỗ cho vòng thứ hai."],
    ["Phân bố", "Câu edge xử lý được", "75,9%", "323 câu tiếng Việt", "Ba phần tư không cần mạng."],
    ["Phân bố", "Câu edge trượt", "24,1%", "323 câu tiếng Việt", "Phần phải lên cloud hiện nay."],
    ["Phân bố", "Trong số trượt: không phải lệnh điều khiển xe", "32% (25/78)", "323 câu tiếng Việt", "KHÔNG phải lãng phí — caps giao hẳn nhóm này cho trợ lý chung trả lời."],
    ["Phân bố", "Câu ngoài miền: hỏi kiến thức chung", "91-100%", "25 câu stress + 96 câu golden_negative", "Thật sự cần cloud. Không chặn tại chỗ được."],
    ["Phân bố", "Câu ngoài miền: hỏi thời tiết", "~5%", "96 câu golden_negative", "CÓ nguồn dữ liệu (Open-Meteo) — trả lời ngay trên xe, không gọi LLM."],
    ["Phân bố", "Câu ngoài miền: số liệu sống KHÔNG có nguồn", "~4%", "96 câu golden_negative", "Câu trả lời cố định là \"chưa xem được\" — chặn bằng từ khoá trên xe được, tiết kiệm ~900ms."],
    ["Phân bố", "Trong số trượt: có nhắc thiết bị, ghép không nổi", "31% (24/78)", "323 câu tiếng Việt", "Phần model có thể giành lại."],
    ["Độ chính xác", "Grammar — frame đúng", "94,6%", "166 câu golden", "CẢNH BÁO: golden là bộ câu dùng để PHÁT TRIỂN grammar, đây là sân nhà của nó."],
    ["Độ chính xác", "Grammar — từ chối đúng", "100%", "109 câu phải im", "Grammar trượt thì im, không đoán bừa."],
    ["Độ chính xác", "Model 13M — frame đúng", "52,4%", "166 câu golden", "Còn xa grammar."],
    ["Độ chính xác", "Model 13M — từ chối đúng", "88,1%", "109 câu phải im", "Tốt lên rõ sau khi thêm mẫu âm."],
    ["Độ tin cậy", "Ngưỡng 0,9 — phủ", "59%", "275 câu golden", "CĂN CỨ CHO LUẬT A."],
    ["Độ tin cậy", "Ngưỡng 0,9 — đúng", "79,6%", "275 câu golden", "Cứ 5 lệnh thì 1 sai, kể cả ở ngưỡng cao nhất. CHƯA ĐỦ để đặt ngưỡng."],
    ["Lỗi đã vá", "Số vòng cloud một lượt — TRƯỚC", "2 vòng (~1800ms)", "câu dài nói vòng", "Vượt trần 1200ms của caps 50%, tốn gấp đôi tiền API. Tìm ra khi đối chiếu code với luật C."],
    ["Lỗi đã vá", "Số vòng cloud một lượt — SAU", "1 vòng (~900ms)", "cùng bộ câu", "Vá ngày 24/09, có test khoá. Đặc tả trả công ngay lần đối chiếu đầu tiên."],
    ["Vá 25/09", "Hỏi thời tiết — TRƯỚC", "1 vòng cloud ~900ms", "\"hôm nay trời thế nào\"", "Tốn vòng chỉ để PHÂN LOẠI câu, rồi mới quay về gọi trợ lý."],
    ["Vá 25/09", "Hỏi thời tiết — SAU", "0 vòng, ~5ms", "cùng câu", "Khớp từ khoá trên xe rồi gọi thẳng trợ lý. Số liệu Open-Meteo đã prefetch."],
    ["Vá 25/09", "Hỏi số liệu không có nguồn — SAU", "0 vòng", "\"giá vàng hôm nay\"", "Câu trả lời cố định là \"chưa xem được\", biết trước nên nói luôn."],
    ["Vá 25/09", "Dấu hiệu thời tiết", "8 -> 22 chuỗi", "7 câu nhận / 8 câu bẫy", "7/7 nhận đúng, 0/8 nhận nhầm câu lệnh xe."],
    ["Model ngoài", "joint-nlu-trained — trên 166 câu golden", "device 84,9% · device+action 71,7%", "bộ chuẩn AgentCar", "Nhận ngày 28/09. Kiến trúc gán nhãn BIO theo token, 14,5M, 3,5ms/câu CPU. Phủ trọn 30/30 thiết bị caps."],
    ["Model ngoài", "joint-nlu-trained — trên câu grammar TRƯỢT", "khớp thiết bị ~36%", "11 câu có đáp án", "MẪU QUÁ NHỎ. Nhưng đây là chỗ cần model nhất, và nó ra lệnh xe 91% số lần thay vì chịu im."],
]
cuoi = do_bang(ws, td, hang, [16, 44, 18, 24, 72], bat_dau=4)
ws.freeze_panes = "A5"

# ------------------------------------------------------------------ 8. Tổng hợp (có công thức)
ws = wb.create_sheet("9 · Tổng hợp")
ws["A1"] = "TỔNG HỢP TRẠNG THÁI"
ws["A1"].font = Font(name=FONT, size=13, bold=True, color=XANH_DAM)
ws["A2"] = "Đếm tự động từ cột Trạng thái của các sheet. Sửa ở sheet gốc thì ô đây tự đổi."
ws["A2"].font = Font(name=FONT, size=10, italic=True, color="666666")

td = ["Nhóm", "✅ Đã có", "⚠️ Một phần", "❌ Chưa có", "Tổng"]
ws.cell(row=4, column=1, value=td[0])
for i, t in enumerate(td, 1):
    ws.cell(row=4, column=i, value=t)
kieu_tieu_de(ws, 4, len(td))

# Cổng vào: cột F (6), hàng 5-7 | Các case: cột J (10), hàng 5-11 | Luật: cột F (6), hàng 5-9
nhom = [
    ("Cổng vào", "'3 · Cổng vào'!$F$5:$F$7"),
    # Cột K, không phải J: sheet Các case có thêm cột "Câu mẫu" nên Trạng thái
    # dịch sang phải một cột. Trỏ nhầm thì file vẫn sạch mà số vẫn sai.
    # Cột L: sheet Các case có thêm "Câu mẫu" và "Không khớp thì đi đâu" nên
    # Trạng thái dịch sang phải hai cột so với bản đầu.
    ("Các case", "'4 · Các case'!$L$5:$L$14"),
    ("Luật cắt ngang", "'5 · Luật cắt ngang'!$F$5:$F$9"),
]
for r, (ten, vung) in enumerate(nhom, 5):
    ws.cell(row=r, column=1, value=ten)
    # So theo CHỮ chứ không theo emoji: "⚠️" có ký tự biến thể ẩn (U+FE0F) nên
    # COUNTIF dễ không khớp tuỳ phiên bản Excel.
    ws.cell(row=r, column=2, value=f'=COUNTIF({vung},"*Đã có*")')
    ws.cell(row=r, column=3, value=f'=COUNTIF({vung},"*Một phần*")')
    ws.cell(row=r, column=4, value=f'=COUNTIF({vung},"*Chưa có*")')
    ws.cell(row=r, column=5, value=f"=SUM(B{r}:D{r})")
r_tong = 5 + len(nhom)
ws.cell(row=r_tong, column=1, value="TỔNG CỘNG")
for c in range(2, 6):
    L = get_column_letter(c)
    ws.cell(row=r_tong, column=c, value=f"=SUM({L}5:{L}{r_tong-1})")

for r in range(5, r_tong + 1):
    for c in range(1, 6):
        o = ws.cell(row=r, column=c)
        o.font = Font(name=FONT, size=10, bold=(r == r_tong))
        o.border = vien
        o.alignment = Alignment(horizontal="center" if c > 1 else "left", vertical="center")
    if r == r_tong:
        for c in range(1, 6):
            ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=XANH_NHAT)
for i, w in enumerate([22, 12, 14, 12, 10], 1):
    ws.column_dimensions[get_column_letter(i)].width = w

ws.cell(row=r_tong + 2, column=1,
        value="Ghi chú: các ô trên là CÔNG THỨC COUNTIF đếm từ sheet gốc, không phải số gõ tay.")
ws.cell(row=r_tong + 2, column=1).font = Font(name=FONT, size=9, italic=True, color="666666")
ws.cell(row=r_tong + 3, column=1,
        value="Nguồn số liệu: repo LR-AI-Labs/solutions-in-cars, nhánh duc/agentcar. "
              "Câu mẫu chạy ngày 24/09/2026 với tầng cloud tắt.")
ws.cell(row=r_tong + 3, column=1).font = Font(name=FONT, size=9, italic=True, color="666666")

wb.save("docs/DinhTuyen_Edge_Cloud.xlsx")
print("da luu docs/DinhTuyen_Edge_Cloud.xlsx")
