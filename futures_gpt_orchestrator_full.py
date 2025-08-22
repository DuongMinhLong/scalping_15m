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


def run(run_live: bool = False, limit: int = 20) -> Dict[str, Any]:
    """Execute the full payload → decision → order pipeline."""

    load_env()
    nano_model, mini_model = get_models()
    ex = make_exchange()

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
            tp = c.get("tp")
            qty = c.get("qty")
            if side not in ("buy", "sell"):
                continue
            if pair in pos_pairs_live:
                continue
            placed.append({"pair": pair, "side": side, "entry": entry, "sl": sl, "tp": tp, "qty": qty})
            ccxt_sym = to_ccxt_symbol(pair)
            ex.create_order(
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

