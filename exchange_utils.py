"""Helpers for interacting with the OANDA forex exchange."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

import ccxt
import pandas as pd
import requests
from datetime import datetime

from env_utils import rfloat

logger = logging.getLogger(__name__)


class OandaREST:
    """Lightweight OANDA client used when ccxt lacks native support."""

    def __init__(self, api_key: str | None = None, account_id: str | None = None):
        self.apiKey = api_key
        self.uid = account_id
        self.session = requests.Session()
        self.base_url = os.getenv(
            "OANDA_API_URL", "https://api-fxpractice.oanda.com/v3"
        )
        self.session.headers.update({"Content-Type": "application/json"})
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        # minimal markets info for symbol resolution and qty_step
        self.markets = {
            "XAU/USD": {
                "id": "XAU_USD",
                "symbol": "XAU/USD",
                "base": "XAU",
                "quote": "USD",
                "precision": {"amount": 0.01, "price": 0.01},
                "limits": {"amount": {"min": 0.01, "step": 0.01}},
            }
        }
        self.options: Dict[str, Any] = {}

    # ---- helpers -----------------------------------------------------
    def _instrument(self, symbol: str) -> str:
        return symbol.replace("/", "_")

    # ---- public ccxt-style methods ----------------------------------
    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None = None, limit: int = 100
    ):
        tf_map = {
            "1m": "M1",
            "5m": "M5",
            "15m": "M15",
            "30m": "M30",
            "1h": "H1",
            "4h": "H4",
            "1d": "D",
        }
        params = {"granularity": tf_map.get(timeframe, "M1"), "count": limit}
        if since is not None:
            iso = datetime.utcfromtimestamp(since / 1000).isoformat("T") + "Z"
            params["from"] = iso
        url = f"{self.base_url}/instruments/{self._instrument(symbol)}/candles"
        r = self.session.get(url, params=params)
        r.raise_for_status()
        candles = r.json().get("candles", [])
        out = []
        for c in candles:
            ts = int(datetime.fromisoformat(c["time"].replace("Z", "+00:00")).timestamp() * 1000)
            mid = c.get("mid") or {}
            out.append(
                [
                    ts,
                    float(mid.get("o", 0)),
                    float(mid.get("h", 0)),
                    float(mid.get("l", 0)),
                    float(mid.get("c", 0)),
                    float(c.get("volume", 0)),
                ]
            )
        return out

    def fetch_order_book(self, symbol: str, limit: int = 10):
        url = f"{self.base_url}/instruments/{self._instrument(symbol)}/orderBook"
        r = self.session.get(url)
        r.raise_for_status()
        data = r.json()
        buckets = data.get("buckets", [])
        # Use long/short percentage as proxy volumes
        bids = []
        asks = []
        for b in buckets[:limit]:
            price = float(b.get("price"))
            bids.append([price, float(b.get("longCountPercent", 0))])
            asks.append([price, float(b.get("shortCountPercent", 0))])
        return {"bids": bids, "asks": asks}

    def fetch_open_orders(self, symbol: str | None = None):
        url = f"{self.base_url}/accounts/{self.uid}/orders"
        params = {"state": "PENDING"}
        if symbol:
            params["instrument"] = self._instrument(symbol)
        r = self.session.get(url, params=params)
        r.raise_for_status()
        orders = r.json().get("orders", [])
        return [{"id": o.get("id"), "symbol": symbol} for o in orders]

    def cancel_order(self, order_id: str, symbol: str | None = None):
        url = f"{self.base_url}/accounts/{self.uid}/orders/{order_id}/cancel"
        r = self.session.put(url)
        r.raise_for_status()
        return r.json()

    def create_order(
        self,
        symbol: str,
        typ: str,
        side: str,
        qty: float,
        price: float | None,
        params: Dict | None = None,
    ):
        url = f"{self.base_url}/accounts/{self.uid}/orders"
        data: Dict[str, Any] = {
            "order": {
                "instrument": self._instrument(symbol),
                "units": str(qty if side.lower() == "buy" else -qty),
                "type": "MARKET" if typ.lower() == "market" else "LIMIT",
                "timeInForce": "FOK" if typ.lower() == "market" else "GTC",
            }
        }
        if price is not None:
            data["order"]["price"] = str(price)
        if params:
            data["order"].update(params)
        r = self.session.post(url, json=data)
        r.raise_for_status()
        return r.json().get("orderCreateTransaction", {"id": None})

    def fetch_order(self, order_id: str, symbol: str | None = None):
        url = f"{self.base_url}/accounts/{self.uid}/orders/{order_id}"
        r = self.session.get(url)
        r.raise_for_status()
        return r.json().get("order", {})

    def fetch_positions(self):
        url = f"{self.base_url}/accounts/{self.uid}/positions"
        r = self.session.get(url)
        r.raise_for_status()
        positions = []
        for p in r.json().get("positions", []):
            inst = p.get("instrument", "")
            sym = inst.replace("_", "/")
            long_units = float(p.get("long", {}).get("units", 0))
            short_units = float(p.get("short", {}).get("units", 0))
            net = long_units + short_units
            entry = float(p.get("long", {}).get("averagePrice") or p.get("short", {}).get("averagePrice") or 0)
            positions.append({"symbol": sym, "contracts": net, "entryPrice": entry})
        return positions

    def fetch_balance(self):
        url = f"{self.base_url}/accounts/{self.uid}/summary"
        r = self.session.get(url)
        r.raise_for_status()
        bal = float(r.json().get("account", {}).get("balance", 0))
        return {"total": {"USD": bal}}

    def fetch_ticker(self, symbol: str):
        url = f"{self.base_url}/accounts/{self.uid}/pricing"
        params = {"instruments": self._instrument(symbol)}
        r = self.session.get(url, params=params)
        r.raise_for_status()
        prices = r.json().get("prices", [{}])[0]
        bid = float(prices.get("bids", [{}])[0].get("price", 0))
        ask = float(prices.get("asks", [{}])[0].get("price", 0))
        last = (bid + ask) / 2 if bid and ask else 0
        return {"bid": bid, "ask": ask, "last": last}

    def market(self, symbol: str):
        return self.markets.get(symbol, {})


def make_exchange() -> Any:
    """Create an OANDA client using API keys from the environment.

    Uses ``ccxt.oanda`` when available; otherwise falls back to a minimal
    REST implementation so the rest of the application can run in
    environments where ccxt ships without OANDA support.
    """

    logger.info("Initializing OANDA exchange client")
    api_key = os.getenv("OANDA_API_KEY")
    account_id = os.getenv("OANDA_ACCOUNT_ID")
    api_url = os.getenv("OANDA_API_URL")
    if not api_key or "your_oanda_api_key" in api_key.lower():
        raise RuntimeError("OANDA_API_KEY is required; set it in your environment or .env file")
    if not account_id or "your_oanda_account_id" in account_id.lower():
        raise RuntimeError(
            "OANDA_ACCOUNT_ID is required; set it in your environment or .env file"
        )
    oanda_cls = getattr(ccxt, "oanda", None)
    if oanda_cls is not None:
        exchange = oanda_cls({"enableRateLimit": True})
        if api_url:
            exchange.urls["api"] = api_url
        exchange.apiKey = api_key
        exchange.uid = account_id
        return exchange

    logger.warning("ccxt installation missing OANDA; using REST fallback")
    return OandaREST(api_key=api_key, account_id=account_id)


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
