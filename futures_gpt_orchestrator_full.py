"""Futures → GPT Orchestrator (15m focus, 1h/4h context; retains ETH bias).

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

logging.getLogger("apscheduler").propagate = False
logging.getLogger("apscheduler").disabled = True

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
from positions import (
    _norm_pair_from_symbol,
    get_open_position_pairs,
    positions_snapshot,
)
from prompts import build_prompts_mini
from trading_utils import (
    enrich_tp_qty,
    parse_mini_actions,
    to_ccxt_symbol,
    qty_step,
    round_step,
)

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
# Default expiry for limit orders in minutes
LIMIT_ORDER_EXPIRY_MIN = env_int("LIMIT_ORDER_EXPIRY_MIN", 30)


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


def _place_sl_tp(exchange, symbol, side, qty, sl, tp):
    """Place stop-loss and take-profit orders for a position.

    Both orders use ``closePosition=True`` so the entire position is closed at
    market once the trigger price is hit. ``qty`` is ignored and kept only for
    backward compatibility.
    """

    exit_side = "sell" if side == "buy" else "buy"
    params_close = {"closePosition": True}

    # Cancel existing close-position/reduce-only orders before placing new ones
    try:
        orders = exchange.fetch_open_orders(symbol)
    except Exception as e:  # pragma: no cover - network or exchange error
        logger.warning("_place_sl_tp fetch_open_orders error for %s: %s", symbol, e)
        orders = []
    for o in orders or []:
        try:
            info = o.get("info") or {}
            if info.get("closePosition") or info.get("reduceOnly"):
                exchange.cancel_order(o.get("id"), symbol)
        except Exception as e:  # pragma: no cover - cancel may fail
            logger.warning("_place_sl_tp cancel_order error for %s: %s", symbol, e)

    try:
        ticker = exchange.fetch_ticker(symbol)
        price = float(ticker.get("last") or ticker.get("close"))
    except Exception as e:  # pragma: no cover - network or exchange error
        logger.warning("_place_sl_tp fetch_ticker error for %s: %s", symbol, e)
        price = None

    sl_ok = True
    tp_ok = True
    if price is not None:
        if side == "buy":
            sl_ok = sl < price
            tp_ok = tp > price
        else:
            sl_ok = sl > price
            tp_ok = tp < price

    if sl_ok:
        try:
            exchange.create_order(
                symbol,
                "STOP_MARKET",
                exit_side,
                None,
                None,
                {**params_close, "stopPrice": sl},
            )
        except OperationRejected as e:  # pragma: no cover - depends on exchange state
            if getattr(e, "code", None) == -4045 or "max stop order" in str(e).lower():
                logger.warning(
                    "_place_sl_tp reached max stop order limit for %s: %s", symbol, e
                )
            else:
                raise
    else:
        logger.warning(
            "_place_sl_tp skipping SL for %s price=%s sl=%s", symbol, price, sl
        )

    if tp_ok:
        try:
            exchange.create_order(
                symbol,
                "TAKE_PROFIT_MARKET",
                exit_side,
                None,
                None,
                {**params_close, "stopPrice": tp},
            )
        except OperationRejected as e:  # pragma: no cover - depends on exchange state
            if getattr(e, "code", None) == -4045 or "max stop order" in str(e).lower():
                logger.warning(
                    "_place_sl_tp reached max stop order limit for %s: %s", symbol, e
                )
            else:
                raise
    else:
        logger.warning(
            "_place_sl_tp skipping TP for %s price=%s tp=%s", symbol, price, tp
        )


# Default limit increased to 30 to expand the number of coins processed
def run(run_live: bool = False, limit: int = 30, ex=None) -> Dict[str, Any]:
    """Execute the full payload → decision → order pipeline."""
    start_time = time.time()
    logger.info("Run start live=%s limit=%s", run_live, limit)
    load_env()
    nano_model, mini_model = get_models()
    ex = ex or make_exchange()

    if run_live:
        cancel_unpositioned_limits(ex)
        remove_unmapped_limit_files(ex)
        cancel_unpositioned_stops(ex)

    try:
        bal = ex.fetch_balance()
        capital = float((bal.get("total") or {}).get("USDT", 0.0))
    except Exception as e:
        logger.warning("run fetch_balance error: %s", e)
        capital = 0.0
    logger.info("Capital available: %.2f USDT", capital)

    stamp = ts_prefix()

    if run_live:
        max_pos = env_int("MAX_OPEN_POSITIONS", 10)
        try:
            current_pos = len(get_open_position_pairs(ex))
        except Exception as e:
            logger.warning("run get_open_position_pairs error: %s", e)
            current_pos = 0
        if current_pos >= max_pos:
            logger.info(
                "Open positions %s >= max %s, exiting run", current_pos, max_pos
            )
            save_text(
                f"{stamp}_orders.json",
                dumps_min(
                    {
                        "live": run_live,
                        "capital": capital,
                        "coins": [],
                        "placed": [],
                        "closed": [],
                        "reason": "max_positions",
                    }
                ),
            )
            return {
                "ts": stamp,
                "live": run_live,
                "capital": capital,
                "coins": [],
                "placed": [],
                "closed": [],
            }

    payload_full = build_payload(ex, limit)
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
                    "closed": [],
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
            "closed": [],
        }

    pr_mini = build_prompts_mini(payload_full)
    rsp_mini = send_openai(pr_mini["system"], pr_mini["user"], mini_model)
    mini_text = extract_content(rsp_mini)
    save_text(f"{stamp}_mini_output.json", mini_text)
    acts = parse_mini_actions(mini_text)
    coins: List[Dict[str, Any]] = acts.get("coins", [])
    close_pairs: List[str] = acts.get("close", [])
    coins = enrich_tp_qty(ex, coins, capital)
    logger.info(
        "Model returned %d coin actions, %d close actions",
        len(coins),
        len(close_pairs),
    )
    logger.info("Mini output JSON:\n%s", mini_text)

    placed: List[Dict[str, Any]] = []
    closed: List[str] = []

    if run_live and coins:
        logger.info("Placing %d orders", len(coins))
        pos_pairs_live = get_open_position_pairs(ex)
        for c in coins:
            pair = (c.get("pair") or "").upper()
            side = c.get("side")
            entry = c.get("entry")
            sl = c.get("sl")
            tp = c.get("tp")
            qty = c.get("qty")
            if side not in ("buy", "sell") or pair in pos_pairs_live or tp is None:
                continue
            ccxt_sym = to_ccxt_symbol(pair)
            cancel_all_orders_for_pair(ex, ccxt_sym, pair)
            try:
                entry_order = ex.create_order(
                    ccxt_sym, "limit", side, qty, entry, {"reduceOnly": False}
                )
                expiry_min = LIMIT_ORDER_EXPIRY_MIN
                expiry_sec = float(expiry_min) * 60 if expiry_min else None
                save_text(
                    f"{pair}.json",
                    dumps_min(
                        {
                            "pair": pair,
                            "order_id": entry_order.get("id"),
                            "side": side,
                            "limit": entry,
                            "qty": qty,
                            "sl": sl,
                            "tp": tp,
                            "expiry": expiry_sec,
                            "ts": time.time(),
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
                        "tp": tp,
                        "qty": qty,
                        "entry_id": entry_order.get("id"),
                        "expiry": expiry_min,
                    }
                )
            except Exception as e:
                logger.warning("order placement error for %s: %s", pair, e)
                continue

    if run_live and close_pairs:
        snap = {p.get("pair"): p for p in positions_snapshot(ex)}
        for pair in close_pairs:
            pos = snap.get(pair)
            if not pos:
                continue
            side = pos.get("side")
            qty = pos.get("qty")
            if side not in ("buy", "sell") or not isinstance(qty, (int, float)):
                continue
            ccxt_sym = to_ccxt_symbol(pair)
            cancel_all_orders_for_pair(ex, ccxt_sym, pair)
            exit_side = "sell" if side == "buy" else "buy"
            try:
                ex.create_order(
                    ccxt_sym,
                    "market",
                    exit_side,
                    qty,
                    None,
                    {"reduceOnly": True, "closePosition": True},
                )
                closed.append(pair)
            except Exception as e:
                logger.warning("close_position error for %s: %s", pair, e)

    result = {
        "live": run_live,
        "capital": capital,
        "coins": coins,
        "placed": placed,
        "closed": closed,
    }
    save_text(f"{stamp}_orders.json", dumps_min(result))
    elapsed = time.time() - start_time
    logger.info("Run complete in %.2fs: placed %d orders", elapsed, len(placed))
    return {"ts": stamp, **result}


def cancel_unpositioned_limits(exchange, max_age_sec: int = 600 * 3):
    """Cancel stale limit orders for pairs without positions and delete their JSON files."""

    logger.info("Checking for stale limit orders older than %s seconds", max_age_sec)
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
    now = time.time()
    for o in orders or []:
        try:
            if o.get("reduceOnly") or (o.get("type") or "").lower() != "limit":
                continue
            symbol = o.get("symbol") or (o.get("info") or {}).get("symbol")
            pair = _norm_pair_from_symbol(symbol)
            if pair in pos_pairs:
                continue
            ts = (
                o.get("timestamp")
                or (o.get("info") or {}).get("updateTime")
                or (o.get("info") or {}).get("time")
            )
            if ts is None:
                continue
            try:
                ts_val = float(ts)
            except Exception:
                continue
            ts_sec = ts_val / 1000.0 if ts_val > 1e12 else ts_val
            age_sec = now - ts_sec
            if age_sec < max_age_sec:
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
                logger.warning("cancel_unpositioned_limits unlink error %s: %s", fp, e)
        except Exception as e:
            logger.warning("cancel_unpositioned_limits processing error: %s", e)
            continue


def cancel_unpositioned_stops(exchange) -> None:
    """Cancel reduce-only stop-loss or take-profit orders without positions."""

    logger.info("Checking for orphaned SL/TP orders")
    try:
        exchange.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
        orders = exchange.fetch_open_orders()
    except Exception as e:
        logger.warning("cancel_unpositioned_stops fetch_open_orders error: %s", e)
        return

    pos_pairs = get_open_position_pairs(exchange)
    for o in orders or []:
        try:
            info = o.get("info") or {}
            if not (o.get("reduceOnly") or info.get("closePosition")):
                continue
            if not (
                o.get("stopPrice")
                or info.get("stopPrice")
                or o.get("triggerPrice")
                or info.get("triggerPrice")
                or (o.get("type") or "").lower().startswith("take")
                or (o.get("type") or "").lower().startswith("stop")
            ):
                continue
            symbol = o.get("symbol") or info.get("symbol")
            pair = _norm_pair_from_symbol(symbol)
            if pair in pos_pairs:
                continue
            oid = o.get("id")
            if not oid:
                continue
            try:
                exchange.cancel_order(oid, symbol)
            except Exception as e:
                logger.warning("cancel_unpositioned_stops cancel_order error: %s", e)
                continue
        except Exception as e:
            logger.warning("cancel_unpositioned_stops processing error: %s", e)
            continue


def cancel_expired_limit_orders(exchange) -> None:
    """Cancel limit orders whose custom expiry has passed."""

    now = time.time()
    for fp in LIMIT_ORDER_DIR.glob("*.json"):
        try:
            data = json.loads(fp.read_text())
        except Exception as e:
            logger.warning("cancel_expired_limit_orders read error %s: %s", fp, e)
            continue
        expiry = data.get("expiry")
        ts = data.get("ts")
        order_id = data.get("order_id")
        pair = data.get("pair")
        if not all([expiry, ts, order_id, pair]):
            continue
        try:
            if now - float(ts) < float(expiry):
                continue
        except Exception:
            continue
        symbol = to_ccxt_symbol(pair)
        try:
            order = exchange.fetch_order(order_id, symbol)
        except Exception:
            order = None
        status = (order or {}).get("status")
        if status == "closed":
            try:
                fp.unlink()
            except Exception as e:
                logger.warning(
                    "cancel_expired_limit_orders unlink closed error %s: %s", fp, e
                )
            continue
        try:
            exchange.cancel_order(order_id, symbol)
        except Exception as e:
            logger.warning(
                "cancel_expired_limit_orders cancel error for %s: %s", pair, e
            )
        try:
            fp.unlink()
        except Exception as e:
            logger.warning("cancel_expired_limit_orders unlink error %s: %s", fp, e)


def remove_unmapped_limit_files(exchange) -> None:
    """Remove limit-order JSON files without an open order or position."""

    try:
        exchange.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
        orders = exchange.fetch_open_orders()
    except Exception as e:
        logger.warning("remove_unmapped_limit_files fetch_open_orders error: %s", e)
        orders = []

    open_pairs = {
        _norm_pair_from_symbol(o.get("symbol") or (o.get("info") or {}).get("symbol"))
        for o in orders or []
        if (o.get("type") or "").lower() == "limit"
    }
    pos_pairs = get_open_position_pairs(exchange)

    for fp in LIMIT_ORDER_DIR.glob("*.json"):
        pair = fp.stem.upper()
        if pair in open_pairs or pair in pos_pairs:
            continue
        try:
            fp.unlink()
        except Exception as e:  # pragma: no cover - filesystem issues
            logger.warning("remove_unmapped_limit_files unlink error %s: %s", fp, e)


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
        qty = data.get("qty")
        sl = data.get("sl")
        tp = data.get("tp")
        if not (pair and order_id and side and qty and sl and tp):
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
        _place_sl_tp(exchange, ccxt_sym, side, qty, sl, tp)
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


def move_sl_to_entry(exchange):
    """If price surpasses 1R, close 20% and move stop-loss to entry."""
    positions = positions_snapshot(exchange)
    for pos in positions:
        pair = pos.get("pair")
        side = pos.get("side")
        entry = pos.get("entry")
        sl = pos.get("sl")
        tp = pos.get("tp")
        qty_total = pos.get("qty")
        if not (pair and side and entry and sl and tp and qty_total):
            continue
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp1 = entry + risk if side == "buy" else entry - risk
        symbol = to_ccxt_symbol(pair)
        try:
            ticker = exchange.fetch_ticker(symbol)
            price = float(ticker.get("last") or ticker.get("close"))
        except Exception as e:
            logger.warning("move_sl_to_entry fetch_ticker error for %s: %s", pair, e)
            continue
        hit = (side == "buy" and price > tp1) or (side == "sell" and price < tp1)
        if not hit:
            continue
        exit_side = "sell" if side == "buy" else "buy"
        qty_close = qty_total * 0.2
        try:
            step = qty_step(exchange, symbol)
            qty_close = round_step(qty_close, step)
        except Exception:
            pass
        try:
            exchange.create_order(
                symbol,
                "MARKET",
                exit_side,
                qty_close,
                None,
                {"reduceOnly": True},
            )
        except Exception as e:
            logger.warning("move_sl_to_entry close_partial error for %s: %s", pair, e)
            continue
        try:
            _place_sl_tp(exchange, symbol, side, qty_total, entry, tp)
        except Exception as e:
            logger.warning("move_sl_to_entry place_sl_tp error for %s: %s", pair, e)


def live_loop(
    limit: int = 30,
    cancel_interval: int = 600,  # cancel stale orders (10m)
    add_interval: int = 60,  # SL/TP add (1m)
    move_sl_interval: int = 600,  # move SL to entry (10m)
):
    """Run orchestrator and maintenance checks on a schedule.

    - Orchestrator job runs at the top of every hour.
    - Cancel stale limit orders mỗi 10 phút.
    - Check để add SL/TP mỗi 1 phút.
    - Kiểm tra dời SL về entry mỗi 10 phút.
    """

    if BlockingScheduler is None:
        raise RuntimeError("APScheduler is required for live_loop scheduling")

    logger.info(
        "Starting live loop limit=%s cancel_interval=%s add_interval=%s move_sl_interval=%s",
        limit,
        cancel_interval,
        add_interval,
        move_sl_interval,
    )

    ex = make_exchange()
    scheduler = BlockingScheduler()

    def run_job():
        start = time.time()
        logger.info("Scheduled run job triggered")
        try:
            run(run_live=True, limit=limit, ex=ex)
        except Exception:
            logger.exception("run_job error")
        finally:
            logger.info("Scheduled run job finished in %.2fs", time.time() - start)

    # def cancel_job():
    #     logger.info("Scheduled stale order cancel check")
    #     try:
    #         cancel_unpositioned_limits(ex)
    #     except Exception:
    #         logger.exception("cancel_job error")

    def limit_job():
        start = time.time()
        logger.info("Scheduled SL/TP placement check")
        try:
            add_sl_tp_from_json(ex)
        except Exception:
            logger.exception("limit_job error")
        finally:
            logger.info("SL/TP placement check finished in %.2fs", time.time() - start)

    def expiry_job():
        start = time.time()
        logger.info("Scheduled limit expiry check")
        try:
            cancel_expired_limit_orders(ex)
        except Exception:
            logger.exception("expiry_job error")
        finally:
            logger.info("Limit expiry check finished in %.2fs", time.time() - start)

    def move_sl_job():
        logger.info("Scheduled move SL to entry check")
        try:
            move_sl_to_entry(ex)
        except Exception:
            logger.exception("move_sl_job error")

    scheduler.add_job(run_job, CronTrigger(minute="0,15,30,45"))

    # Các job còn lại chạy theo interval
    # scheduler.add_job(cancel_job, "interval", seconds=cancel_interval)
    scheduler.add_job(limit_job, "interval", seconds=add_interval)
    scheduler.add_job(expiry_job, "interval", seconds=60)
    # scheduler.add_job(move_sl_job, "interval", seconds=move_sl_interval)

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
            dumps_min(run(run_live=env_bool("LIVE", False), limit=env_int("LIMIT", 30)))
        )
