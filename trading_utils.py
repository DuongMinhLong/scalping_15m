"""Parsing helpers and quantity/TP calculations for trades."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from env_utils import env_float, rfloat
from openai_client import try_extract_json
from typing import Iterable

DEFAULT_RISK_FRAC = env_float("DEFAULT_RISK", 0.005)


def parse_mini_actions(text: str) -> Dict[str, Any]:
    """Parse MINI model JSON output into trading instructions.

    The result contains keys ``coins`` (new entries), ``close`` (full closes),
    ``move_sl`` (adjust stop losses), ``close_partial`` (partial closes) and
    ``close_all`` (boolean flag to close all positions). Invalid entries are
    ignored silently.
    """

    data = try_extract_json(text)
    coins_in = data.get("coins", []) if isinstance(data, dict) else []
    close_in = data.get("close", []) if isinstance(data, dict) else []
    move_sl_in = data.get("move_sl", []) if isinstance(data, dict) else []
    close_part_in = data.get("close_partial", []) if isinstance(data, dict) else []
    close_all_flag = bool(data.get("close_all")) if isinstance(data, dict) else False

    coins: List[Dict[str, Any]] = []
    for item in coins_in:
        if not isinstance(item, dict):
            continue
        pair = (item.get("pair") or "").upper().replace("/", "")
        if not pair:
            continue
        entry = item.get("entry")
        sl = item.get("sl")
        tp = item.get("tp") if item.get("tp") is not None else item.get("tp1")
        risk = item.get("risk")
        conf = item.get("conf")
        rr = item.get("rr")
        try:
            entry = float(entry) if entry is not None else None
            sl = float(sl) if sl is not None else None
            tp = float(tp) if tp not in (None, "") else None
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
        if tp is not None and (
            (side == "buy" and tp <= entry)
            or (side == "sell" and tp >= entry)
        ):
            continue
        coins.append(
            {
                "pair": pair,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "risk": risk,
                "conf": conf,
                "rr": rr,
            }
        )

    close: List[Dict[str, Any]] = []
    for item in close_in:
        if not isinstance(item, dict):
            continue
        pair = (item.get("pair") or "").upper().replace("/", "")
        if pair:
            close.append({"pair": pair})

    move_sl: List[Dict[str, Any]] = []
    for item in move_sl_in:
        if not isinstance(item, dict):
            continue
        pair = (item.get("pair") or "").upper().replace("/", "")
        sl_val = item.get("sl")
        try:
            sl_val = float(sl_val)
        except Exception:
            continue
        if pair:
            move_sl.append({"pair": pair, "sl": sl_val})

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

    return {
        "coins": coins,
        "close": close,
        "move_sl": move_sl,
        "close_partial": close_partial,
        "close_all": close_all_flag,
    }


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
    """Compute qty for each action, requiring TP1 from the model.

    Actions missing TP1 are skipped.
    """

    out: List[Dict[str, Any]] = []
    for a in acts:
        entry = a.get("entry")
        sl = a.get("sl")
        tp = a.get("tp") if a.get("tp") is not None else a.get("tp1")
        risk = a.get("risk")
        if not (
            isinstance(entry, (int, float))
            and isinstance(sl, (int, float))
            and isinstance(tp, (int, float))
        ):
            continue
        a["tp"] = rfloat(tp, 8)
        rf = (
            float(risk) if isinstance(risk, (int, float)) and risk > 0 else DEFAULT_RISK_FRAC
        )
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
        side = infer_side(float(entry), float(sl), float(tp))
        if side in {"buy", "sell"}:
            a["side"] = side
            out.append(a)
    return out

