"""Helpers related to open futures positions."""

from __future__ import annotations

from typing import Set


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

