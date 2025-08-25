"""Helpers related to open futures positions."""

from __future__ import annotations

from typing import Dict, List, Set

from env_utils import drop_empty, rfloat


def _norm_pair_from_symbol(symbol: str) -> str:
    """Convert CCXT symbol into ``BASEQUOTE`` pair format."""

    if not symbol:
        return ""
    symbol = symbol.split(":")[0]
    return symbol.replace("/", "").upper()


def get_open_position_pairs(exchange) -> Set[str]:
    """Return a set of pairs that currently have an open position."""

    out: Set[str] = set()
    try:
        positions = exchange.fetch_positions()
        for p in positions or []:
            sym = p.get("symbol") or (p.get("info") or {}).get("symbol")
            pair = _norm_pair_from_symbol(sym)
            amt = p.get("contracts")
            if amt is None:
                amt = p.get("amount")
            if amt is None:
                amt = (p.get("info") or {}).get("positionAmt", 0)
            try:
                if abs(float(amt)) > 0:
                    out.add(pair)
            except Exception:
                continue
    except Exception:
        pass
    return out


def positions_snapshot(exchange) -> List[Dict]:
    """Return snapshot of open positions with entry, SL and TP."""

    out: List[Dict] = []
    try:
        positions = exchange.fetch_positions()
    except Exception:
        return out

    for p in positions or []:
        sym = p.get("symbol") or (p.get("info") or {}).get("symbol")
        pair = _norm_pair_from_symbol(sym)
        amt = p.get("contracts")
        if amt is None:
            amt = p.get("amount")
        if amt is None:
            amt = (p.get("info") or {}).get("positionAmt")
        entry = p.get("entryPrice") or (p.get("info") or {}).get("entryPrice")
        try:
            amt_val = float(amt)
            entry_price = float(entry)
        except Exception:
            continue
        if amt_val == 0:
            continue
        side = "buy" if amt_val > 0 else "sell"
        sl = None
        tp1 = None
        tp2 = None
        tp3 = None
        try:
            orders = exchange.fetch_open_orders(sym)
        except Exception:
            orders = []
        sl_orders = [
            o
            for o in orders
            if (o.get("type") or "").lower() == "stop" and o.get("reduceOnly")
        ]
        tp_orders = [
            o
            for o in orders
            if (o.get("type") or "").lower() == "limit" and o.get("reduceOnly")
        ]
        if sl_orders:
            sl = rfloat(sl_orders[0].get("stopPrice") or sl_orders[0].get("price"))
        prices = [float(o.get("price") or 0) for o in tp_orders]
        prices.sort(reverse=(side == "sell"))
        if len(prices) >= 1:
            tp1 = rfloat(prices[0])
        if len(prices) >= 2:
            tp2 = rfloat(prices[1])
        if len(prices) >= 3:
            tp3 = rfloat(prices[2])
        out.append(
            drop_empty(
                {
                    "pair": pair,
                    "side": side,
                    "entry": rfloat(entry_price),
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                }
            )
        )
    return out

