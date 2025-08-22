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
import time
import sched
from typing import Any, Dict, List

from env_utils import (
    dumps_min,
    env_bool,
    env_int,
    get_models,
    load_env,
    rfloat,
    save_text,
    ts_prefix,
)
from exchange_utils import make_exchange
from openai_client import extract_content, send_openai, try_extract_json
from payload_builder import build_payload
from positions import get_open_position_pairs
from prompts import build_prompts_mini, build_prompts_nano
from trading_utils import enrich_tp_qty, parse_mini_actions, to_ccxt_symbol


def run(run_live: bool = False, limit: int = 20, ex=None) -> Dict[str, Any]:
    """Execute the full payload → decision → order pipeline."""

    load_env()
    nano_model, mini_model = get_models()
    ex = ex or make_exchange()

    try:
        bal = ex.fetch_balance()
        capital = float((bal.get("total") or {}).get("USDT", 0.0))
    except Exception:
        capital = 0.0

    pos_pairs = get_open_position_pairs(ex)
    payload_full = build_payload(ex, limit, exclude_pairs=pos_pairs)
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

    coins = enrich_tp_qty(ex, coins, capital)

    placed: List[Dict[str, Any]] = []
    if run_live and coins:
        pos_pairs_live = get_open_position_pairs(ex)
        for c in coins:
            pair = (c.get("pair") or "").upper()
            side = c.get("side")
            entry = c.get("entry")
            sl = c.get("sl")
            tp1 = c.get("tp1")
            tp2 = c.get("tp2")
            qty = c.get("qty")
            if side not in ("buy", "sell") or pair in pos_pairs_live:
                continue
            ccxt_sym = to_ccxt_symbol(pair)
            qty_tp1 = rfloat(qty / 2, 8)
            qty_tp2 = rfloat(qty - qty_tp1, 8)
            entry_order = ex.create_order(ccxt_sym, "limit", side, qty, entry, {"reduceOnly": False})
            if side == "buy":
                sl_order = ex.create_order(ccxt_sym, "stop", "sell", qty, sl, {"stopPrice": sl, "reduceOnly": True})
                tp1_order = ex.create_order(ccxt_sym, "limit", "sell", qty_tp1, tp1, {"reduceOnly": True})
                tp2_order = ex.create_order(ccxt_sym, "limit", "sell", qty_tp2, tp2, {"reduceOnly": True})
            else:
                sl_order = ex.create_order(ccxt_sym, "stop", "buy", qty, sl, {"stopPrice": sl, "reduceOnly": True})
                tp1_order = ex.create_order(ccxt_sym, "limit", "buy", qty_tp1, tp1, {"reduceOnly": True})
                tp2_order = ex.create_order(ccxt_sym, "limit", "buy", qty_tp2, tp2, {"reduceOnly": True})
            placed.append(
                {
                    "pair": pair,
                    "side": side,
                    "entry": entry,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "qty": qty,
                    "entry_id": entry_order.get("id"),
                    "sl_id": sl_order.get("id"),
                    "tp1_id": tp1_order.get("id"),
                    "tp2_id": tp2_order.get("id"),
                }
            )

    result = {"live": run_live, "capital": capital, "coins": coins, "placed": placed}
    save_text(f"{stamp}_orders.json", dumps_min(result))
    return {"ts": stamp, **result}


def move_sl_to_entry_if_tp1_hit(exchange, trades: Dict[str, Dict[str, Any]]):
    """Move stop-loss to entry once price crosses TP1 for live trades."""

    for pair, info in list(trades.items()):
        if info.get("sl_moved"):
            continue
        ccxt_sym = to_ccxt_symbol(pair)
        try:
            price = float((exchange.fetch_ticker(ccxt_sym) or {}).get("last", 0))
        except Exception:
            continue
        side = info.get("side")
        tp1 = info.get("tp1")
        entry = info.get("entry")
        qty = info.get("qty")
        if side == "buy" and price >= tp1 or side == "sell" and price <= tp1:
            try:
                exchange.cancel_order(info.get("sl_id"), ccxt_sym)
            except Exception:
                pass
            try:
                if side == "buy":
                    sl_order = exchange.create_order(
                        ccxt_sym,
                        "stop",
                        "sell",
                        qty,
                        entry,
                        {"stopPrice": entry, "reduceOnly": True},
                    )
                else:
                    sl_order = exchange.create_order(
                        ccxt_sym,
                        "stop",
                        "buy",
                        qty,
                        entry,
                        {"stopPrice": entry, "reduceOnly": True},
                    )
                info["sl_id"] = sl_order.get("id")
                info["sl"] = entry
                info["sl_moved"] = True
            except Exception:
                continue


def live_loop(limit: int = 20):
    """Run the orchestrator live every 15 minutes and adjust SL every 5 minutes."""

    ex = make_exchange()
    active: Dict[str, Dict[str, Any]] = {}
    scheduler = sched.scheduler(time.time, time.sleep)

    def run_job():
        res = run(run_live=True, limit=limit, ex=ex)
        for p in res.get("placed", []):
            active[p["pair"]] = p
        scheduler.enter(15 * 60, 1, run_job)

    def sl_job():
        move_sl_to_entry_if_tp1_hit(ex, active)
        scheduler.enter(5 * 60, 1, sl_job)

    scheduler.enter(0, 1, run_job)
    scheduler.enter(0, 1, sl_job)
    scheduler.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--live", action="store_true", default=env_bool("LIVE", False))
    parser.add_argument("--limit", type=int, default=env_int("LIMIT", 20))
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    if args.loop:
        live_loop(limit=args.limit)
    elif args.run:
        print(dumps_min(run(run_live=args.live, limit=args.limit)))
    else:
        print(dumps_min(run(run_live=env_bool("LIVE", False), limit=env_int("LIMIT", 20))))

