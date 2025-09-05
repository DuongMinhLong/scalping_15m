"""Helpers for interacting with the OANDA forex exchange."""

from __future__ import annotations

import logging
import os
from typing import Dict

import ccxt
import pandas as pd

from env_utils import rfloat

logger = logging.getLogger(__name__)


def make_exchange() -> ccxt.Exchange:
    """Create an OANDA client using API keys from the environment."""
    logger.info("Initializing OANDA exchange client")
    exchange = ccxt.oanda({"enableRateLimit": True})
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    if api_key:
        exchange.apiKey = api_key
    if account_id:
        exchange.uid = account_id
    return exchange


def fetch_ohlcv_df(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    limit: int,
    since: int | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV data and return as a tidy :class:`~pandas.DataFrame`."""

    raw = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df.ts, unit="ms", utc=True)
    return df.set_index("ts").sort_index()


def orderbook_snapshot(exchange: ccxt.Exchange, symbol: str, depth: int = 10) -> Dict:
    """Return a small snapshot of the order book with basic statistics."""

    try:
        ob = exchange.fetch_order_book(symbol, limit=depth)
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        if not bids or not asks:
            return {}
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid = (best_bid + best_ask) / 2.0
        spread = (best_ask - best_bid) / mid if mid > 0 else 0.0
        bid_vol = sum(float(p) * float(a) for p, a in bids[:depth])
        ask_vol = sum(float(p) * float(a) for p, a in asks[:depth])
        den = (bid_vol + ask_vol) or 1.0
        imb = (bid_vol - ask_vol) / den
        return {
            "sp": rfloat(spread, 6),
            "b": rfloat(bid_vol, 6),
            "a": rfloat(ask_vol, 6),
            "im": rfloat(imb, 6),
        }
    except Exception as e:
        logger.warning("orderbook_snapshot error for %s: %s", symbol, e)
        return {}
