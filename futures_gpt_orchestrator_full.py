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
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from ccxt.base.errors import OperationRejected  # type: ignore

try:  # pragma: no cover - optional dependency
    from apscheduler.schedulers.blocking import BlockingScheduler  # type: ignore
    from apscheduler.triggers.cron import CronTrigger  # type: ignore
except Exception:  # pragma: no cover - APScheduler missing
    BlockingScheduler = None
    CronTrigger = None

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
from positions import _norm_pair_from_symbol, get_open_position_pairs, positions_snapshot
from prompts import build_prompts_mini
from trading_utils import enrich_tp_qty, parse_mini_actions, to_ccxt_symbol

# Configure root logger to write informational messages to both stdout and a file.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
file_handler = logging.FileHandler("bot.log")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
)
logging.getLogger().addHandler(file_handler)

logger = logging.getLogger(__name__)

# Directory inside ``outputs`` where limit order metadata is stored
LIMIT_ORDER_DIR = Path("outputs") / "limit_orders"


def cancel_all_orders_for_pair(exchange, symbol: str, pair: str) -> None:
    """Cancel all open orders for ``symbol`` and remove its metadata file."""

    try:
        orders = exchange.fetch_open_orders(symbol)
    except Exception as e:  # pragma: no cover - network or exchange error
        logger.warning(
            "cancel_all_orders_for_pair fetch_open_orders error for %s: %s",
            pair,
            e,
        )
        orders = []
    for o in orders or []:
        try:
            exchange.cancel_order(o.get("id"), symbol)
        except Exception as e:  # pragma: no cover - cancel may fail
            logger.warning(
                "cancel_all_orders_for_pair cancel_order error for %s: %s",
                pair,
                e,
            )
    fp = LIMIT_ORDER_DIR / f"{pair}.json"
    try:
        if fp.exists():
            fp.unlink()
    except Exception as e:  # pragma: no cover - file removal may fail
        logger.warning("cancel_all_orders_for_pair unlink error %s: %s", fp, e)


def _place_sl_tp(exchange, symbol, side, qty1, qty2, sl, tp1, tp2, tp3):
    """Đặt SL và 3 TP (tp1 20%, tp2 30%, tp3 phần còn lại)."""

    exit_side = "sell" if side == "buy" else "buy"

    # To avoid hitting Binance's max stop order limit, cancel any existing
    # close-position stop orders before placing new ones.
    try:
        orders = exchange.fetch_open_orders(symbol)
    except Exception as e:  # pragma: no cover - network or exchange error
        logger.warning("_place_sl_tp fetch_open_orders error for %s: %s", symbol, e)
        orders = []
    for o in orders or []:
        try:
            info = o.get("info") or {}
            if info.get("closePosition"):
                exchange.cancel_order(o.get("id"), symbol)
        except Exception as e:  # pragma: no cover - cancel may fail
            logger.warning("_place_sl_tp cancel_order error for %s: %s", symbol, e)

    try:
        # Stop-loss closes toàn bộ vị thế
        exchange.create_order(
            symbol,
            "STOP_MARKET",
            exit_side,
            None,
            None,
            {"closePosition": True, "stopPrice": sl},
        )
        # TP1: chốt 20%
        if qty1 > 0:
            exchange.create_order(
                symbol,
                "TAKE_PROFIT_MARKET",
                exit_side,
                qty1,
                None,
                {"reduceOnly": True, "stopPrice": tp1},
            )
        # TP2: chốt 30%
        if qty2 > 0:
            exchange.create_order(
                symbol,
                "TAKE_PROFIT_MARKET",
                exit_side,
                qty2,
                None,
                {"reduceOnly": True, "stopPrice": tp2},
            )
        # TP3: đóng phần còn lại
        exchange.create_order(
            symbol,
            "TAKE_PROFIT_MARKET",
            exit_side,
            None,
            None,
            {"closePosition": True, "stopPrice": tp3},
        )
    except OperationRejected as e:  # pragma: no cover - depends on exchange state
        if getattr(e, "code", None) == -4045 or "max stop order" in str(e).lower():
            logger.warning(
                "_place_sl_tp reached max stop order limit for %s: %s", symbol, e
            )
        else:
            raise


# Default limit increased to 30 to expand the number of coins processed
def run(run_live: bool = False, limit: int = 30, ex=None) -> Dict[str, Any]:
    """Execute the full payload → decision → order pipeline."""

    logger.info("Run start live=%s limit=%s", run_live, limit)
    load_env()
    nano_model, mini_model = get_models()
    ex = ex or make_exchange()

    if run_live:
        cancel_unpositioned_limits(ex)

    try:
        bal = ex.fetch_balance()
        capital = float((bal.get("total") or {}).get("USDT", 0.0))
    except Exception as e:
        logger.warning("run fetch_balance error: %s", e)
        capital = 0.0
    logger.info("Capital available: %.2f USDT", capital)

    payload_full = build_payload(ex, limit)
    stamp = ts_prefix()
    save_text(f"{stamp}_payload_full.json", dumps_min(payload_full))
    logger.info("Payload built with %d coins", len(payload_full.get("coins", [])))

    if not payload_full.get("coins"):
        logger.info("No coins in payload, exiting run")
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
    logger.info("Model returned %d coin actions", len(coins))
    logger.info("Mini output JSON:\n%s", mini_text)


    placed: List[Dict[str, Any]] = []
    if run_live and coins:
        logger.info("Placing %d orders", len(coins))
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
            qty1 = c.get("qty1")
            qty2 = c.get("qty2")
            if side not in ("buy", "sell") or pair in pos_pairs_live:
                continue
            ccxt_sym = to_ccxt_symbol(pair)
            cancel_all_orders_for_pair(ex, ccxt_sym, pair)
            entry_order = ex.create_order(
                ccxt_sym, "limit", side, qty, entry, {"reduceOnly": False}
            )
            save_text(
                f"{pair}.json",
                dumps_min(
                    {
                        "pair": pair,
                        "order_id": entry_order.get("id"),
                        "side": side,
                        "limit": entry,
                        "qty": qty,
                        "qty1": qty1,
                        "qty2": qty2,
                        "sl": sl,
                        "tp1": tp1,
                        "tp2": tp2,
                        "tp3": tp3,
                    }
                ),
                folder=str(LIMIT_ORDER_DIR),
            )
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
                    "qty1": qty1,
                    "qty2": qty2,
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
    logger.info("Run complete: placed %d orders", len(placed))
    return {"ts": stamp, **result}


def cancel_unpositioned_limits(exchange):
    """Cancel all limit orders for pairs without positions and delete their JSON files."""

    logger.info("Checking for any open limit orders to cancel")
    try:
        # Suppress CCXT warning when fetching all open orders without a symbol
        exchange.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
        logger.info(
            "Fetching all open orders with warnOnFetchOpenOrdersWithoutSymbol=False"
        )
        orders = exchange.fetch_open_orders()
        logger.info("Fetched %d open orders", len(orders or []))
    except Exception as e:
        logger.warning("cancel_unpositioned_limits fetch_open_orders error: %s", e)
        return

    pos_pairs = get_open_position_pairs(exchange)
    for o in orders or []:
        try:
            if o.get("reduceOnly") or (o.get("type") or "").lower() != "limit":
                continue
            symbol = o.get("symbol") or (o.get("info") or {}).get("symbol")
            pair = _norm_pair_from_symbol(symbol)
            if pair in pos_pairs:
                continue
            try:
                exchange.cancel_order(o.get("id"), symbol)
            except Exception as e:
                logger.warning("cancel_unpositioned_limits cancel_order error: %s", e)
                continue
            fp = LIMIT_ORDER_DIR / f"{pair}.json"
            try:
                if fp.exists():
                    fp.unlink()
            except Exception as e:
                logger.warning(
                    "cancel_unpositioned_limits unlink error %s: %s", fp, e
                )
        except Exception as e:
            logger.warning("cancel_unpositioned_limits processing error: %s", e)
            continue


def add_sl_tp_from_json(exchange):
    """Đọc các file limit order và đặt SL/TP khi lệnh đã khớp."""
    for fp in LIMIT_ORDER_DIR.glob("*.json"):
        try:
            data = json.loads(fp.read_text())
        except Exception as e:
            logger.warning("add_sl_tp_from_json read error %s: %s", fp, e)
            continue
        pair = (data.get("pair") or "").upper()
        order_id = data.get("order_id")
        side = data.get("side")
        qty1 = data.get("qty1")
        qty2 = data.get("qty2")
        sl = data.get("sl")
        tp1 = data.get("tp1")
        tp2 = data.get("tp2")
        tp3 = data.get("tp3")
        if not (
            pair
            and order_id
            and side
            and sl
            and tp1
            and tp2
            and tp3
            and qty1 is not None
            and qty2 is not None
        ):
            continue
        ccxt_sym = to_ccxt_symbol(pair)
        try:
            o = exchange.fetch_order(order_id, ccxt_sym)
        except Exception as e:
            logger.warning("add_sl_tp_from_json fetch_order error for %s: %s", pair, e)
            continue
        status = (o.get("status") or "").lower()
        if status != "closed":
            continue
        _place_sl_tp(exchange, ccxt_sym, side, float(qty1), float(qty2), sl, tp1, tp2, tp3)
        try:
            fp.unlink()
        except Exception as e:
            logger.warning("add_sl_tp_from_json unlink error %s: %s", fp, e)



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


def live_loop(
    limit: int = 30,
    add_interval: int = 60,       # SL/TP add (1m)
):
    """Run orchestrator and maintenance checks on a schedule.

    - Orchestrator job runs at minutes 0, 15, 30 and 45.
    - Check để add SL/TP mỗi 1 phút.
    """

    if BlockingScheduler is None:
        raise RuntimeError("APScheduler is required for live_loop scheduling")

    logger.info(
        "Starting live loop limit=%s add_interval=%s",
        limit,
        add_interval,
    )

    ex = make_exchange()
    scheduler = BlockingScheduler()

    def run_job():
        logger.info("Scheduled run job triggered")
        try:
            run(run_live=True, limit=limit, ex=ex)
        except Exception:
            logger.exception("run_job error")

    def limit_job():
        logger.info("Scheduled SL/TP placement check")
        try:
            add_sl_tp_from_json(ex)
        except Exception:
            logger.exception("limit_job error")

    scheduler.add_job(run_job, CronTrigger(minute="0,15,30,45"))
    scheduler.add_job(limit_job, "interval", seconds=add_interval)

    logger.info("Scheduler starting")
    scheduler.start()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--live", action="store_true", default=env_bool("LIVE", False))
    parser.add_argument("--limit", type=int, default=env_int("LIMIT", 30))
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()
    if args.loop:
        live_loop(limit=args.limit)
    elif args.run:
        logger.info(dumps_min(run(run_live=args.live, limit=args.limit)))
    else:
        logger.info(
            dumps_min(
                run(run_live=env_bool("LIVE", False), limit=env_int("LIMIT", 30))
            )
        )

