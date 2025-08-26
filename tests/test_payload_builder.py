import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import payload_builder  # noqa: E402


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
    monkeypatch.setattr(payload_builder, "detect_sr_levels", lambda *a, **k: [])

    df = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.05, 2.05],
            "volume": [100.0, 200.0],
        },
        index=pd.date_range("2024-01-01", periods=2, freq="1h"),
    )

    res = payload_builder.build_1h(df)
    assert all(len(candle) == 5 for candle in res["ohlcv"])


def test_build_1h_volume_numeric(monkeypatch):
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
    monkeypatch.setattr(payload_builder, "detect_sr_levels", lambda *a, **k: [])

    df = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.1, 2.1],
            "low": [0.9, 1.9],
            "close": [1.05, 2.05],
            "volume": [100.0, 312066130.0],
        },
        index=pd.date_range("2024-01-01", periods=2, freq="1h"),
    )

    res = payload_builder.build_1h(df)
    assert res["ohlcv"][-1][-1] == "312M"


def test_build_1h_limits_length_and_snap(monkeypatch):
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
    monkeypatch.setattr(payload_builder, "trend_lbl", lambda *a, **k: 0)
    monkeypatch.setattr(payload_builder, "detect_sr_levels", lambda *a, **k: [])

    df = pd.DataFrame(
        {
            "open": range(25),
            "high": range(25),
            "low": range(25),
            "close": range(25),
            "volume": range(25),
        },
        index=pd.date_range("2024-01-01", periods=25, freq="1h"),
    )

    res = payload_builder.build_1h(df)
    assert len(res["ohlcv"]) == 20
    assert all(len(v) == 20 for v in res["ind"].values())
    assert set(res["ind"].keys()) == {
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
    }

    snap = payload_builder.build_1h(df, limit=1)
    expected = payload_builder.build_snap(df)
    assert snap == expected


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
            ("macd_sig", 0.0),
            ("macd_hist", 0.0),
            ("atr14", 0.0),
            ("vol_spike", 0.0),
        ]:
            df[col] = val
        return df

    monkeypatch.setattr(payload_builder, "add_indicators", fake_add_indicators)
    monkeypatch.setattr(payload_builder, "trend_lbl", lambda *a, **k: 0)

    df = pd.DataFrame(
        {
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.05],
            "volume": [100.0],
        },
        index=pd.date_range("2024-01-01", periods=1, freq="1h"),
    )

    snap = payload_builder.build_snap(df)
    assert snap["ema20"] == 4270.76


def test_coin_payload_includes_higher_timeframes(monkeypatch):
    import pandas as pd

    payload_builder.CACHE_H1.clear()
    payload_builder.CACHE_H4.clear()
    payload_builder.CACHE_D1.clear()

    def fake_fetch(exchange, symbol, timeframe, limit, since=None):
        return pd.DataFrame(
            {
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [1.0],
            },
            index=pd.date_range("2024-01-01", periods=1, freq="1h", tz="UTC"),
        )

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

    monkeypatch.setattr(payload_builder, "fetch_ohlcv_df", fake_fetch)
    monkeypatch.setattr(payload_builder, "add_indicators", fake_add_indicators)
    monkeypatch.setattr(payload_builder, "trend_lbl", lambda *a, **k: 0)
    monkeypatch.setattr(payload_builder, "detect_sr_levels", lambda *a, **k: [])
    monkeypatch.setattr(payload_builder, "orderbook_snapshot", lambda ex, sym, depth=10: {"sp": 0.1})
    monkeypatch.setattr(payload_builder, "funding_snapshot", lambda ex, sym: {"rate": 0.0})
    monkeypatch.setattr(payload_builder, "open_interest_snapshot", lambda ex, sym: {"amount": 0.0})
    monkeypatch.setattr(payload_builder, "cvd_snapshot", lambda ex, sym: {"cvd": 0.0})
    monkeypatch.setattr(payload_builder, "liquidation_snapshot", lambda ex, sym: {"long_liq": 0.0})

    res = payload_builder.coin_payload(None, "BTC/USDT:USDT")
    assert {
        "pair",
        "h1",
        "h4",
        "d1",
        "funding",
        "oi",
        "cvd",
        "liquidation",
        "orderbook",
    } <= set(res.keys())
    assert res["orderbook"]["sp"] == 0.1


def test_time_payload_sessions():
    from datetime import datetime, timezone

    now = datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc)
    asia = payload_builder.time_payload(now)
    assert asia["session"] == "asia" and asia["utc_hour"] == 2

    now = datetime(2024, 1, 1, 18, 0, tzinfo=timezone.utc)
    us = payload_builder.time_payload(now)
    assert us["session"] == "us" and us["mins_to_close"] == 360
