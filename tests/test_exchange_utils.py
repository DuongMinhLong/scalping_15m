import exchange_utils
import pytest


def test_fetch_ohlcv_df(monkeypatch):
    class DummyExchange:
        def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
            return [[0, 1, 2, 0, 1, 100]]

    ex = DummyExchange()
    df = exchange_utils.fetch_ohlcv_df(ex, "XAU/USD", "1m", limit=1)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_orderbook_snapshot_calculates_values():
    class DummyExchange:
        def fetch_order_book(self, symbol, limit=10):
            return {"bids": [[10, 1]], "asks": [[11, 1]]}

    snap = exchange_utils.orderbook_snapshot(DummyExchange(), "XAU/USD")
    assert snap["sp"] > 0
    assert snap["b"] > 0
    assert snap["a"] > 0


def test_make_exchange_falls_back_without_ccxt(monkeypatch):
    monkeypatch.setenv("OANDA_API_KEY", "k")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "a")
    monkeypatch.setattr(exchange_utils.ccxt, "oanda", None, raising=False)
    ex = exchange_utils.make_exchange()
    assert isinstance(ex, exchange_utils.OandaREST)


def test_make_exchange_requires_credentials(monkeypatch):
    monkeypatch.delenv("OANDA_API_KEY", raising=False)
    monkeypatch.delenv("OANDA_ACCOUNT_ID", raising=False)
    with pytest.raises(RuntimeError):
        exchange_utils.make_exchange()


def test_make_exchange_uses_api_url_with_ccxt(monkeypatch):
    class Dummy:
        def __init__(self, config):
            self.urls = {"api": "default"}
            self.apiKey = None
            self.uid = None

    monkeypatch.setenv("OANDA_API_KEY", "k")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "a")
    monkeypatch.setenv("OANDA_API_URL", "https://example.com/v3")
    monkeypatch.setattr(exchange_utils.ccxt, "oanda", Dummy, raising=False)
    ex = exchange_utils.make_exchange()
    assert ex.urls["api"] == "https://example.com/v3"
