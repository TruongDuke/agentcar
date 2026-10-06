import pytest

from agentcar.numbers import parse_number


@pytest.mark.parametrize("text,value", [
    ("hai mươi ba", 23), ("hai ba", 23), ("mười lăm", 15), ("mười", 10),
    ("hai mươi mốt", 21), ("hai mươi tư", 24), ("một trăm", 100),
    ("một trăm hai mươi", 120), ("22", 22), ("22.5", 22.5),
    ("năm rưỡi", 5.5), ("một nửa", 0.5), ("tám", 8),
])
def test_parse(text, value):
    assert parse_number(text.split(), 0)[0] == value


def test_khong_is_not_zero():
    """'không' là từ hỏi, không phải số 0 — nếu đọc thành 0 thì câu hỏi biến thành lệnh."""
    assert parse_number(["không"], 0)[0] is None


def test_consumes_exact_tokens():
    tokens = "hai mươi ba độ".split()
    assert parse_number(tokens, 0) == (23, 3)


@pytest.mark.parametrize("bare,accented", [
    ("hai muoi ba", "hai mươi ba"),
    ("muoi lam", "mười lăm"),
    ("hai muoi mot", "hai mươi mốt"),
    ("mot tram hai muoi", "một trăm hai mươi"),
    ("mot nua", "một nửa"),
    ("nam ruoi", "năm rưỡi"),
])
def test_works_without_diacritics(bare, accented):
    """ASR hay trả câu không dấu — số đọc bằng chữ vẫn phải đọc được."""
    assert parse_number(bare.split(), 0) == parse_number(accented.split(), 0)


def test_muoi_is_disambiguated_by_position():
    """'mười' và 'mươi' bỏ dấu đều thành 'muoi'; vị trí phân biệt được."""
    assert parse_number("muoi lam".split(), 0)[0] == 15    # mười lăm
    assert parse_number("hai muoi".split(), 0)[0] == 20    # hai mươi


@pytest.mark.parametrize("text", ["nhầm", "lăm", "nhăm", "tư"])
def test_combining_forms_are_not_standalone_numbers(text):
    """"nhăm" chỉ là số khi đứng sau "mươi". Bỏ dấu nó trùng "nhầm" (sửa ý), nên
    đọc bừa thành 5 sẽ biến "điều hoà nhầm rồi" thành đặt mức 5."""
    assert parse_number([text], 0)[0] is None


@pytest.mark.parametrize("text,value", [
    ("hai mươi nhăm", 25), ("hai mươi lăm", 25), ("hai mươi mốt", 21),
    ("hai mươi tư", 24), ("mười lăm", 15),
])
def test_combining_forms_work_after_muoi(text, value):
    assert parse_number(text.split(), 0)[0] == value


def test_mot_stays_a_standalone_number():
    """"một" và "mốt" bỏ dấu cùng thành "mot" — không được chặn cả hai."""
    assert parse_number("một trăm".split(), 0)[0] == 100
    assert parse_number("một nửa".split(), 0)[0] == 0.5
