"""Helpers for interacting with the Binance futures exchange."""

from __future__ import annotations

import os
from typing import Dict, List

import ccxt
import pandas as pd

from env_utils import rfloat

# Symbols to skip when building the market universe
BLACKLIST_BASES = {"BTC", "BNB"}


def make_exchange() -> ccxt.Exchange:
    """Create a Binance futures client using API keys from the environment."""

    exchange = ccxt.binance(
        {"enableRateLimit": True, "options": {"defaultType": "future"}}
    )
    api_key, secret = os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET")
    if api_key and secret:
        exchange.apiKey, exchange.secret = api_key, secret
    return exchange


def load_usdtm(exchange: ccxt.Exchange) -> Dict[str, Dict]:
    """Return all active USDT-margined futures markets except blacklisted bases."""

    markets = exchange.load_markets()
    out: Dict[str, Dict] = {}
    for m in markets.values():
        if (
            m.get("linear")
            and m.get("swap")
            and m.get("quote") == "USDT"
            and m.get("active")
        ):
            base = m.get("base", "")
            if base not in BLACKLIST_BASES:
                out[m["symbol"]] = m
    return out


def top_by_qv(exchange: ccxt.Exchange, limit: int = 20) -> List[str]:
    """Return ``limit`` symbols sorted by quote volume."""

    markets = load_usdtm(exchange)
    symbols = list(markets.keys())
    try:
        tickers = exchange.fetch_tickers()
        scored = []
        for sym in symbols:
            qv = (tickers.get(sym) or {}).get("quoteVolume") or 0
            scored.append((sym, float(qv)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored[:limit]]
    except Exception:
        return symbols[:limit]


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


def orderbook_snapshot(exchange: ccxt.Exchange, symbol: str, depth: int = 20) -> Dict:
    """Return a small snapshot of the order book with basic statistics.

    The default ``depth`` has been increased compared to the original
    scalping version to provide a broader view that suits the slower 1h
    timeframe better.
    """

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
            "spread": rfloat(spread, 6),
            "bid_vol": rfloat(bid_vol, 6),
            "ask_vol": rfloat(ask_vol, 6),
            "imbalance": rfloat(imb, 6),
        }
    except Exception:
        return {}


def funding_rate(exchange: ccxt.Exchange, symbol: str) -> Dict:
    """Return current funding rate and next funding time for ``symbol``.

    The function is intentionally lightweight and returns an empty dictionary
    on any exchange/API error.  The timestamp is expressed in milliseconds.
    """

    try:
        info = exchange.fetch_funding_rate(symbol)
        rate = info.get("fundingRate")
        next_time = info.get("nextFundingTime")
        out: Dict[str, float | int] = {}
        if rate is not None:
            try:
                rate_val = float(rate)
            except Exception:
                rate_val = None
            out["rate"] = rfloat(rate_val, 6)
        if next_time is not None:
            out["next_funding"] = int(next_time)
        return out
    except Exception:
        return {}

