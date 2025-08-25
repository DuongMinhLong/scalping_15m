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


def test_load_usdtm_filters_stablecoins():
    class DummyExchange:
        def load_markets(self):
            return {
                "ETH/USDT:USDT": {
                    "symbol": "ETH/USDT:USDT",
                    "linear": True,
                    "swap": True,
                    "quote": "USDT",
                    "active": True,
                    "base": "ETH",
                },
                "BUSD/USDT:USDT": {
                    "symbol": "BUSD/USDT:USDT",
                    "linear": True,
                    "swap": True,
                    "quote": "USDT",
                    "active": True,
                    "base": "BUSD",
                },
            }

    exchange = DummyExchange()
    markets = exchange_utils.load_usdtm(exchange)
    assert "ETH/USDT:USDT" in markets
    assert "BUSD/USDT:USDT" not in markets


def test_top_by_market_cap(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(1)
        assert params["per_page"] == 2
        return DummyResponse([{"symbol": "btc"}, {"symbol": "eth"}])

    monkeypatch.setattr(requests, "get", fake_get)
    exchange_utils._MCAP_CACHE["timestamp"] = 0
    exchange_utils._MCAP_CACHE["data"] = []
    res1 = exchange_utils.top_by_market_cap(2)
    res2 = exchange_utils.top_by_market_cap(2)
    assert res1 == ["BTC", "ETH"]
    assert res2 == ["BTC", "ETH"]
    assert len(calls) == 1
