"""Futures → GPT Orchestrator (15m focus, H4/D1 context; retains ETH bias).

This script orchestrates the flow:
1. Build payloads from market data
2. Generate trading decisions with the MINI model
3. Optionally place orders on Binance futures

The original monolithic implementation has been refactored into smaller
modules for clarity and maintainability.
"""

from __future__ import annotations

import argparse
import logging
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
from openai_client import extract_content, send_openai
from payload_builder import build_payload
from positions import _norm_pair_from_symbol, get_open_position_pairs
from prompts import build_prompts_mini
from trading_utils import enrich_tp_qty, parse_mini_actions, to_ccxt_symbol

logger = logging.getLogger(__name__)


def _place_sl_tp(exchange, symbol, side, qty, sl, tp1, tp2, tp3):
    """Place stop-loss and three take-profit orders for an entry."""

    qty_tp1 = rfloat(qty * 0.3, 8)
    qty_tp2 = rfloat(qty * 0.5, 8)
    qty_tp3 = rfloat(qty - qty_tp1 - qty_tp2, 8)
    exit_side = "sell" if side == "buy" else "buy"

    exchange.create_order(
        symbol, "limit", exit_side, qty, sl, {"stopPrice": sl, "reduceOnly": True}
    )
    exchange.create_order(
        symbol, "limit", exit_side, qty_tp1, tp1, {"reduceOnly": True}
    )
    exchange.create_order(
        symbol, "limit", exit_side, qty_tp2, tp2, {"reduceOnly": True}
    )
    exchange.create_order(
        symbol, "limit", exit_side, qty_tp3, tp3, {"reduceOnly": True}
    )


def await_entry_fill(exchange, symbol, order_id, side, qty, sl, tp1, tp2, tp3, timeout=120):
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
            _place_sl_tp(exchange, symbol, side, qty, sl, tp1, tp2, tp3)
            return
        except Exception as e:
            logger.warning("await_entry_fill fetch_order error: %s", e)
            time.sleep(2)  # lỗi tạm thời, thử lại
    return


def run(run_live: bool = False, limit: int = 10, ex=None) -> Dict[str, Any]:
    """Execute the full payload → decision → order pipeline."""

    load_env()
    _, mini_model = get_models()
    ex = ex or make_exchange()

    if run_live:
        cancel_unpositioned_limits(ex)

    try:
        bal = ex.fetch_balance()
        capital = float((bal.get("total") or {}).get("USDT", 0.0))
    except Exception as e:
        logger.warning("run fetch_balance error: %s", e)
        capital = 0.0

    payload_full = build_payload(ex, limit)
    stamp = ts_prefix()
    save_text(f"{stamp}_payload_full.json", dumps_min(payload_full))

    if not payload_full.get("coins"):
        save_text(
            f"{stamp}_orders.json",
            dumps_min(
                {
                    "live": run_live,
                    "capital": capital,
                    "coins": [],
                    "placed": [],
                    "reason": "no_coins",
                }
            ),
        )
        return {
            "ts": stamp,
            "live": run_live,
            "capital": capital,
            "coins": [],
            "placed": [],
        }

    pr_mini = build_prompts_mini(payload_full)
    rsp_mini = send_openai(pr_mini["system"], pr_mini["user"], mini_model)
    mini_text = extract_content(rsp_mini)
    save_text(f"{stamp}_mini_output.json", mini_text)
    acts = parse_mini_actions(mini_text)
    coins: List[Dict[str, Any]] = acts.get("coins", [])
    coins = enrich_tp_qty(ex, coins, capital)


    if coins:
        limits = {
            c["pair"]: {
                "sl": c["sl"],
                "tp1": c["tp1"],
                "tp2": c["tp2"],
                "tp3": c["tp3"],
            }
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
            tp3 = c.get("tp3")
            qty = c.get("qty")
            if side not in ("buy", "sell") or pair in pos_pairs_live:
                continue
            ccxt_sym = to_ccxt_symbol(pair)
            entry_order = ex.create_order(
                ccxt_sym, "limit", side, qty, entry, {"reduceOnly": False}
            )
            Thread(
                target=await_entry_fill,
                args=(ex, ccxt_sym, entry_order.get("id"), side, qty, sl, tp1, tp2, tp3),
                daemon=True,
            ).start()
            placed.append(
                {
                    "pair": pair,
                    "side": side,
                    "entry": entry,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "qty": qty,
                    "entry_id": entry_order.get("id"),
                }
            )

    result = {
        "live": run_live,
        "capital": capital,
        "coins": coins,
        "placed": placed,
    }
    save_text(f"{stamp}_orders.json", dumps_min(result))
    return {"ts": stamp, **result}


def cancel_unpositioned_limits(exchange, max_age_sec: int = 600):
    """Cancel non-reduceOnly limit orders for pairs without positions once stale (>10m)."""

    try:
        orders = exchange.fetch_open_orders()
    except Exception as e:
        logger.warning("cancel_unpositioned_limits fetch_open_orders error: %s", e)
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
            except Exception as e:
                logger.warning("cancel_unpositioned_limits cancel_order error: %s", e)
                continue
        except Exception as e:
            logger.warning("cancel_unpositioned_limits processing error: %s", e)
            continue



def _get_position_info(pos):
    symbol = pos.get("symbol") or (pos.get("info") or {}).get("symbol")
    amt = pos.get("contracts")
    if amt is None:
        amt = pos.get("amount")
    if amt is None:
        amt = (pos.get("info") or {}).get("positionAmt")
    try:
        amt_val = float(amt)
    except Exception as e:
        logger.warning("_get_position_info amt parse error: %s", e)
        return None
    if amt_val == 0:
        return None
    side = "buy" if amt_val > 0 else "sell"
    entry = pos.get("entryPrice") or (pos.get("info") or {}).get("entryPrice")
    try:
        entry_price = float(entry)
    except Exception as e:
        logger.warning("_get_position_info entry parse error: %s", e)
        return None
    return symbol, side, entry_price, amt_val


def _get_sl_tp_orders(exchange, symbol):
    try:
        ticker = exchange.fetch_ticker(symbol)
        last = ticker.get("last")
        if last is None:
            last = (ticker.get("info") or {}).get("lastPrice")
        last_price = float(last)
    except Exception as e:
        logger.warning("_get_sl_tp_orders fetch_ticker error for %s: %s", symbol, e)
        last_price = 0
    try:
        orders = exchange.fetch_open_orders(symbol)
    except Exception as e:
        logger.warning("_get_sl_tp_orders fetch_open_orders error for %s: %s", symbol, e)
        return [], [], last_price
    sl_orders = [
        o
        for o in orders
        if (o.get("type") or "").lower() == "limit"
        and o.get("reduceOnly")
        and (o.get("stopPrice") or (o.get("info") or {}).get("stopPrice"))
    ]
    tp_orders = [
        o
        for o in orders
        if (o.get("type") or "").lower() == "limit"
        and o.get("reduceOnly")
        and not (o.get("stopPrice") or (o.get("info") or {}).get("stopPrice"))
    ]
    return sl_orders, tp_orders, last_price


def _handle_tp1_hit(exchange, symbol, side, last_price, sl_orders, tp_orders):
    if len(tp_orders) < 3:
        return sl_orders, tp_orders
    if side == "buy":
        tp1_order = sorted(tp_orders, key=lambda o: float(o.get("price") or 0))[0]
        price_hit = last_price >= float(tp1_order.get("price") or 0)
        exit_side = "sell"
    else:
        tp1_order = sorted(tp_orders, key=lambda o: float(o.get("price") or 0), reverse=True)[0]
        price_hit = last_price <= float(tp1_order.get("price") or 0)
        exit_side = "buy"
    if not price_hit:
        return sl_orders, tp_orders
    qty_tp1 = abs(float(tp1_order.get("amount") or tp1_order.get("remaining") or 0))
    try:
        exchange.cancel_order(tp1_order.get("id"), symbol)
    except Exception as e:
        logger.warning("_handle_tp1_hit cancel_order error: %s", e)
    try:
        price = float(tp1_order.get("price") or 0)
        exchange.create_order(symbol, "limit", exit_side, qty_tp1, price, {"reduceOnly": True})
    except Exception as e:
        logger.warning("_handle_tp1_hit create_order error: %s", e)
        return sl_orders, tp_orders
    sl_orders, tp_orders, _ = _get_sl_tp_orders(exchange, symbol)
    return sl_orders, tp_orders


def _update_sl_to_entry(exchange, symbol, side, amt_val, entry_price, sl_order):
    try:
        sl_price = float(sl_order.get("price") or sl_order.get("stopPrice") or 0)
    except Exception as e:
        logger.warning("_update_sl_to_entry parse sl price error: %s", e)
        sl_price = 0
    if abs(sl_price - entry_price) < 1e-8:
        return
    try:
        exchange.cancel_order(sl_order.get("id"), symbol)
    except Exception as e:
        logger.warning("_update_sl_to_entry cancel_order error: %s", e)
    try:
        qty = abs(amt_val)
        if side == "buy":
            exchange.create_order(
                symbol,
                "limit",
                "sell",
                qty,
                entry_price,
                {"stopPrice": entry_price, "reduceOnly": True},
            )
        else:
            exchange.create_order(
                symbol,
                "limit",
                "buy",
                qty,
                entry_price,
                {"stopPrice": entry_price, "reduceOnly": True},
            )
    except Exception as e:
        logger.warning("_update_sl_to_entry create_order error: %s", e)
        return


def move_sl_to_entry_if_tp1_hit(exchange):
    """Move stop-loss to entry once the first take-profit fills."""

    try:
        positions = exchange.fetch_positions()
    except Exception as e:
        logger.warning("move_sl_to_entry_if_tp1_hit fetch_positions error: %s", e)
        return

    for pos in positions or []:
        info = _get_position_info(pos)
        if info is None:
            continue
        symbol, side, entry_price, amt_val = info
        sl_orders, tp_orders, last_price = _get_sl_tp_orders(exchange, symbol)
        if not sl_orders:
            continue
        sl_orders, tp_orders = _handle_tp1_hit(exchange, symbol, side, last_price, sl_orders, tp_orders)
        if len(tp_orders) >= 3:
            continue
        _update_sl_to_entry(exchange, symbol, side, amt_val, entry_price, sl_orders[0])

def live_loop(
    limit: int = 20,
    run_interval: int = 900,
    sl_interval: int = 300,
    cancel_interval: int = 600,
):
    """Run orchestrator and maintenance checks on a schedule.

    The orchestrator job defaults to running every fifteen minutes, the
    stop-loss check runs every five minutes, and stale limit orders are
    cancelled every ten minutes. The ``run_interval``, ``sl_interval`` and
    ``cancel_interval`` arguments (seconds) allow customizing these cadences.
    """

    ex = make_exchange()
    scheduler = sched.scheduler(time.time, time.sleep)

    def run_job():
        try:
            run(run_live=True, limit=limit, ex=ex)
        except Exception:
            logger.exception("run_job error")
        scheduler.enter(run_interval, 1, run_job)

    def sl_job():
        try:
            move_sl_to_entry_if_tp1_hit(ex)
        except Exception:
            logger.exception("sl_job error")
        scheduler.enter(sl_interval, 1, sl_job)

    def cancel_job():
        try:
            cancel_unpositioned_limits(ex)
        except Exception:
            logger.exception("cancel_job error")
        scheduler.enter(cancel_interval, 1, cancel_job)

    scheduler.enter(0, 1, run_job)
    scheduler.enter(0, 1, sl_job)
    scheduler.enter(0, 1, cancel_job)
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

