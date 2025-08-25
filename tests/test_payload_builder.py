import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import payload_builder  # noqa: E402


def test_build_15m_adds_volume(monkeypatch):
    import pandas as pd

    def fake_add_indicators(df):
        for col in ["ema20", "ema50", "ema200", "rsi14", "macd"]:
            df[col] = 0.0
        return df

    monkeypatch.setattr(payload_builder, "add_indicators", fake_add_indicators)

    df = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.05, 2.05],
            "volume": [100.0, 200.0],
        },
        index=pd.date_range("2024-01-01", periods=2, freq="15T"),
    )

    res = payload_builder.build_15m(df)
    assert all(len(candle) == 5 for candle in res["ohlcv"])


def test_build_15m_formats_large_volume(monkeypatch):
    import pandas as pd

    def fake_add_indicators(df):
        for col in ["ema20", "ema50", "ema200", "rsi14", "macd"]:
            df[col] = 0.0
        return df

    monkeypatch.setattr(payload_builder, "add_indicators", fake_add_indicators)

    df = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.05, 2.05],
            "volume": [100.0, 312066130.0],
        },
        index=pd.date_range("2024-01-01", periods=2, freq="15T"),
    )

    res = payload_builder.build_15m(df)
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
        index=pd.date_range("2024-01-01", periods=1, freq="15T"),
    )

    snap = payload_builder.build_snap(df)
    assert snap["ema20"] == 4270.76
