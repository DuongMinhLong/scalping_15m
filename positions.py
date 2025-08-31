"""Helpers related to open futures positions."""

from __future__ import annotations

from typing import Dict, List, Set
import logging

from env_utils import drop_empty, rfloat


logger = logging.getLogger(__name__)


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
            except Exception as e:
                logger.warning("get_open_position_pairs amt parse error: %s", e)
                continue
    except Exception as e:
        logger.warning("get_open_position_pairs fetch_positions error: %s", e)
    return out


def positions_snapshot(exchange) -> List[Dict]:
    """Return snapshot of open positions with entry, SL, TP and PnL."""

    out: List[Dict] = []
    try:
        positions = exchange.fetch_positions()
    except Exception as e:
        logger.warning("positions_snapshot fetch_positions error: %s", e)
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
        except Exception as e:
            logger.warning("positions_snapshot parse error for %s: %s", pair, e)
            continue
        if amt_val == 0:
            continue
        side = "buy" if amt_val > 0 else "sell"
        qty = abs(amt_val)
        sl = None
        tp1 = None
        tp2 = None
        tp3 = None
        pnl = p.get("unrealizedPnl") or (p.get("info") or {}).get(
            "unrealizedProfit"
        )
        pnl = rfloat(pnl)
        try:
            orders = exchange.fetch_open_orders(sym)
        except Exception as e:
            logger.warning("positions_snapshot fetch_open_orders error for %s: %s", sym, e)
            orders = []
        stop_orders = [
            o
            for o in orders
            if (
                o.get("reduceOnly")
                or (o.get("info") or {}).get("closePosition")
            )
            and (
                o.get("stopPrice")
                or (o.get("info") or {}).get("stopPrice")
                or o.get("price")
            )
        ]
        try:
            prices = [
                float(
                    o.get("stopPrice")
                    or (o.get("info") or {}).get("stopPrice")
                    or o.get("price")
                    or 0
                )
                for o in stop_orders
            ]
        except Exception as e:
            logger.warning("positions_snapshot price parse error for %s: %s", sym, e)
            prices = []
        if prices:
            tp_prices = []
            sl_prices = []
            for price in prices:
                if side == "buy":
                    if price < entry_price:
                        sl_prices.append(price)
                    elif price > entry_price:
                        tp_prices.append(price)
                else:
                    if price > entry_price:
                        sl_prices.append(price)
                    elif price < entry_price:
                        tp_prices.append(price)
            if sl_prices:
                sl = rfloat(min(sl_prices) if side == "buy" else max(sl_prices))
            if tp_prices:
                tp_sorted = sorted(tp_prices) if side == "buy" else sorted(tp_prices, reverse=True)
                tp1 = rfloat(tp_sorted[0])
                if len(tp_sorted) > 1:
                    tp2 = rfloat(tp_sorted[1])
                if len(tp_sorted) > 2:
                    tp3 = rfloat(tp_sorted[2])
        out.append(
            drop_empty(
                {
                    "pair": pair,
                    "side": side,
                    "entry": rfloat(entry_price),
                    "qty": rfloat(qty),
                    "sl": sl,
                    "tp": tp1,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "pnl": pnl,
                }
            )
        )
    return out

