from pathlib import Path

import pytest

from agentcar.caps import load_caps

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def caps():
    return load_caps(ROOT / "caps" / "vf9.yaml")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Test KHÔNG BAO GIỜ được gọi ra ngoài.

    .env thật có thể đang bật tầng [2]; nếu không chặn thì mỗi lần chạy pytest sẽ
    bắn hàng chục request lên DashScope và tính tiền. Chặn hai lớp: tắt cấu hình,
    và cho client thật nổ nếu có đường nào lọt qua.
    """
    monkeypatch.setenv("AGENTCAR_LLM_ENABLED", "false")
    # Test không được ghi vào log thật — nếu không, mọi thống kê sẽ lẫn hàng trăm
    # lượt giả và số đo trở nên vô nghĩa.
    monkeypatch.setenv("AGENTCAR_LOG", "off")

    def forbidden(*args, **kwargs):
        raise AssertionError("test đã gọi mạng thật — phải dùng client giả")

    monkeypatch.setattr("agentcar.llm.DashScopeClient.complete", forbidden)


def caps_theo(caps, **chinh_sach):
    """Bản sao caps ép theo một chính sách nghiệm thu cụ thể.

    Hai tài liệu (QC và BA) mâu thuẫn ở vài điểm, khối `policy` trong caps quyết
    bên nào thắng. Test phải nói rõ mình đang kiểm nhánh nào, nếu không thì đổi
    chính sách là cả bộ test đỏ mà chẳng có gì hỏng.
    """
    from dataclasses import replace
    return replace(caps, policy={**caps.policy, **chinh_sach})
