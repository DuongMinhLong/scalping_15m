import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import exchange_utils  # noqa: E402
import requests  # noqa: E402


class DummyResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def test_top_by_market_cap(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        assert params["per_page"] == 2
        return DummyResponse([{"symbol": "btc"}, {"symbol": "eth"}])

    monkeypatch.setattr(requests, "get", fake_get)
    res = exchange_utils.top_by_market_cap(2)
    assert res == ["BTC", "ETH"]
