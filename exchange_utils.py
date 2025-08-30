"""Helpers for interacting with the Binance futures exchange."""

from __future__ import annotations

import os
import logging
from typing import Dict, List

import ccxt
import pandas as pd

from env_utils import drop_empty, now_ms, rfloat

# Symbols to skip when building the market universe
BLACKLIST_BASES = {"BTC", "BNB"}


logger = logging.getLogger(__name__)


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


def top_by_24h_change(exchange: ccxt.Exchange, limit: int = 20) -> List[str]:
    """Return ``limit`` symbols sorted by absolute 24h percentage change."""

    markets = load_usdtm(exchange)
    symbols = list(markets.keys())
    try:
        tickers = exchange.fetch_tickers()
        scored = []
        for sym in symbols:
            pct = (tickers.get(sym) or {}).get("percentage") or 0
            scored.append((sym, abs(float(pct))))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored[:limit]]
    except Exception:
        return symbols[:limit]


def fetch_ohlcv_df(exchange: ccxt.Exchange, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Fetch OHLCV data and return as a tidy :class:`~pandas.DataFrame`."""

    raw = exchange.fetch_ohlcv(symbol, timeframe, since=None, limit=limit)
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
        bid_vol_1_5 = sum(float(p) * float(a) for p, a in bids[:5])
        ask_vol_1_5 = sum(float(p) * float(a) for p, a in asks[:5])
        den = (bid_vol_1_5 + ask_vol_1_5) or 1.0
        imb = (bid_vol_1_5 - ask_vol_1_5) / den
        return {
            "spread": rfloat(spread, 6),
            "bid_vol_1_5": rfloat(bid_vol_1_5, 6),
            "ask_vol_1_5": rfloat(ask_vol_1_5, 6),
            "imb": rfloat(imb, 6),
        }
    except Exception:
        return {}


def funding_snapshot(exchange: ccxt.Exchange, symbol: str) -> Dict:
    """Return funding rate and minutes until the next funding event."""

    try:
        fr = exchange.fetch_funding_rate(symbol)
    except Exception:
        return {}
    rate = rfloat(fr.get("fundingRate"))
    next_ts = fr.get("nextFundingTime")
    mins = None
    if isinstance(next_ts, (int, float)):
        mins = max(0, int((float(next_ts) - now_ms()) / 60000))
    return drop_empty({"rate": rate, "next_mins": mins})


def open_interest_snapshot(exchange: ccxt.Exchange, symbol: str) -> Dict:
    """Return current open interest and optional 24h change."""

    method = getattr(exchange, "fetch_open_interest_history", None)
    if not callable(method):
        return {}
    try:
        records = method(symbol, "1h", None, 25)
    except Exception:
        return {}
    if not records:
        return {}
    last = records[-1]
    oi = rfloat(last.get("openInterest"))
    change = None
    if len(records) > 24:
        first = records[0]
        try:
            change = rfloat(float(last.get("openInterest")) - float(first.get("openInterest")))
        except Exception:
            change = None
    return drop_empty({"oi": oi, "oi_chg_24h": change})


def long_short_ratio(exchange: ccxt.Exchange, symbol: str) -> Dict:
    """Return the global long/short account ratio if available."""

    method = getattr(exchange, "fapiPublic_get_globalLongShortAccountRatio", None)
    if not callable(method):
        return {}
    try:
        market = exchange.market(symbol)
        data = method({"symbol": market.get("id"), "period": "5m", "limit": 1})
        item = data[-1] if data else None
    except Exception:
        return {}
    if not item:
        return {}
    return drop_empty({"lsr": rfloat(item.get("longShortRatio"))})


def price_snapshot(exchange: ccxt.Exchange, symbol: str) -> Dict:
    """Return mark and index prices when provided by the exchange."""

    try:
        ticker = exchange.fetch_ticker(symbol)
    except Exception:
        return {}
    info = ticker.get("info") or {}
    mark = rfloat(info.get("markPrice") or ticker.get("mark"))
    index = rfloat(info.get("indexPrice") or ticker.get("index"))
    return drop_empty({"mark": mark, "index": index})


def market_snapshot(exchange: ccxt.Exchange, symbol: str) -> Dict:
    """Return contract specification details for ``symbol``."""

    try:
        m = exchange.market(symbol)
    except Exception:
        return {}
    tick_size = rfloat((m.get("precision") or {}).get("price"))
    step_size = rfloat((m.get("precision") or {}).get("amount"))
    min_qty = rfloat(((m.get("limits") or {}).get("amount") or {}).get("min"))
    max_lev = rfloat(((m.get("limits") or {}).get("leverage") or {}).get("max") or (m.get("info") or {}).get("maxLeverage"))
    maker = rfloat(m.get("maker"))
    taker = rfloat(m.get("taker"))
    return drop_empty(
        {
            "tick_size": tick_size,
            "step_size": step_size,
            "min_qty": min_qty,
            "max_leverage": max_lev,
            "maker_fee": maker,
            "taker_fee": taker,
        }
    )


def position_snapshot(exchange: ccxt.Exchange, symbol: str) -> Dict:
    """Return current position state for ``symbol`` if any."""

    try:
        positions = exchange.fetch_positions([symbol])
    except Exception:
        try:
            positions = exchange.fetch_positions()
        except Exception:
            return {}
    for p in positions or []:
        sym = p.get("symbol") or (p.get("info") or {}).get("symbol")
        if sym != symbol:
            continue
        amt = (
            p.get("contracts")
            or p.get("amount")
            or (p.get("info") or {}).get("positionAmt")
            or 0
        )
        try:
            amt = float(amt)
        except Exception:
            amt = 0.0
        if abs(amt) <= 0:
            return {}
        side = "long" if amt > 0 else "short"
        qty = rfloat(abs(amt))
        avg = rfloat(p.get("entryPrice") or (p.get("info") or {}).get("entryPrice"))
        upl = rfloat(
            p.get("unrealizedPnl") or (p.get("info") or {}).get("unRealizedProfit")
        )
        return drop_empty({"in": True, "side": side, "qty": qty, "avg": avg, "unreal_pnl": upl})
    return {}


def liquidation_snapshot(exchange: ccxt.Exchange, symbol: str, limit: int = 50) -> Dict:
    """Return 24h liquidation statistics or an empty dict if unsupported."""

    if not getattr(exchange, "has", {}).get("fetchLiquidations"):
        return {}
    try:
        records = exchange.fetch_liquidations(symbol, limit=limit)
    except Exception as exc:  # pragma: no cover - network errors
        logger.warning("liquidation_snapshot error for %s: %s", symbol, exc)
        return {}

    buy_vol = 0.0
    sell_vol = 0.0
    for r in records or []:
        side = (r.get("side") or "").lower()
        amount = float(r.get("amount") or 0.0)
        price = float(r.get("price") or 0.0)
        vol = amount * price
        if side == "buy":
            buy_vol += vol
        elif side == "sell":
            sell_vol += vol

    den = (buy_vol + sell_vol) or 1.0
    return {
        "liq_long_usd": rfloat(buy_vol, 6),
        "liq_short_usd": rfloat(sell_vol, 6),
        "imbalance": rfloat((buy_vol - sell_vol) / den, 6),
    }

