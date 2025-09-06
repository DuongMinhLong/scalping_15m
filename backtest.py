"""Simple RSI-based backtesting pipeline.

This script downloads historical candles from the FXCM forex exchange via CCXT,
computes technical indicators and runs a toy RSI strategy to demonstrate how
one might wire the existing helpers into a backtest.
"""
from __future__ import annotations

import argparse
import logging
from typing import List

import pandas as pd

from exchange_utils import make_exchange, fetch_ohlcv_df
from indicators import add_indicators

logger = logging.getLogger(__name__)


def simple_rsi_strategy(df: pd.DataFrame) -> List[float]:
    """Return a list of trade returns using a naive RSI strategy."""

    position = 0
    entry = 0.0
    trades: List[float] = []
    for _, row in df.iterrows():
        rsi = float(row.get("rsi14"))
        price = float(row["close"])
        if position == 0 and rsi < 30:
            position = 1
            entry = price
        elif position == 1 and rsi > 70:
            trades.append((price - entry) / entry)
            position = 0
    return trades


def run_backtest(symbol: str, timeframe: str, limit: int, since: int | None) -> None:
    """Run a backtest for ``symbol`` and log basic performance metrics."""

    exchange = make_exchange()
    df = fetch_ohlcv_df(exchange, symbol, timeframe, limit, since)
    df = add_indicators(df).dropna()
    trades = simple_rsi_strategy(df)
    if trades:
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t <= 0]
        win_rate = len(wins) / len(trades)
        profit_factor = sum(wins) / abs(sum(losses)) if losses else float("inf")
        total = sum(trades)
    else:
        win_rate = 0.0
        profit_factor = 0.0
        total = 0.0
    logger.info(
        "Trades: %s | Win rate: %.2f%% | Profit factor: %.2f | Total return: %.4f",
        len(trades),
        win_rate * 100,
        profit_factor,
        total,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a simple backtest")
    parser.add_argument(
        "--symbol", default="XAU/USD", help="CCXT symbol, e.g. XAU/USD"
    )
    parser.add_argument("--timeframe", default="1h", help="Candle timeframe")
    parser.add_argument("--limit", type=int, default=500, help="Number of candles to fetch")
    parser.add_argument(
        "--since", type=int, default=None, help="Optional start timestamp in milliseconds"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_backtest(args.symbol, args.timeframe, args.limit, args.since)
