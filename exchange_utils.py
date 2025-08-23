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
            "spread": rfloat(spread, 6),
            "bid_vol": rfloat(bid_vol, 6),
            "ask_vol": rfloat(ask_vol, 6),
            "imbalance": rfloat(imb, 6),
        }
    except Exception:
        return {}


def funding_snapshot(exchange: ccxt.Exchange, symbol: str) -> Dict:
    """Return the current funding rate and prediction for ``symbol``."""

    try:
        fr = exchange.fetch_funding_rate(symbol)
        info = fr.get("info") or {}
        rate = fr.get("fundingRate")
        predicted = info.get("predictedFundingRate")
        next_ts = fr.get("nextFundingTime") or info.get("nextFundingTime")
        return {
            "rate": rfloat(rate, 6),
            "predicted_rate": rfloat(predicted, 6),
            "next_ts": int(next_ts) if next_ts else None,
        }
    except Exception:
        return {}


def open_interest_snapshot(exchange: ccxt.Exchange, symbol: str) -> Dict:
    """Return the latest open interest for ``symbol``."""

    try:
        oi = exchange.fetch_open_interest(symbol)
        amount = (
            oi.get("openInterestAmount")
            or oi.get("amount")
            or oi.get("openInterest")
        )
        value = oi.get("openInterestValue") or oi.get("value")
        out: Dict[str, float] = {}
        if amount is not None:
            out["amount"] = rfloat(amount, 6)
        if value is not None:
            out["value"] = rfloat(value, 6)
        return out
    except Exception:
        return {}


def cvd_snapshot(exchange: ccxt.Exchange, symbol: str, limit: int = 500) -> Dict:
    """Return a simple cumulative volume delta over recent trades."""

    try:
        trades = exchange.fetch_trades(symbol, limit=limit)
        cvd = 0.0
        for t in trades:
            side = t.get("side")
            amt = float(t.get("amount") or 0)
            if side == "buy":
                cvd += amt
            elif side == "sell":
                cvd -= amt
        return {"cvd": rfloat(cvd, 6)}
    except Exception:
        return {}


def liquidation_snapshot(
    exchange: ccxt.Exchange, symbol: str, limit: int = 50
) -> Dict:
    """Return recent liquidation statistics for ``symbol``."""

    try:
        rows = exchange.fetch_liquidations(symbol, limit=limit)
        long_amt = 0.0
        short_amt = 0.0
        for r in rows:
            amt = float(r.get("amount") or 0)
            side = r.get("side", "").lower()
            if side == "long":
                long_amt += amt
            elif side == "short":
                short_amt += amt
        return {
            "long_liq": rfloat(long_amt, 6),
            "short_liq": rfloat(short_amt, 6),
        }
    except Exception:
        return {}

