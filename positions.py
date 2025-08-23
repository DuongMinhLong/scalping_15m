"""Helpers related to open futures positions."""

from __future__ import annotations

import math
from typing import Dict, Set, Tuple


def _norm_pair_from_symbol(symbol: str) -> str:
    """Convert CCXT symbol into ``BASEQUOTE`` pair format."""

    if not symbol:
        return ""
    symbol = symbol.split(":")[0]
    return symbol.replace("/", "").upper()


def get_open_positions_with_risk(exchange) -> Tuple[Set[str], Dict[str, bool]]:
    """Return open position pairs and whether each is risk-free.

    A position is considered ``risk_free`` when there is an associated
    stop-loss order whose price is effectively equal to the entry price.
    """

    pairs: Set[str] = set()
    risk_free: Dict[str, bool] = {}
    pos_entry: Dict[str, float] = {}

    try:
        positions = exchange.fetch_positions()
    except Exception:
        positions = []

    for p in positions or []:
        sym = p.get("symbol") or (p.get("info") or {}).get("symbol")
        pair = _norm_pair_from_symbol(sym)
        amt = p.get("contracts")
        if amt is None:
            amt = p.get("amount")
        if amt is None:
            amt = (p.get("info") or {}).get("positionAmt", 0)
        try:
            if abs(float(amt)) <= 0:
                continue
        except Exception:
            continue
        pairs.add(pair)
        try:
            entry = float(
                p.get("entryPrice")
                or (p.get("info") or {}).get("entryPrice")
                or 0.0
            )
        except Exception:
            entry = 0.0
        pos_entry[pair] = entry
        risk_free[pair] = False

    try:
        orders = exchange.fetch_open_orders()
    except Exception:
        orders = []

    stop_map: Dict[str, float] = {}
    for o in orders or []:
        sym = o.get("symbol") or (o.get("info") or {}).get("symbol")
        pair = _norm_pair_from_symbol(sym)
        typ = (o.get("type") or "").lower()
        if "stop" not in typ:
            continue
        price = o.get("stopPrice")
        if price is None:
            price = o.get("price")
        try:
            stop_map[pair] = float(price)
        except Exception:
            continue

    for pair in pairs:
        entry = pos_entry.get(pair)
        stop = stop_map.get(pair)
        if entry is None or stop is None:
            continue
        if math.isclose(float(entry), float(stop), rel_tol=1e-9, abs_tol=1e-9):
            risk_free[pair] = True

    return pairs, risk_free


def get_open_position_pairs(exchange) -> Set[str]:
    """Return a set of pairs that currently have an open position."""

    pairs, _ = get_open_positions_with_risk(exchange)
    return pairs

