"""Helpers for interacting with the Binance futures exchange."""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List
import logging

import ccxt
import pandas as pd
import requests

from env_utils import rfloat


logger = logging.getLogger(__name__)

# Stablecoins that should not be traded
STABLE_BASES = {
    "USDT",
    "USDC",
    "BUSD",
    "TUSD",
    "FDUSD",
    "USDP",
    "SUSD",
    "USTC",
    "DAI",
}

# Symbols to skip when building the market universe
BLACKLIST_BASES = {"BTC", "BNB"} | STABLE_BASES


# Cache for CoinGecko market cap results
_MCAP_CACHE: Dict[str, object] = {"timestamp": 0.0, "data": []}


def make_exchange() -> ccxt.Exchange:
    """Create a Binance futures client using API keys from the environment."""
    logger.info("Initializing Binance futures exchange client")
    exchange = ccxt.binance(
        {"enableRateLimit": True, "options": {"defaultType": "future"}}
    )
    api_key, secret = os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET")
    if api_key and secret:
        exchange.apiKey, exchange.secret = api_key, secret
    return exchange


def load_usdtm(exchange: ccxt.Exchange) -> Dict[str, Dict]:
    """Return all active USDT-margined futures markets excluding stablecoins and other blacklisted bases."""

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
    logger.info("Loaded %d USDT-margined markets", len(out))
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
    except Exception as e:
        logger.warning("top_by_qv error: %s", e)
        return symbols[:limit]


def cache_top_by_qv(
    exchange: ccxt.Exchange,
    limit: int = 100,
    *,
    ttl: float = 3600,
    path: str = "cache/top_volume.json",
) -> List[str]:
    """Return top symbols by quote volume using a JSON cache.

    The cache stores a list of objects containing the original ``symbol`` and a
    normalised ``base`` (numeric prefixes removed) so that tokens like
    ``1000PEPE`` are not duplicated when refreshed.
    """

    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or []
            return [item.get("symbol") for item in data][:limit]
    except Exception as e:  # pragma: no cover - IO failures
        logger.warning("cache_top_by_qv read error: %s", e)

    markets = load_usdtm(exchange)
    try:
        tickers = exchange.fetch_tickers()
    except Exception as e:  # pragma: no cover - network failures
        logger.warning("cache_top_by_qv fetch error: %s", e)
        return list(markets.keys())[:limit]

    try:
        from payload_builder import strip_numeric_prefix
    except Exception:  # pragma: no cover - circular import
        def strip_numeric_prefix(s: str) -> str:
            return s

    scored: Dict[str, Dict] = {}
    for sym, m in markets.items():
        qv = (tickers.get(sym) or {}).get("quoteVolume") or 0
        base = m.get("base") or ""
        norm = strip_numeric_prefix(base)
        info = scored.get(norm)
        if not info or float(qv) > info["qv"]:
            scored[norm] = {"symbol": sym, "qv": float(qv), "base": norm}

    top = sorted(scored.values(), key=lambda x: x["qv"], reverse=True)[:limit]

    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(top, fh)
    except Exception as e:  # pragma: no cover - IO failures
        logger.warning("cache_top_by_qv write error: %s", e)

    return [item["symbol"] for item in top]


def top_gainers(exchange: ccxt.Exchange, limit: int = 20) -> List[str]:
    """Return symbols sorted by 24h percentage change."""

    markets = load_usdtm(exchange)
    try:
        tickers = exchange.fetch_tickers()
    except Exception as e:  # pragma: no cover - network failures
        logger.warning("top_gainers error: %s", e)
        return []

    try:
        from payload_builder import strip_numeric_prefix
    except Exception:  # pragma: no cover - circular import
        def strip_numeric_prefix(s: str) -> str:
            return s

    scored = []
    for sym, m in markets.items():
        pct = (tickers.get(sym) or {}).get("percentage")
        if pct is None:
            pct = (tickers.get(sym) or {}).get("info", {}).get("priceChangePercent")
        try:
            pct_val = float(pct)
        except Exception:
            continue
        base = strip_numeric_prefix(m.get("base") or "")
        if base in BLACKLIST_BASES:
            continue
        scored.append((sym, pct_val))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in scored[:limit]]


def top_by_market_cap(limit: int = 30, *, ttl: float = 3600) -> List[str]:
    """Return top coin symbols sorted by market cap using the CoinGecko API.

    Results are cached in-memory for ``ttl`` seconds to avoid hitting the
    CoinGecko API on every call.
    """

    now = time.time()
    cached = _MCAP_CACHE["data"]
    if cached and now - _MCAP_CACHE["timestamp"] < ttl and len(cached) >= limit:
        return cached[:limit]

    per_page = min(250, max(limit * 2, limit + len(BLACKLIST_BASES)))
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": per_page,
                "page": 1,
                "sparkline": "false",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json() or []
        symbols = [
            str(item.get("symbol", "")).upper()
            for item in data
            if str(item.get("symbol", "")).upper() not in BLACKLIST_BASES
        ]
        _MCAP_CACHE["timestamp"] = now
        _MCAP_CACHE["data"] = symbols
        return symbols[:limit]
    except Exception as e:
        logger.warning("top_by_market_cap error: %s", e)
        return cached[:limit] if cached else []


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
    except Exception as e:
        logger.warning("funding_snapshot error for %s: %s", symbol, e)
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
    except Exception as e:
        logger.warning("open_interest_snapshot error for %s: %s", symbol, e)
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
    except Exception as e:
        logger.warning("cvd_snapshot error for %s: %s", symbol, e)
        return {}


def liquidation_snapshot(
    exchange: ccxt.Exchange, symbol: str, limit: int = 50
) -> Dict:
    """Return recent liquidation statistics for ``symbol``."""
    # ``fetch_liquidations`` is not implemented for all exchanges.  The
    # Binance client used by this project, for example, does not support it
    # which resulted in noisy ``NotSupported`` warnings.  Guard against that
    # here so we simply return an empty payload when the capability is
    # missing.
    if not getattr(exchange, "has", {}).get("fetchLiquidations"):
        return {}

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
    except Exception as e:
        logger.warning("liquidation_snapshot error for %s: %s", symbol, e)
        return {}

