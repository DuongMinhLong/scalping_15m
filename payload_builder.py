"""Payload construction utilities for 15m scalping."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from threading import Lock
from typing import Dict, List, Set

import pandas as pd

from env_utils import compact, drop_empty, human_num, rfloat
from exchange_utils import fetch_ohlcv_df, load_usdtm, top_by_qv, top_by_market_cap
from indicators import add_indicators, trend_lbl
from positions import positions_snapshot

logger = logging.getLogger(__name__)

# Cache for 15m OHLCV data
CACHE_M15: Dict[str, pd.DataFrame] = {}
LOCK_M15 = Lock()


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


def build_15m(df: pd.DataFrame) -> Dict:
    """Build the detailed 15m payload with indicators and OHLCV."""

    data = add_indicators(df)
    tail20 = data.tail(20)
    ohlcv20 = [
        compact([r.open, r.high, r.low, r.close]) + [human_num(r.volume)]
        for _, r in tail20.iterrows()
    ]
    ind = {
        "ema20": compact(data["ema20"].tail(20).tolist()),
        "ema50": compact(data["ema50"].tail(20).tolist()),
        "ema200": compact(data["ema200"].tail(20).tolist()),
        "rsi14": compact(data["rsi14"].tail(20).tolist()),
        "macd": compact(data["macd"].tail(20).tolist()),
    }
    return {"ohlcv": ohlcv20, "ind": ind}


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
    payload = {"pair": norm_pair_symbol(symbol), "m15": build_15m(m15)}
    return drop_empty(payload)


def build_payload(exchange, limit: int = 10, exclude_pairs: Set[str] | None = None) -> Dict:
    """Build the payload used by the orchestrator (15m only)."""

    exclude_pairs = exclude_pairs or set()
    positions = positions_snapshot(exchange)
    pos_pairs = {p.get("pair") for p in positions}
    symbols_raw = top_by_qv(exchange, limit * 2)
    mc_list = top_by_market_cap(max(limit, 30))
    mc_bases = set(mc_list)
    symbols: List[str] = []
    used_bases: Set[str] = set()
    for s in symbols_raw:
        pair = norm_pair_symbol(s)
        base = pair[:-4]
        norm_base = strip_numeric_prefix(base)
        if pair in exclude_pairs or pair in pos_pairs or norm_base not in mc_bases:
            continue
        symbols.append(s)
        used_bases.add(norm_base)
        if len(symbols) >= limit:
            break
    if len(symbols) < limit:
        markets = load_usdtm(exchange)
        base_map: Dict[str, str] = {}
        for sym, m in markets.items():
            b = m.get("base") or ""
            base_map[strip_numeric_prefix(b)] = sym
        for base in mc_list:
            if len(symbols) >= limit:
                break
            if base in used_bases:
                continue
            sym = base_map.get(base, f"{base}/USDT:USDT")
            if sym not in markets:
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
    return {"coins": [drop_empty(c) for c in coins]}
