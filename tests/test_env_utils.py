from env_utils import save_text


def test_save_text_creates_nested_dirs(tmp_path):
    save_text("limit_orders/XAUUSD.json", "hello", folder=str(tmp_path))
    target = tmp_path / "limit_orders" / "XAUUSD.json"
    assert target.exists()
    assert target.read_text() == "hello"
