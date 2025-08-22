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
import json
import logging
import os
import sched
import time
from threading import Thread
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
from positions import _norm_pair_from_symbol, get_open_position_pairs
from prompts import build_prompts_mini, build_prompts_nano
from trading_utils import enrich_tp_qty, parse_mini_actions, to_ccxt_symbol

logger = logging.getLogger(__name__)


def await_entry_fill(exchange, symbol, order_id, side, qty, sl, tp1, tp2, timeout=120):
    """Chờ lệnh vào khớp rồi đặt SL/TP tương ứng."""

    end = time.time() + timeout
    while time.time() < end:
        try:
            o = exchange.fetch_order(order_id, symbol)
            status = (o.get("status") or "").lower()
            if status == "open":
                time.sleep(2)  # chưa khớp, đợi thêm
                continue
            if status != "closed":
                return  # lệnh bị huỷ hoặc hết hạn
            qty_tp1 = rfloat(qty * 0.2, 8)
            qty_tp2 = rfloat(qty - qty_tp1, 8)
            if side == "buy":
                exchange.create_order(
                    symbol, "stop", "sell", qty, sl, {"stopPrice": sl, "reduceOnly": True}
                )
                exchange.create_order(
                    symbol, "limit", "sell", qty_tp1, tp1, {"reduceOnly": True}
                )
                exchange.create_order(
                    symbol, "limit", "sell", qty_tp2, tp2, {"reduceOnly": True}
                )
            else:
                exchange.create_order(
                    symbol, "stop", "buy", qty, sl, {"stopPrice": sl, "reduceOnly": True}
                )
                exchange.create_order(
                    symbol, "limit", "buy", qty_tp1, tp1, {"reduceOnly": True}
                )
                exchange.create_order(
                    symbol, "limit", "buy", qty_tp2, tp2, {"reduceOnly": True}
                )
            return
        except Exception:
            time.sleep(2)  # lỗi tạm thời, thử lại
    return


def run(run_live: bool = False, limit: int = 20, ex=None) -> Dict[str, Any]:
    """Execute the full payload → decision → order pipeline."""

    load_env()
    nano_model, mini_model = get_models()
    ex = ex or make_exchange()

    if run_live:
        cancel_unpositioned_limits(ex)

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

    kept: List[Dict[str, Any]] = [c for c in payload_full["coins"] if c["pair"] in keep]
    if not kept:
        result = {
            "live": run_live,
            "capital": capital,
            "coins": [],
            "placed": [],
            "reason": "nano_no_data",
        }
        save_text(f"{stamp}_orders.json", dumps_min(result))
        return {"ts": stamp, **result}

    payload_kept = {"time": payload_full["time"], "eth": payload_full["eth"], "coins": kept}
    save_text(f"{stamp}_payload_kept.json", dumps_min(payload_kept))

    pr_mini = build_prompts_mini(payload_kept)
    rsp_mini = send_openai(pr_mini["system"], pr_mini["user"], mini_model)
    mini_text = extract_content(rsp_mini)
    save_text(f"{stamp}_mini_output.json", mini_text)
    coins: List[Dict[str, Any]] = parse_mini_actions(mini_text)

    coins = enrich_tp_qty(ex, coins, capital)

    if coins:
        limits = {
            c["pair"]: {"sl": c["sl"], "tp1": c["tp1"], "tp2": c["tp2"]}
            for c in coins
        }
        save_text("gpt_limits.json", dumps_min(limits))  # ghi file để job nền đọc

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
            entry_order = ex.create_order(
                ccxt_sym, "limit", side, qty, entry, {"reduceOnly": False}
            )
            Thread(
                target=await_entry_fill,
                args=(ex, ccxt_sym, entry_order.get("id"), side, qty, sl, tp1, tp2),
                daemon=True,
            ).start()  # chạy nền chờ khớp để đặt SL/TP
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
                }
            )

    result = {"live": run_live, "capital": capital, "coins": coins, "placed": placed}
    save_text(f"{stamp}_orders.json", dumps_min(result))
    return {"ts": stamp, **result}


def cancel_unpositioned_limits(exchange, max_age_sec: int = 600):
    """Cancel non-reduceOnly limit orders for pairs without positions once stale (>10m)."""

    try:
        orders = exchange.fetch_open_orders()
    except Exception:
        return

    pos_pairs = get_open_position_pairs(exchange)
    now_ms = time.time() * 1000
    for o in orders or []:
        try:
            if o.get("reduceOnly") or (o.get("type") or "").lower() != "limit":
                continue
            symbol = o.get("symbol") or (o.get("info") or {}).get("symbol")
            pair = _norm_pair_from_symbol(symbol)
            if pair in pos_pairs:
                continue
            ts = o.get("timestamp") or (o.get("info") or {}).get("updateTime") or (o.get("info") or {}).get("time")
            if ts is None:
                continue
            age_sec = (now_ms - float(ts)) / 1000.0
            if age_sec < max_age_sec:
                continue
            try:
                exchange.cancel_order(o.get("id"), symbol)
            except Exception:
                continue
        except Exception:
            continue


def update_limits_from_file(exchange, path: str = "gpt_limits.json"):
    """Read GPT-provided levels from a file and reset SL/TP orders."""

    if not os.path.exists(path):
        return
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception:
        return
    try:
        positions = {
            _norm_pair_from_symbol(p.get("symbol") or (p.get("info") or {}).get("symbol")): p
            for p in (exchange.fetch_positions() or [])
        }
    except Exception:
        positions = {}
    for pair, params in (data or {}).items():
        if not isinstance(params, dict):
            continue
        pos = positions.get(pair.upper())
        if not pos:
            continue
        amt = pos.get("contracts") or pos.get("amount") or (pos.get("info") or {}).get("positionAmt")
        try:
            amt_val = float(amt)
        except Exception:
            continue
        side = "buy" if amt_val > 0 else "sell"
        qty = abs(amt_val)
        sl = params.get("sl")
        tp1 = params.get("tp1")
        tp2 = params.get("tp2")
        if None in (sl, tp1, tp2):
            continue
        symbol = to_ccxt_symbol(pair)
        qty_tp1 = rfloat(qty * 0.2, 8)
        qty_tp2 = rfloat(qty - qty_tp1, 8)
        try:
            orders = exchange.fetch_open_orders(symbol)
            for o in orders or []:
                try:
                    exchange.cancel_order(o.get("id"), symbol)
                except Exception:
                    continue
        except Exception:
            pass
        try:
            if side == "buy":
                exchange.create_order(symbol, "stop", "sell", qty, sl, {"stopPrice": sl, "reduceOnly": True})
                exchange.create_order(symbol, "limit", "sell", qty_tp1, tp1, {"reduceOnly": True})
                exchange.create_order(symbol, "limit", "sell", qty_tp2, tp2, {"reduceOnly": True})
            else:
                exchange.create_order(symbol, "stop", "buy", qty, sl, {"stopPrice": sl, "reduceOnly": True})
                exchange.create_order(symbol, "limit", "buy", qty_tp1, tp1, {"reduceOnly": True})
                exchange.create_order(symbol, "limit", "buy", qty_tp2, tp2, {"reduceOnly": True})
        except Exception:
            continue
    try:
        os.remove(path)  # xoá file sau khi xử lý để tránh lặp lại
    except Exception:
        pass


def move_sl_to_entry_if_tp1_hit(exchange):
    """Move stop-loss to entry once the first take-profit fills."""

    try:
        positions = exchange.fetch_positions()
    except Exception:
        return

    for pos in positions or []:
        symbol = pos.get("symbol") or (pos.get("info") or {}).get("symbol")
        amt = pos.get("contracts")
        if amt is None:
            amt = pos.get("amount")
        if amt is None:
            amt = (pos.get("info") or {}).get("positionAmt")
        try:
            amt_val = float(amt)
        except Exception:
            continue
        if amt_val == 0:
            continue
        side = "buy" if amt_val > 0 else "sell"
        entry = pos.get("entryPrice") or (pos.get("info") or {}).get("entryPrice")
        try:
            entry_price = float(entry)
        except Exception:
            continue
        try:
            ticker = exchange.fetch_ticker(symbol)
            last = ticker.get("last")
            if last is None:
                last = (ticker.get("info") or {}).get("lastPrice")
            last_price = float(last)
        except Exception:
            last_price = 0
        try:
            orders = exchange.fetch_open_orders(symbol)
        except Exception:
            continue
        sl_orders = [o for o in orders if (o.get("type") or "").lower() == "stop" and o.get("reduceOnly")]
        tp_orders = [o for o in orders if (o.get("type") or "").lower() == "limit" and o.get("reduceOnly")]
        if not sl_orders:
            continue
        if len(tp_orders) >= 2:
            if side == "buy":
                tp1_order = sorted(tp_orders, key=lambda o: float(o.get("price") or 0))[0]
                price_hit = last_price >= float(tp1_order.get("price") or 0)
                exit_side = "sell"
            else:
                tp1_order = sorted(tp_orders, key=lambda o: float(o.get("price") or 0), reverse=True)[0]
                price_hit = last_price <= float(tp1_order.get("price") or 0)
                exit_side = "buy"
            if not price_hit:
                continue
            qty_tp1 = abs(float(tp1_order.get("amount") or tp1_order.get("remaining") or 0))
            try:
                exchange.cancel_order(tp1_order.get("id"), symbol)
            except Exception:
                pass
            try:
                exchange.create_order(symbol, "market", exit_side, qty_tp1, None, {"reduceOnly": True})
            except Exception:
                continue
            try:
                orders = exchange.fetch_open_orders(symbol)
            except Exception:
                continue
            sl_orders = [o for o in orders if (o.get("type") or "").lower() == "stop" and o.get("reduceOnly")]
            tp_orders = [o for o in orders if (o.get("type") or "").lower() == "limit" and o.get("reduceOnly")]
        if len(tp_orders) >= 2:
            continue
        sl_order = sl_orders[0]
        try:
            sl_price = float(sl_order.get("price") or sl_order.get("stopPrice") or 0)
        except Exception:
            sl_price = 0
        if abs(sl_price - entry_price) < 1e-8:
            continue
        try:
            exchange.cancel_order(sl_order.get("id"), symbol)
        except Exception:
            pass
        try:
            qty = abs(amt_val)
            if side == "buy":
                exchange.create_order(
                    symbol,
                    "stop",
                    "sell",
                    qty,
                    entry_price,
                    {"stopPrice": entry_price, "reduceOnly": True},
                )
            else:
                exchange.create_order(
                    symbol,
                    "stop",
                    "buy",
                    qty,
                    entry_price,
                    {"stopPrice": entry_price, "reduceOnly": True},
                )
        except Exception:
            continue


def live_loop(limit: int = 20):
    """Run the orchestrator and adjust SL every minute."""

    ex = make_exchange()
    scheduler = sched.scheduler(time.time, time.sleep)

    def run_job():
        run(run_live=True, limit=limit, ex=ex)
        scheduler.enter(60, 1, run_job)

    def sl_job():
        move_sl_to_entry_if_tp1_hit(ex)
        update_limits_from_file(ex)
        scheduler.enter(60, 1, sl_job)

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
        logger.info(dumps_min(run(run_live=args.live, limit=args.limit)))
    else:
        logger.info(
            dumps_min(
                run(run_live=env_bool("LIVE", False), limit=env_int("LIMIT", 20))
            )
        )

