"""Payload construction utilities for building model inputs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Set

import pandas as pd
from threading import Lock

from env_utils import compact, drop_empty, now_ms, rfloat
from exchange_utils import (
    fetch_ohlcv_df,
    orderbook_snapshot,
    top_by_qv,
    top_by_24h_change,
)
from indicators import add_indicators, trend_lbl


def session_meta() -> Dict[str, int | str]:
    """Return current trading session label and minutes remaining."""

    now = datetime.now(timezone.utc)
    hour = now.hour
    if 0 <= hour < 8:
        label = "Asia"
        end = now.replace(hour=8, minute=0, second=0, microsecond=0)
    elif 8 <= hour < 16:
        label = "Europe"
        end = now.replace(hour=16, minute=0, second=0, microsecond=0)
    else:
        label = "US"
        end = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return {
        "label": label,
        "utc_hour": hour,
        "mins_to_close": max(0, int((end - now).total_seconds() // 60)),
    }


class ThreadSafeCache:
    """Thread-safe cache for storing OHLCV DataFrames by symbol."""

    def __init__(self) -> None:
        self._cache: Dict[str, pd.DataFrame] = {}
        self._lock = Lock()

    def get(self, symbol: str, loader: Callable[[], pd.DataFrame]) -> pd.DataFrame:
        """Return cached DataFrame for ``symbol`` or load it if missing."""

        with self._lock:
            if symbol not in self._cache:
                self._cache[symbol] = loader()
            return self._cache[symbol]


CACHE_H1 = ThreadSafeCache()
CACHE_H4 = ThreadSafeCache()


def norm_pair_symbol(symbol: str) -> str:
    """Normalise CCXT-style symbols to ``BASEQUOTE`` format."""

    if not symbol:
        return ""
    return symbol.split(":")[0].replace("/", "").upper()


def build_15m(df: pd.DataFrame) -> Dict:
    """Build the detailed 15m payload with indicators and OHLCV."""

    data = add_indicators(df)
    tail20 = data.tail(20)
    ohlcv20 = [
        [
            rfloat(r.open),
            rfloat(r.high),
            rfloat(r.low),
            rfloat(r.close),
            rfloat(r.volume),
        ]
        for _, r in tail20.iterrows()
    ]
    swing_high = rfloat(data["high"].tail(20).max())
    swing_low = rfloat(data["low"].tail(20).min())
    key = {
        "prev_close": rfloat(data.close.iloc[-2]),
        "last_close": rfloat(data.close.iloc[-1]),
        "swing_high": swing_high,
        "swing_low": swing_low,
    }
    ind = {
        "ema20": compact(data["ema20"].tail(20).tolist()),
        "ema50": compact(data["ema50"].tail(20).tolist()),
        "ema99": compact(data["ema99"].tail(20).tolist()),
        "ema200": compact(data["ema200"].tail(20).tolist()),
        "rsi14": compact(data["rsi14"].tail(20).tolist()),
        "macd": compact(data["macd"].tail(20).tolist()),
        "macd_sig": compact(data["macd_sig"].tail(20).tolist()),
        "macd_hist": compact(data["macd_hist"].tail(20).tolist()),
        "atr14": compact(data["atr14"].tail(20).tolist()),
        "vol_spike": compact(data["vol_spike"].tail(20).tolist()),
    }
    return {"ohlcv": ohlcv20, "ind": ind, "key": key}


def build_snap(df: pd.DataFrame) -> Dict:
    """Return a lightweight snapshot containing the latest indicator values."""

    data = add_indicators(df)
    return {
        "ema20": rfloat(data["ema20"].iloc[-1]),
        "ema50": rfloat(data["ema50"].iloc[-1]),
        "ema99": rfloat(data["ema99"].iloc[-1]),
        "ema200": rfloat(data["ema200"].iloc[-1]),
        "rsi": rfloat(data["rsi14"].iloc[-1]),
        "macd": rfloat(data["macd"].iloc[-1]),
        "trend": trend_lbl(
            data["ema20"].iloc[-1],
            data["ema50"].iloc[-1],
            data["ema200"].iloc[-1],
            data["macd"].iloc[-1],
            data["rsi14"].iloc[-1],
        ),
    }


def coin_payload(exchange, symbol: str) -> Dict:
    """Build payload for a single symbol including multi-timeframe data."""

    df15 = fetch_ohlcv_df(exchange, symbol, "15m", 300)
    df_h1 = CACHE_H1.get(
        symbol, lambda: fetch_ohlcv_df(exchange, symbol, "1h", 300)
    )
    df_h4 = CACHE_H4.get(
        symbol, lambda: fetch_ohlcv_df(exchange, symbol, "4h", 300)
    )
    payload = {
        "pair": norm_pair_symbol(symbol),
        "c15": build_15m(df15),
        "h1": build_snap(df_h1),
        "h4": build_snap(df_h4),
        "orderbook": orderbook_snapshot(exchange, symbol, depth=10),
    }
    return drop_empty(payload)


def eth_bias(exchange) -> Dict:
    """Convenience wrapper returning ETH H1/H4 snapshots."""

    symbol = "ETH/USDT"
    df_h1 = CACHE_H1.get(
        symbol, lambda: fetch_ohlcv_df(exchange, symbol, "1h", 300)
    )
    df_h4 = CACHE_H4.get(
        symbol, lambda: fetch_ohlcv_df(exchange, symbol, "4h", 300)
    )
    return {"h1": build_snap(df_h1), "h4": build_snap(df_h4)}


def build_payload(exchange, limit: int = 20, exclude_pairs: Set[str] | None = None) -> Dict:
    """Build the full payload used by the orchestrator."""

    exclude_pairs = exclude_pairs or set()
    # Prioritize symbols with the largest 24h percentage change
    symbols_raw = top_by_24h_change(exchange, limit * 3)
    symbols: List[str] = []
    for s in symbols_raw:
        pair = s.replace("/", "").upper()
        if pair in exclude_pairs:
            continue
        symbols.append(s)
        if len(symbols) >= limit:
            break
    if len(symbols) < limit:
        # If not enough, fill the remainder with top quote-volume symbols
        fallback_raw = top_by_qv(exchange, limit * 3)
        for s in fallback_raw:
            pair = s.replace("/", "").upper()
            if pair in exclude_pairs or s in symbols:
                continue
            symbols.append(s)
            if len(symbols) >= limit:
                break
    coins = [coin_payload(exchange, s) for s in symbols]
    return {
        "time": {"now_utc": now_ms(), "session": session_meta()},
        "eth": eth_bias(exchange),
        "coins": [drop_empty(c) for c in coins],
    }

