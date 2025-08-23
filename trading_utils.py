"""Parsing helpers and quantity/TP calculations for trades."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from env_utils import rfloat
from openai_client import try_extract_json
from typing import Iterable


def parse_mini_actions(text: str) -> List[Dict[str, Any]]:
    """Phân tích output của mô hình MINI thành danh sách hành động."""

    data = try_extract_json(text)
    arr = data.get("coins", []) if isinstance(data, dict) else []
    out: List[Dict[str, Any]] = []
    for item in arr:
        if not isinstance(item, dict):
            continue  # bỏ qua phần tử không phải dict
        pair = (item.get("pair") or "").upper().replace("/", "")
        if not pair:
            continue  # thiếu mã giao dịch
        entry = item.get("entry")
        sl = item.get("sl")
        tp2 = item.get("tp2")
        risk = item.get("risk")
        try:
            entry = float(entry) if entry is not None else None
            sl = float(sl) if sl is not None else None
            tp2 = float(tp2) if tp2 not in (None, "") else None
            risk = float(risk) if risk not in (None, "") else None
        except Exception:
            continue  # dữ liệu số không hợp lệ
        if None in (entry, sl) or entry == sl:
            continue  # entry và SL phải có và khác nhau
        if risk is not None and not (0 < risk < 1):
            continue  # rủi ro phải trong (0,1)
        if tp2 is not None:
            if (entry > sl and tp2 <= entry) or (entry < sl and tp2 >= entry):
                continue  # TP2 phải cùng hướng với entry-SL
        out.append({"pair": pair, "entry": entry, "sl": sl, "tp2": tp2, "risk": risk})
    return out


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
    """Compute qty, TP1 (1R) and TP2 (default 2R) for each action."""

    out: List[Dict[str, Any]] = []
    for a in acts:
        entry = a.get("entry")
        sl = a.get("sl")
        tp2 = a.get("tp2")
        risk = a.get("risk")
        if not (isinstance(entry, (int, float)) and isinstance(sl, (int, float))):
            continue
        tp1 = entry + (entry - sl) if entry > sl else entry - (sl - entry)
        a["tp1"] = rfloat(tp1, 8)
        if not (isinstance(tp2, (int, float)) and tp2 > 0 and tp2 != entry):
            tp2 = entry + 2 * (entry - sl) if entry > sl else entry - 2 * (sl - entry)
        a["tp2"] = rfloat(tp2, 8)
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
        side = infer_side(float(entry), float(sl), float(tp2))
        if side in {"buy", "sell"}:
            a["side"] = side
            out.append(a)
    return out

