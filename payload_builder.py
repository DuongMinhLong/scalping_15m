"""Payload construction utilities for 15m trading with 1h/4h snapshots."""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import partial
from threading import Lock
from typing import Dict, List, Set, Tuple

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
from positions import get_open_position_pairs
from events import event_snapshot

logger = logging.getLogger(__name__)

# Cache for OHLCV data by timeframe along with fetch timestamps
CACHE_M15: Dict[str, Tuple[pd.DataFrame, datetime]] = {}
CACHE_H1: Dict[str, Tuple[pd.DataFrame, datetime]] = {}
CACHE_H4: Dict[str, Tuple[pd.DataFrame, datetime]] = {}
LOCK_M15 = Lock()
LOCK_H1 = Lock()
LOCK_H4 = Lock()

# Cache management configuration
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))  # seconds
CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "100"))


def _purge_cache(cache: Dict[str, Tuple[pd.DataFrame, datetime]]) -> None:
    """Remove cache entries older than :data:`CACHE_TTL` or exceeding size."""

    now = datetime.now(timezone.utc)
    # Purge expired entries
    expired = [
        k for k, (_, ts) in cache.items() if now - ts > timedelta(seconds=CACHE_TTL)
    ]
    for k in expired:
        del cache[k]

    # Enforce max cache size, removing oldest entries first
    if len(cache) > CACHE_MAX_SIZE:
        sorted_items = sorted(cache.items(), key=lambda item: item[1][1])
        for k, _ in sorted_items[: len(cache) - CACHE_MAX_SIZE]:
            del cache[k]


def _tf_with_cache(
    exchange, symbol: str, timeframe: str, cache, lock, limit: int = 200
) -> Dict:
    """Fetch ``timeframe`` data with caching and return :func:`build_tf`."""

    with lock:
        _purge_cache(cache)
        if symbol not in cache:
            df = fetch_ohlcv_df(exchange, symbol, timeframe, 300)
        else:
            df, _ = cache[symbol]
            last_ts = int(df.index[-1].timestamp() * 1000)
            new = fetch_ohlcv_df(exchange, symbol, timeframe, 300, since=last_ts)
            if not new.empty:
                df = pd.concat([df, new]).sort_index()
                df = df[~df.index.duplicated(keep="last")].tail(300)
        cache[symbol] = (df, datetime.now(timezone.utc))
        _purge_cache(cache)
        df_tf = cache[symbol][0]
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
        "m15": _tf_with_cache(exchange, symbol, "15m", CACHE_M15, LOCK_M15, limit=200),
        "h1": _tf_with_cache(exchange, symbol, "1h", CACHE_H1, LOCK_H1, limit=1),
        "h4": _tf_with_cache(exchange, symbol, "4h", CACHE_H4, LOCK_H4, limit=1),
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
    pos_pairs = get_open_position_pairs(exchange)

    env_pairs = os.getenv("COIN_PAIRS", "")
    symbols: List[str] = []
    for raw in env_pairs.split(","):
        raw = raw.strip().upper()
        if not raw:
            continue
        pair = raw if raw.endswith("USDT") else f"{raw}USDT"
        if pair in exclude_pairs or pair in pos_pairs:
            continue
        symbols.append(pair_to_symbol(pair))
        if len(symbols) >= limit:
            break

    func = partial(coin_payload, exchange)
    coins: List[Dict] = []
    if symbols:
        with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as ex:
            futures = {ex.submit(func, s): s for s in symbols}
            for fut in as_completed(futures):
                sym = futures[fut]
                try:
                    coins.append(fut.result())
                except Exception as e:
                    logger.warning("coin_payload failed for %s: %s", sym, e)
    payload = {
        "time": time_payload(),
        "events": event_snapshot(),
        "coins": [drop_empty(c) for c in coins],
    }
    return {k: v for k, v in payload.items() if v not in (None, "", [], {})}
