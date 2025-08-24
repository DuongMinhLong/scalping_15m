import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import payload_builder  # noqa: E402
import requests  # noqa: E402


class DummyResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def test_news_snapshot(monkeypatch):
    def fake_get(url, params=None, timeout=None, headers=None):
        assert "auth_token" in params
        data = {
            "results": [
                {"title": "A", "domain": "d1"},
                {"title": "B" * 130, "domain": "d2"},
            ]
        }
        return DummyResponse(data)

    monkeypatch.setenv("NEWS_API_KEY", "key")
    monkeypatch.setattr(requests, "get", fake_get)
    snap = payload_builder.news_snapshot()
    long_headline = "B" * 120 + "…"
    assert snap == {"news": f"A – d1 • {long_headline}"}


def test_build_1h_adds_volume(monkeypatch):
    import pandas as pd

    def fake_add_indicators(df):
        for col in [
            "ema20",
            "ema50",
            "ema99",
            "ema200",
            "rsi14",
            "macd",
            "macd_sig",
            "macd_hist",
            "atr14",
            "vol_spike",
        ]:
            df[col] = 0.0
        return df

    monkeypatch.setattr(payload_builder, "add_indicators", fake_add_indicators)
    monkeypatch.setattr(payload_builder, "detect_sr_levels", lambda df, lookback: [])

    df = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.05, 2.05],
            "volume": [100.0, 200.0],
        },
        index=pd.date_range("2024-01-01", periods=2, freq="H"),
    )

    res = payload_builder.build_1h(df)
    assert all(len(candle) == 5 for candle in res["ohlcv"])


def test_build_1h_formats_large_volume(monkeypatch):
    import pandas as pd

    def fake_add_indicators(df):
        for col in [
            "ema20",
            "ema50",
            "ema99",
            "ema200",
            "rsi14",
            "macd",
            "macd_sig",
            "macd_hist",
            "atr14",
            "vol_spike",
        ]:
            df[col] = 0.0
        return df

    monkeypatch.setattr(payload_builder, "add_indicators", fake_add_indicators)
    monkeypatch.setattr(payload_builder, "detect_sr_levels", lambda df, lookback: [])

    df = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.05, 2.05],
            "volume": [100.0, 312066130.0],
        },
        index=pd.date_range("2024-01-01", periods=2, freq="H"),
    )

    res = payload_builder.build_1h(df)
    assert res["ohlcv"][-1][-1] == "312M"


def test_build_snap_rounds_price(monkeypatch):
    import pandas as pd

    def fake_add_indicators(df):
        for col, val in [
            ("ema20", 4270.7607),
            ("ema50", 0.0),
            ("ema99", 0.0),
            ("ema200", 0.0),
            ("rsi14", 0.0),
            ("macd", 0.0),
        ]:
            df[col] = val
        return df

    monkeypatch.setattr(payload_builder, "add_indicators", fake_add_indicators)
    monkeypatch.setattr(payload_builder, "trend_lbl", lambda *a, **k: "flat")

    df = pd.DataFrame(
        {
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.05],
            "volume": [100.0],
        },
        index=pd.date_range("2024-01-01", periods=1, freq="H"),
    )

    snap = payload_builder.build_snap(df)
    assert snap["ema20"] == 4270.76
