"""Payload construction utilities for 1h trading with higher timeframe snapshots."""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import partial
from threading import Lock
from typing import Dict, List, Set

import pandas as pd

from env_utils import compact, drop_empty, human_num, rfloat, rprice
from exchange_utils import (
    fetch_ohlcv_df,
    orderbook_snapshot,
    funding_snapshot,
    open_interest_snapshot,
    cvd_snapshot,
    liquidation_snapshot,
)
from indicators import add_indicators, trend_lbl
from positions import positions_snapshot

logger = logging.getLogger(__name__)

# Cache for OHLCV data by timeframe
CACHE_H1: Dict[str, pd.DataFrame] = {}
CACHE_H4: Dict[str, pd.DataFrame] = {}
CACHE_D1: Dict[str, pd.DataFrame] = {}
LOCK_H1 = Lock()
LOCK_H4 = Lock()
LOCK_D1 = Lock()


def _tf_with_cache(
    exchange, symbol: str, timeframe: str, cache, lock, limit: int = 200
) -> Dict:
    """Fetch ``timeframe`` data with caching and return :func:`build_tf`."""

    with lock:
        if symbol not in cache:
            cache[symbol] = fetch_ohlcv_df(exchange, symbol, timeframe, 300)
        else:
            last_ts = int(cache[symbol].index[-1].timestamp() * 1000)
            new = fetch_ohlcv_df(exchange, symbol, timeframe, 300, since=last_ts)
            if not new.empty:
                df = pd.concat([cache[symbol], new]).sort_index()
                cache[symbol] = df[~df.index.duplicated(keep="last")].tail(300)
        df_tf = cache[symbol]
    return build_tf(df_tf, limit=limit)


def time_payload(now: datetime | None = None) -> Dict:
    """Return current UTC time info and trading session details."""

    now = now or datetime.now(timezone.utc)
    utc_hour = now.hour
    if 0 <= utc_hour < 8:
        session = "asia"
        end = now.replace(hour=8, minute=0, second=0, microsecond=0)
    elif 8 <= utc_hour < 16:
        session = "europe"
        end = now.replace(hour=16, minute=0, second=0, microsecond=0)
    else:
        session = "us"
        end = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    mins_to_close = int((end - now).total_seconds() / 60)
    return {
        "now_utc": now.isoformat().replace("+00:00", "Z"),
        "utc_hour": utc_hour,
        "session": session,
        "mins_to_close": mins_to_close,
    }


def norm_pair_symbol(symbol: str) -> str:
    """Normalise CCXT-style symbols to ``BASEQUOTE`` format."""

    if not symbol:
        return ""
    return symbol.split(":")[0].replace("/", "").upper()


def pair_to_symbol(pair: str) -> str:
    """Convert ``BASEQUOTE`` pair into CCXT ``BASE/QUOTE:QUOTE`` symbol."""

    if not pair:
        return ""
    if pair.endswith("USDT"):
        base = pair[:-4]
        return f"{base}/USDT:USDT"
    return pair


def strip_numeric_prefix(base: str) -> str:
    return re.sub(r"^\d+", "", base)


def build_tf(df: pd.DataFrame, limit: int = 200, nd: int = 5) -> Dict:
    """Build the timeframe payload returning only OHLCV data."""

    if limit <= 1:
        return build_snap(df)

    tail = df.tail(limit)
    ohlcv = [
        compact([r.open, r.high, r.low, r.close], nd) + [human_num(r.volume)]
        for _, r in tail.iterrows()
    ]
    return {"ohlcv": ohlcv}


def build_snap(df: pd.DataFrame) -> Dict:
    """Return a lightweight snapshot containing the latest indicator values."""

    data = add_indicators(df)
    return {
        "ema20": rprice(data["ema20"].iloc[-1]),
        "ema50": rprice(data["ema50"].iloc[-1]),
        "rsi": rfloat(data["rsi14"].iloc[-1]),
        "t": trend_lbl(
            data["ema20"].iloc[-1],
            data["ema50"].iloc[-1],
            data["rsi14"].iloc[-1],
        ),
    }


def coin_payload(exchange, symbol: str) -> Dict:
    """Build payload for a single symbol with thread-safe caching."""

    payload = {
        "pair": norm_pair_symbol(symbol),
        "h1": _tf_with_cache(exchange, symbol, "1h", CACHE_H1, LOCK_H1),
        "h4": _tf_with_cache(exchange, symbol, "4h", CACHE_H4, LOCK_H4),
        "d1": _tf_with_cache(exchange, symbol, "1d", CACHE_D1, LOCK_D1),
        "funding": funding_snapshot(exchange, symbol),
        "oi": open_interest_snapshot(exchange, symbol),
        "cvd": cvd_snapshot(exchange, symbol),
        "liquidation": liquidation_snapshot(exchange, symbol),
        "orderbook": orderbook_snapshot(exchange, symbol, depth=10),
    }
    return drop_empty(payload)


def build_payload(
    exchange,
    limit: int = 10,
    exclude_pairs: Set[str] | None = None,
) -> Dict:
    """Build the payload used by the orchestrator with time info only.

    Symbols are read from the ``COIN_PAIRS`` environment variable as a
    comma-separated list of ``BASE`` or ``BASEUSDT`` pairs. Any pairs
    already in ``exclude_pairs`` or with existing positions are skipped.
    """

    exclude_pairs = exclude_pairs or set()
    positions = positions_snapshot(exchange)
    pos_pairs = {p.get("pair") for p in positions}

    env_pairs = os.getenv("COIN_PAIRS", "")
    symbols: List[str] = [pair_to_symbol(p) for p in pos_pairs]
    for raw in env_pairs.split(","):
        raw = raw.strip().upper()
        if not raw:
            continue
        pair = raw if raw.endswith("USDT") else f"{raw}USDT"
        if pair in exclude_pairs or pair in pos_pairs:
            continue
        symbols.append(pair_to_symbol(pair))
        if len(symbols) >= limit + len(pos_pairs):
            break

    func = partial(coin_payload, exchange)
    coins: List[Dict] = []
    with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as ex:
        futures = {ex.submit(func, s): s for s in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                coins.append(fut.result())
            except Exception as e:
                logger.warning("coin_payload failed for %s: %s", sym, e)
    return drop_empty(
        {
            "time": time_payload(),
            "coins": [drop_empty(c) for c in coins],
            "positions": positions,
        }
    )
