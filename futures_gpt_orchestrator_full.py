"""Futures → GPT Orchestrator (15m scalping, H1/H4, ETH bias).

This script orchestrates the full flow:
1. Build payloads from market data
2. Prefilter with the NANO model
3. Generate trading decisions with the MINI model
4. Optionally place orders on Binance futures

The original monolithic implementation has been refactored into smaller
modules for clarity and maintainability.
"""

from __future__ import annotations

import argparse
import threading
import time
from typing import Any, Dict, List

from env_utils import (
    dumps_min,
    env_bool,
    env_int,
    get_models,
    load_env,
    save_text,
    ts_prefix,
)
from exchange_utils import make_exchange
from openai_client import extract_content, send_openai, try_extract_json
from payload_builder import build_payload
from positions import get_open_position_pairs
from prompts import build_prompts_mini, build_prompts_nano
from trading_utils import enrich_tp_qty, parse_mini_actions, to_ccxt_symbol


exchange_lock = threading.Lock()


def call_locked(func, *args, **kwargs):
    """Call ``func`` with ``exchange_lock`` held to ensure thread safety."""
    with exchange_lock:
        return func(*args, **kwargs)


def await_entry_fill(
    exchange,
    ccxt_symbol: str,
    side: str,
    qty: float,
    price: float,
    timeout: float = 1800.0,
    poll_interval: float = 1.0,
):
    """Place a limit order and wait until it is fully filled or times out.

    All interactions with ``exchange`` are routed through :func:`call_locked`
    to ensure the global ``exchange_lock`` is honoured.

    Parameters
    ----------
    exchange: ccxt-like exchange instance
        The exchange on which to place the order.
    ccxt_symbol: str
        Symbol in CCXT format (e.g., ``"BTC/USDT"``).
    side: str
        ``"buy"`` or ``"sell"``.
    qty: float
        Order quantity.
    price: float
        Limit price for the entry order.
    timeout: float, optional
        Maximum seconds to wait for the order to fill before cancelling
        (default 30 minutes).
    poll_interval: float, optional
        Seconds between order status checks.

    Returns
    -------
    dict | None
        Final order information if filled, otherwise ``None``.
    """

    order = call_locked(
        exchange.create_order,
        ccxt_symbol,
        "limit",
        "buy" if side == "buy" else "sell",
        qty,
        price,
        {"reduceOnly": False},
    )

    order_id = order.get("id") if isinstance(order, dict) else None
    if not order_id:
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            current = call_locked(exchange.fetch_order, order_id, ccxt_symbol)
        except Exception:
            current = None
        if isinstance(current, dict):
            status = (current.get("status") or "").lower()
            filled = float(current.get("filled") or 0.0)
            if status == "closed" or filled >= float(qty):
                return current
        time.sleep(poll_interval)

    try:
        call_locked(exchange.cancel_order, order_id, ccxt_symbol)
    except Exception:
        pass
    return None


def run(run_live: bool = False, limit: int = 20) -> Dict[str, Any]:
    """Execute the full payload → decision → order pipeline."""

    load_env()
    nano_model, mini_model = get_models()
    ex = make_exchange()

    try:
        bal = call_locked(ex.fetch_balance)
        capital = float((bal.get("total") or {}).get("USDT", 0.0))
    except Exception:
        capital = 0.0

    pos_pairs = call_locked(get_open_position_pairs, ex)
    payload_full = call_locked(build_payload, ex, limit, exclude_pairs=pos_pairs)
    stamp = ts_prefix()
    save_text(f"{stamp}_payload_full.json", dumps_min(payload_full))
    save_text(
        f"{stamp}_positions_excluded.json",
        dumps_min({"positions": sorted(list(pos_pairs))}),
    )

    if not payload_full["coins"]:
        save_text(
            f"{stamp}_orders.json",
            dumps_min(
                {
                    "live": run_live,
                    "capital": capital,
                    "coins": [],
                    "placed": [],
                    "reason": "no_coins_after_exclude",
                }
            ),
        )
        return {"ts": stamp, "capital": capital, "coins": [], "placed": []}

    pr_nano = build_prompts_nano(payload_full)
    rsp_nano = send_openai(pr_nano["system"], pr_nano["user"], nano_model)
    nano_text = extract_content(rsp_nano)
    save_text(f"{stamp}_nano_output.json", nano_text)
    keep: List[str] = []
    try:
        j = try_extract_json(nano_text) or {}
        keep = [s.replace("/", "").upper() for s in (j.get("keep") or []) if isinstance(s, str)]
    except Exception:
        keep = []

    kept = [c for c in payload_full["coins"] if c["pair"] in keep] if keep else []
    payload_kept = {"time": payload_full["time"], "eth": payload_full["eth"], "coins": kept}
    save_text(f"{stamp}_payload_kept.json", dumps_min(payload_kept))

    mini_text = ""
    coins: List[Dict[str, Any]] = []
    if kept:
        pr_mini = build_prompts_mini(payload_kept)
        rsp_mini = send_openai(pr_mini["system"], pr_mini["user"], mini_model)
        mini_text = extract_content(rsp_mini)
        save_text(f"{stamp}_mini_output.json", mini_text)
        coins = parse_mini_actions(mini_text)

    coins = call_locked(enrich_tp_qty, ex, coins, capital)

    placed: List[Dict[str, Any]] = []
    if run_live and coins:
        pos_pairs_live = call_locked(get_open_position_pairs, ex)
        for c in coins:
            pair = (c.get("pair") or "").upper()
            side = c.get("side")
            entry = c.get("entry")
            sl = c.get("sl")
            tp = c.get("tp")
            qty = c.get("qty")
            if side not in ("buy", "sell"):
                continue
            if pair in pos_pairs_live:
                continue
            placed.append({"pair": pair, "side": side, "entry": entry, "sl": sl, "tp": tp, "qty": qty})
            ccxt_sym = to_ccxt_symbol(pair)
            call_locked(
                ex.create_order,
                ccxt_sym,
                "limit",
                "buy" if side == "buy" else "sell",
                qty,
                entry,
                {"reduceOnly": False},
            )

    result = {"live": run_live, "capital": capital, "coins": coins, "placed": placed}
    save_text(f"{stamp}_orders.json", dumps_min(result))
    return {"ts": stamp, **result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--live", action="store_true", default=env_bool("LIVE", False))
    parser.add_argument("--limit", type=int, default=env_int("LIMIT", 20))
    args = parser.parse_args()
    if args.run:
        print(dumps_min(run(run_live=args.live, limit=args.limit)))
    else:
        print(dumps_min(run(run_live=env_bool("LIVE", False), limit=env_int("LIMIT", 20))))

