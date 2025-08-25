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
        data["rsi14"] = ta.rsi(data["close"], length=14)
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

        data["ema20"], data["ema50"] = (
            ema(data.close, 20),
            ema(data.close, 50),
        )
        data["rsi14"] = rsi(data.close, 14)
    return data


def trend_lbl(e20: float, e50: float, rsi_val: float) -> int:
    """Classify trend direction using EMA alignment and RSI."""

    if e20 > e50 and rsi_val > 50:
        return 1
    if e20 < e50 and rsi_val < 50:
        return -1
    return 0


def detect_sr_levels(df: pd.DataFrame, lookback: int = 5) -> list[float]:
    """Detect simple support/resistance levels.

    The function looks for pivot highs/lows within a ``lookback`` window and
    merges nearby levels to highlight zones that price has reacted to multiple
    times.  It returns a sorted list of levels as floats.
    """

    if df is None or df.empty:
        return []

    lb = max(1, int(lookback))
    data = df.tail(lb * 5).copy()
    highs = data["high"].reset_index(drop=True)
    lows = data["low"].reset_index(drop=True)

    pivots: list[float] = []
    for i in range(lb, len(data) - lb):
        h = highs.iloc[i]
        if h == highs.iloc[i - lb : i + lb + 1].max():
            pivots.append(float(h))
        l = lows.iloc[i]
        if l == lows.iloc[i - lb : i + lb + 1].min():
            pivots.append(float(l))

    if not pivots:
        return []

    pivots.sort()
    avg_range = (highs - lows).mean()
    tol = float(avg_range * 0.5) if avg_range > 0 else 0.0
    merged: list[float] = []
    for lvl in pivots:
        if not merged or abs(lvl - merged[-1]) > tol:
            merged.append(lvl)
        else:
            merged[-1] = (merged[-1] + lvl) / 2
    return merged

