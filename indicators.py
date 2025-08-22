"""Indicator calculations used across the project."""

from __future__ import annotations

import pandas as pd

# Attempt to import pandas-ta for richer indicator support.  The rest of the
# code transparently falls back to simple pandas implementations if the import
# fails.
USE_PTA = False
try:  # pragma: no cover - optional dependency
    import pandas_ta as ta

    USE_PTA = True
except Exception:  # pragma: no cover - handled gracefully
    USE_PTA = False


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` enriched with common technical indicators."""

    data = df.copy()
    if USE_PTA:
        data["ema20"] = ta.ema(data["close"], length=20)
        data["ema50"] = ta.ema(data["close"], length=50)
        data["ema99"] = ta.ema(data["close"], length=99)
        data["ema200"] = ta.ema(data["close"], length=200)
        data["rsi14"] = ta.rsi(data["close"], length=14)
        macd = ta.macd(data["close"], fast=12, slow=26, signal=9)
        data["macd"] = macd["MACD_12_26_9"]
        data["macd_sig"] = macd["MACDs_12_26_9"]
        data["macd_hist"] = macd["MACDh_12_26_9"]
        tr = ta.true_range(data["high"], data["low"], data["close"])
        data["atr14"] = ta.ema(tr, length=14)
        data["vol_spike"] = data["volume"] / (ta.ema(data["volume"], length=20) + 1e-12)
    else:
        # Lightweight pandas fallbacks
        def ema(series: pd.Series, span: int) -> pd.Series:
            return series.ewm(span=span, adjust=False).mean()

        def rsi(series: pd.Series, n: int = 14) -> pd.Series:
            change = series.diff()
            up = change.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
            down = (-change.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
            rs = up / (down + 1e-12)
            return 100 - (100 / (1 + rs))

        def macd(series: pd.Series, f: int = 12, sl: int = 26, sig: int = 9):
            mac = ema(series, f) - ema(series, sl)
            sig_line = ema(mac, sig)
            return mac, sig_line, mac - sig_line

        def atr(df_: pd.DataFrame, n: int = 14) -> pd.Series:
            h, l, c = df_["high"], df_["low"], df_["close"]
            prev_close = c.shift(1)
            tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
            return tr.ewm(alpha=1 / n, adjust=False).mean()

        data["ema20"], data["ema50"], data["ema99"], data["ema200"] = (
            ema(data.close, 20),
            ema(data.close, 50),
            ema(data.close, 99),
            ema(data.close, 200),
        )
        data["rsi14"] = rsi(data.close, 14)
        mac, sig, hist = macd(data.close)
        data["macd"], data["macd_sig"], data["macd_hist"] = mac, sig, hist
        data["atr14"] = atr(data, 14)
        data["vol_spike"] = data["volume"] / (data["volume"].ewm(span=20, adjust=False).mean() + 1e-12)
    return data


def trend_lbl(e20: float, e50: float, e200: float, macd_val: float, rsi_val: float) -> str:
    """Classify trend direction using EMA alignment and momentum signals."""

    if e20 > e50 > e200 and macd_val > 0 and rsi_val > 50:
        return "up"
    if e20 < e50 < e200 and macd_val < 0 and rsi_val < 50:
        return "down"
    return "flat"

