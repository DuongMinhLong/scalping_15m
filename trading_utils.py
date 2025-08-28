"""Parsing helpers and quantity/TP calculations for trades."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from env_utils import rfloat
from openai_client import try_extract_json
from typing import Iterable


def parse_mini_actions(text: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse MINI model JSON output into open/close instructions.

    Returns a dict with keys ``coins``, ``close_all`` and ``close_partial``.
    ``coins`` contains dicts with trading instructions (entry, SL, TP1, TP2,
    risk).
    ``close_all`` is a list of {"pair"} dicts. ``close_partial`` is a list of
    {"pair", "pct"} dicts where ``pct`` is a percentage between 0 and 100.
    Invalid entries are ignored silently.
    """

    data = try_extract_json(text)
    coins_in = data.get("coins", []) if isinstance(data, dict) else []
    close_all_in = data.get("close_all", []) if isinstance(data, dict) else []
    close_part_in = data.get("close_partial", []) if isinstance(data, dict) else []

    coins: List[Dict[str, Any]] = []
    for item in coins_in:
        if not isinstance(item, dict):
            continue
        pair = (item.get("pair") or "").upper().replace("/", "")
        if not pair:
            continue
        entry = item.get("entry")
        sl = item.get("sl")
        tp1 = item.get("tp1")
        tp2 = item.get("tp2")
        tp3 = item.get("tp3")
        risk = item.get("risk")
        conf = item.get("conf")
        rr = item.get("rr")
        try:
            entry = float(entry) if entry is not None else None
            sl = float(sl) if sl is not None else None
            tp1 = float(tp1) if tp1 not in (None, "") else None
            tp2 = float(tp2) if tp2 not in (None, "") else None
            tp3 = float(tp3) if tp3 not in (None, "") else None
            risk = float(risk) if risk not in (None, "") else None
            conf = float(conf) if conf not in (None, "") else None
            rr = float(rr) if rr not in (None, "") else None
        except Exception:
            continue
        if None in (entry, sl) or entry == sl:
            continue
        if risk is not None and not (0 < risk < 1):
            continue
        side = "buy" if entry > sl else "sell"
        if tp1 is not None and (
            (side == "buy" and tp1 <= entry)
            or (side == "sell" and tp1 >= entry)
        ):
            continue
        if tp2 is not None and (
            (side == "buy" and tp2 <= entry)
            or (side == "sell" and tp2 >= entry)
        ):
            continue
        if tp3 is not None and (
            (side == "buy" and tp3 <= entry)
            or (side == "sell" and tp3 >= entry)
        ):
            continue
        coins.append(
            {
                "pair": pair,
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "tp3": tp3,
                "risk": risk,
                "conf": conf,
                "rr": rr,
            }
        )

    close_all: List[Dict[str, Any]] = []
    for item in close_all_in:
        if not isinstance(item, dict):
            continue
        pair = (item.get("pair") or "").upper().replace("/", "")
        if pair:
            close_all.append({"pair": pair})

    close_partial: List[Dict[str, Any]] = []
    for item in close_part_in:
        if not isinstance(item, dict):
            continue
        pair = (item.get("pair") or "").upper().replace("/", "")
        pct = item.get("pct")
        try:
            pct = float(pct)
        except Exception:
            continue
        if not pair or not (0 < pct <= 100):
            continue
        close_partial.append({"pair": pair, "pct": pct})

    return {"coins": coins, "close_all": close_all, "close_partial": close_partial}


KNOWN_QUOTES: Iterable[str] = (
    "USDT",
    "BUSD",
    "USDC",
    "USD",
    "BTC",
    "ETH",
    "BNB",
)


def to_ccxt_symbol(pair_no_slash: str, exchange: Any | None = None) -> str:
    """Convert ``BASEQUOTE`` pair to CCXT ``BASE/QUOTE`` format.

    Tries to detect the quote token by checking known quote currencies or
    consulting ``exchange.markets`` if an exchange instance is supplied.
    Falls back to splitting the last four characters if no match is found.
    """

    pair = pair_no_slash.upper()
    if exchange is not None:
        markets = getattr(exchange, "markets", {}) or {}
        for m in markets.values():
            sym = m.get("symbol")
            if isinstance(sym, str) and sym.replace("/", "") == pair:
                return sym
    for q in sorted(KNOWN_QUOTES, key=len, reverse=True):
        if pair.endswith(q):
            base = pair[: -len(q)]
            if base:
                return f"{base}/{q}"
    base, quote = pair[:-4], pair[-4:]
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


def calc_qty(
    capital: float,
    risk_frac: float,
    entry: float,
    sl: float,
    step: float,
    max_leverage: float = 1.0,
    contract_size: float = 1.0,
) -> float:
    """Tính khối lượng theo rủi ro, giới hạn bởi leverage và vốn."""

    dist = abs(entry - sl)
    if dist <= 0 or risk_frac <= 0 or capital <= 0:
        return 0.0  # dữ liệu không hợp lệ
    raw = (capital * risk_frac) / dist  # khối lượng theo công thức rủi ro
    max_qty = (capital * max_leverage) / (entry * contract_size)  # tối đa theo vốn và đòn bẩy
    qty = min(raw, max_qty)  # cắt giảm nếu vượt quá giới hạn
    return round_step(qty, step)


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
    """Compute qty and default TP1/TP2/TP3 levels for each action."""

    out: List[Dict[str, Any]] = []
    for a in acts:
        entry = a.get("entry")
        sl = a.get("sl")
        tp1 = a.get("tp1")
        tp2 = a.get("tp2")
        tp3 = a.get("tp3")
        risk = a.get("risk")
        if not (isinstance(entry, (int, float)) and isinstance(sl, (int, float))):
            continue
        dist = entry - sl
        tp1_def = entry + 1.0 * dist   # TP1 = 1R
        tp2_def = entry + 1.5 * dist   # TP2 = 1.5R

        if not (isinstance(tp1, (int, float)) and tp1 != entry):
            tp1 = tp1_def
        if not (isinstance(tp2, (int, float)) and tp2 != entry):
            tp2 = tp2_def
        tp3_def = tp2_def
        if not (isinstance(tp3, (int, float)) and tp3 != entry):
            tp3 = tp3_def
        a["tp1"] = rfloat(tp1, 8)
        a["tp2"] = rfloat(tp2, 8)
        a["tp3"] = rfloat(tp3, 8)
        rf = float(risk) if isinstance(risk, (int, float)) and risk > 0 else 0.01
        ccxt_sym = to_ccxt_symbol(a["pair"])
        step = qty_step(exchange, ccxt_sym)
        m = exchange.market(ccxt_sym)  # lấy thông tin thị trường
        max_lev = float(
            (m.get("limits", {}).get("leverage", {}) or {}).get("max")
            or (m.get("info") or {}).get("maxLeverage")
            or 1
        )
        contract = float(m.get("contractSize") or 1)
        qty = calc_qty(capital, rf, float(entry), float(sl), step, max_lev, contract)
        if qty <= 0:
            continue  # bỏ qua nếu khối lượng bằng 0
        a["qty"] = rfloat(qty, 8)
        a["risk"] = rfloat(rf, 6)
        side = infer_side(float(entry), float(sl), float(tp1))
        if side in {"buy", "sell"}:
            a["side"] = side
            out.append(a)
    return out

