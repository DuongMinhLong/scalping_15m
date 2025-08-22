"""Parsing helpers and quantity/TP calculations for trades."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from env_utils import rfloat
from openai_client import try_extract_json


def parse_mini_actions(text: str) -> List[Dict[str, Any]]:
    """Parse MINI model output into a structured list of actions."""

    data = try_extract_json(text)
    arr = data.get("coins", []) if isinstance(data, dict) else []
    out: List[Dict[str, Any]] = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        pair = (item.get("pair") or "").upper().replace("/", "")
        if not pair:
            continue
        entry = item.get("entry")
        sl = item.get("sl")
        tp = item.get("tp")
        risk = item.get("risk")
        try:
            entry = float(entry) if entry is not None else None
            sl = float(sl) if sl is not None else None
            tp = float(tp) if tp not in (None, "") else None
            risk = float(risk) if risk not in (None, "") else None
        except Exception:
            continue
        out.append({"pair": pair, "entry": entry, "sl": sl, "tp": tp, "risk": risk})
    return out


def to_ccxt_symbol(pair_no_slash: str) -> str:
    """Convert ``BASEQUOTE`` pair to CCXT ``BASE/QUOTE`` format."""

    base, quote = pair_no_slash[:-4], pair_no_slash[-4:]
    return f"{base}/{quote}"


def qty_step(exchange, ccxt_symbol: str) -> float:
    """Determine the minimal quantity step for ``ccxt_symbol``."""

    try:
        m = exchange.market(ccxt_symbol)
        step = (
            (m.get("limits", {}).get("amount", {}) or {}).get("step")
            or m.get("precision", {}).get("amount")
            or (m.get("limits", {}).get("amount", {}) or {}).get("min")
        )
        return float(step or 0.0001)
    except Exception:
        return 0.0001


def round_step(qty: float, step: float) -> float:
    """Round ``qty`` down to the nearest multiple of ``step``."""

    if step <= 0:
        return qty
    return math.floor(qty / step) * step


def calc_qty(capital: float, risk_frac: float, entry: float, sl: float, step: float) -> float:
    """Calculate order quantity based on risk parameters."""

    dist = abs(entry - sl)
    if dist <= 0 or risk_frac <= 0 or capital <= 0:
        return 0.0
    raw = (capital * risk_frac) / dist
    return round_step(raw, step)


def infer_side(entry: float, sl: float, tp: Optional[float]) -> Optional[str]:
    """Infer order side (buy/sell) from entry, stop-loss and take-profit."""

    try:
        if tp is not None:
            if tp > entry > sl:
                return "buy"
            if tp < entry < sl:
                return "sell"
        else:
            if entry > sl:
                return "buy"
            if entry < sl:
                return "sell"
    except Exception:
        pass
    return None


def enrich_tp_qty(exchange, acts: List[Dict[str, Any]], capital: float) -> List[Dict[str, Any]]:
    """Fill in missing TP with 1R and compute quantity/side for each action."""

    out: List[Dict[str, Any]] = []
    for a in acts:
        entry = a.get("entry")
        sl = a.get("sl")
        tp = a.get("tp")
        risk = a.get("risk")
        if not (isinstance(entry, (int, float)) and isinstance(sl, (int, float))):
            continue
        if not (isinstance(tp, (int, float)) and tp > 0 and tp != entry):
            tp = entry + (entry - sl) if entry > sl else entry - (sl - entry)
            a["tp"] = rfloat(tp, 8)
        rf = float(risk) if isinstance(risk, (int, float)) and risk > 0 else 0.005
        ccxt_sym = to_ccxt_symbol(a["pair"])
        step = qty_step(exchange, ccxt_sym)
        qty = calc_qty(capital, rf, float(entry), float(sl), step)
        a["qty"] = rfloat(qty, 8)
        a["risk"] = rfloat(rf, 6)
        side = infer_side(float(entry), float(sl), float(tp))
        a["side"] = side
        out.append(a)
    return out

