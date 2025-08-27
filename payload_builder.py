"""Payload construction utilities for 15m trading with higher timeframe snapshots."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import partial
from threading import Lock
from typing import Dict, List, Set

import pandas as pd

from env_utils import compact, compact_price, drop_empty, human_num, rfloat, rprice
from exchange_utils import (
    fetch_ohlcv_df,
    load_usdtm,
    orderbook_snapshot,
    cache_top_by_qv,
    top_by_market_cap,
    funding_snapshot,
    open_interest_snapshot,
    cvd_snapshot,
    liquidation_snapshot,
)
from indicators import add_indicators, trend_lbl, detect_sr_levels
from positions import positions_snapshot

logger = logging.getLogger(__name__)

# Cache for OHLCV data by timeframe
CACHE_M15: Dict[str, pd.DataFrame] = {}
CACHE_H1: Dict[str, pd.DataFrame] = {}
CACHE_H4: Dict[str, pd.DataFrame] = {}
LOCK_M15 = Lock()
LOCK_H1 = Lock()
LOCK_H4 = Lock()


def _snap_with_cache(exchange, symbol: str, timeframe: str, cache, lock) -> Dict:
    """Fetch ``timeframe`` data with caching and return :func:`build_snap`."""

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
    return build_snap(df_tf)


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


def build_15m(df: pd.DataFrame, limit: int = 20, nd: int = 5) -> Dict:
    """Build the detailed 15m payload with indicators and OHLCV."""

    data = add_indicators(df)
    if limit <= 1:
        # ``build_snap`` calls ``add_indicators`` internally so we can pass the
        # enriched ``data`` without harm.
        return build_snap(data)

    tail = data.tail(limit)
    ohlcv = [
        compact([r.open, r.high, r.low, r.close], nd) + [human_num(r.volume)]
        for _, r in tail.iterrows()
    ]
    swing_high = rfloat(data["high"].tail(limit).max(), nd)
    swing_low = rfloat(data["low"].tail(limit).min(), nd)
    key = {
        "prev_close": rfloat(data.close.iloc[-2], nd) if len(data) >= 2 else None,
        "last_close": rfloat(data.close.iloc[-1], nd),
        "swing_high": swing_high,
        "swing_low": swing_low,
    }
    sr_levels = [rfloat(lvl, nd) for lvl in detect_sr_levels(data, lookback=5)]
    ind = {
        "ema20": compact(data["ema20"].tail(limit).tolist(), nd),
        "ema50": compact(data["ema50"].tail(limit).tolist(), nd),
        "ema99": compact(data["ema99"].tail(limit).tolist(), nd),
        "ema200": compact(data["ema200"].tail(limit).tolist(), nd),
        "rsi14": compact(data["rsi14"].tail(limit).tolist(), nd),
        "macd": compact(data["macd"].tail(limit).tolist(), nd),
        "macd_sig": compact(data["macd_sig"].tail(limit).tolist(), nd),
        "macd_hist": compact(data["macd_hist"].tail(limit).tolist(), nd),
        "atr14": compact(data["atr14"].tail(limit).tolist(), nd),
        "vol_spike": compact(data["vol_spike"].tail(limit).tolist(), nd),
    }
    return {"ohlcv": ohlcv, "ind": ind, "key": key, "sr_levels": sr_levels}


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

    with LOCK_M15:
        if symbol not in CACHE_M15:
            CACHE_M15[symbol] = fetch_ohlcv_df(exchange, symbol, "15m", 300)
        else:
            last_ts = int(CACHE_M15[symbol].index[-1].timestamp() * 1000)
            new = fetch_ohlcv_df(exchange, symbol, "15m", 300, since=last_ts)
            if not new.empty:
                df = pd.concat([CACHE_M15[symbol], new]).sort_index()
                CACHE_M15[symbol] = df[~df.index.duplicated(keep="last")].tail(300)
        m15 = CACHE_M15[symbol]
    payload = {
        "pair": norm_pair_symbol(symbol),
        "m15": build_15m(m15),
        "h1": _snap_with_cache(exchange, symbol, "1h", CACHE_H1, LOCK_H1),
        "h4": _snap_with_cache(exchange, symbol, "4h", CACHE_H4, LOCK_H4),
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
    mc_ttl: float = 3600,
) -> Dict:
    """Build the payload used by the orchestrator with time and bias info."""

    exclude_pairs = exclude_pairs or set()
    positions = positions_snapshot(exchange)
    pos_pairs = {p.get("pair") for p in positions}
    volumes = cache_top_by_qv(exchange, limit=limit)
    mc_list = top_by_market_cap(max(limit, 200), ttl=mc_ttl)
    mc_bases = set(mc_list)
    markets = load_usdtm(exchange)
    base_map: Dict[str, str] = {}
    for sym, m in markets.items():
        b = m.get("base") or ""
        base_map[strip_numeric_prefix(b)] = sym

    symbols: List[str] = []
    used_bases: Set[str] = set()

    for s in volumes:
        pair = norm_pair_symbol(s)
        base = strip_numeric_prefix(pair[:-4])
        if (
            pair in exclude_pairs
            or pair in pos_pairs
            or base not in mc_bases
            or base in used_bases
        ):
            continue
        symbols.append(s)
        used_bases.add(base)
        if len(symbols) >= limit:
            break

    for base in mc_list:
        if len(symbols) >= limit:
            break
        if base in used_bases:
            continue
        sym = base_map.get(base)
        if sym is None:
            continue
        pair = norm_pair_symbol(sym)
        if pair in exclude_pairs or pair in pos_pairs:
            continue
        symbols.append(sym)
        used_bases.add(base)
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
    eth_symbol = pair_to_symbol("ETHUSDT")
    eth = {
        "h1": _snap_with_cache(exchange, eth_symbol, "1h", CACHE_H1, LOCK_H1),
        "h4": _snap_with_cache(exchange, eth_symbol, "4h", CACHE_H4, LOCK_H4),
    }
    return drop_empty(
        {
            "time": time_payload(),
            "eth": drop_empty(eth),
            "coins": [drop_empty(c) for c in coins],
        }
    )
