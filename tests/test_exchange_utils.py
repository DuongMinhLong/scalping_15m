import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import exchange_utils  # noqa: E402
import requests  # noqa: E402
import json


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
        expected = min(250, max(2 * 2, 2 + len(exchange_utils.BLACKLIST_BASES)))
        assert params["per_page"] == expected
        return DummyResponse(
            [{"symbol": "btc"}, {"symbol": "eth"}, {"symbol": "xrp"}, {"symbol": "usdt"}]
        )

    monkeypatch.setattr(requests, "get", fake_get)
    exchange_utils._MCAP_CACHE["timestamp"] = 0
    exchange_utils._MCAP_CACHE["data"] = []
    res1 = exchange_utils.top_by_market_cap(2)
    res2 = exchange_utils.top_by_market_cap(2)
    assert res1 == ["ETH", "XRP"]
    assert res2 == ["ETH", "XRP"]
    assert len(calls) == 1


def test_top_by_market_cap_filters_blacklist(monkeypatch):
    data = [
        {"symbol": "usdt"},
        {"symbol": "btc"},
        {"symbol": "eth"},
        {"symbol": "bnb"},
        {"symbol": "xrp"},
        {"symbol": "ada"},
    ]

    class Resp:
        def json(self):
            return data

        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())
    exchange_utils._MCAP_CACHE["data"] = []
    res = exchange_utils.top_by_market_cap(limit=3, ttl=0)
    assert res == ["ETH", "XRP", "ADA"]


def test_liquidation_snapshot_unsupported_exchange(caplog):
    class DummyExchange:
        has = {"fetchLiquidations": False}

    ex = DummyExchange()
    with caplog.at_level("WARNING"):
        res = exchange_utils.liquidation_snapshot(ex, "ETH/USDT:USDT")
    assert res == {}
    assert "liquidation_snapshot error" not in caplog.text


def test_cache_top_by_qv_caches_results(monkeypatch, tmp_path):
    class DummyExchange:
        def load_markets(self):
            return {
                "AAA/USDT:USDT": {
                    "symbol": "AAA/USDT:USDT",
                    "linear": True,
                    "swap": True,
                    "quote": "USDT",
                    "active": True,
                    "base": "AAA",
                }
            }

        def fetch_tickers(self):
            calls[0] += 1
            return {"AAA/USDT:USDT": {"quoteVolume": 100}}

    calls = [0]
    path = tmp_path / "top.json"
    ex = DummyExchange()

    res1 = exchange_utils.cache_top_by_qv(ex, limit=1, ttl=3600, path=str(path))
    res2 = exchange_utils.cache_top_by_qv(ex, limit=1, ttl=3600, path=str(path))
    res3 = exchange_utils.cache_top_by_qv(ex, limit=1, ttl=0, path=str(path))

    assert res1 == ["AAA/USDT:USDT"]
    assert res2 == ["AAA/USDT:USDT"]
    assert res3 == ["AAA/USDT:USDT"]
    assert calls[0] == 2

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data[0]["base"] == "AAA"


def test_cache_top_by_qv_filters_by_min_qv(tmp_path):
    class DummyExchange:
        def load_markets(self):
            return {
                "AAA/USDT:USDT": {
                    "symbol": "AAA/USDT:USDT",
                    "linear": True,
                    "swap": True,
                    "quote": "USDT",
                    "active": True,
                    "base": "AAA",
                },
                "BBB/USDT:USDT": {
                    "symbol": "BBB/USDT:USDT",
                    "linear": True,
                    "swap": True,
                    "quote": "USDT",
                    "active": True,
                    "base": "BBB",
                },
            }

        def fetch_tickers(self):
            return {
                "AAA/USDT:USDT": {"quoteVolume": 6_000_000},
                "BBB/USDT:USDT": {"quoteVolume": 1_000_000},
            }

    ex = DummyExchange()
    path = tmp_path / "vol.json"
    res = exchange_utils.cache_top_by_qv(
        ex, limit=2, ttl=0, path=str(path), min_qv=5_000_000
    )
    assert res == ["AAA/USDT:USDT"]
