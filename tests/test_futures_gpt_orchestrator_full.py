import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "test")
import futures_gpt_orchestrator_full as orch  # noqa: E402
import trading_utils  # noqa: E402


class DummyExchange:
    def fetch_balance(self):
        return {"total": {"USD": 1000}}


class CaptureExchange:
    def __init__(self):
        self.orders = []
        self.cancelled = []

    def create_order(self, symbol, typ, side, qty, price, params):
        self.orders.append((symbol, typ, side, qty, price, params))

    def fetch_open_orders(self, symbol):
        return []

    def cancel_order(self, oid, symbol):
        self.cancelled.append((oid, symbol))


class FilledExchange(CaptureExchange):
    def fetch_order(self, order_id, symbol):
        return {"status": "closed"}


def test_run_sends_coins_only(monkeypatch):
    monkeypatch.setattr(orch, "load_env", lambda: None)
    monkeypatch.setattr(orch, "get_models", lambda: (None, "MODEL"))
    monkeypatch.setattr(orch, "ts_prefix", lambda: "ts")

    def fake_save_text(path, text):
        fake_save_text.saved[path] = text

    fake_save_text.saved = {}
    monkeypatch.setattr(orch, "save_text", fake_save_text)
    build_called = {}

    def fake_build_payload(ex, limit):
        build_called["called"] = True
        return {
            "coins": [{"p": "XAUUSD"}, {"p": "EURUSD"}],
            "positions": [
                {"pair": "XAUUSD", "entry": 1, "sl": 0.9, "tp": 1.1, "pnl": 0.0}
            ],
        }

    monkeypatch.setattr(orch, "build_payload", fake_build_payload)

    captured = {}

    def fake_send_openai(system, user, model):
        captured["user"] = user
        return {"choices": [{"message": {"content": "{\"coins\": []}"}}]}

    monkeypatch.setattr(orch, "send_openai", fake_send_openai)
    monkeypatch.setattr(
        orch, "extract_content", lambda r: r["choices"][0]["message"]["content"]
    )
    monkeypatch.setattr(orch, "parse_mini_actions", lambda text: {"coins": []})
    monkeypatch.setattr(orch, "enrich_tp_qty", lambda ex, coins, capital: coins)

    class DummyDT:
        @staticmethod
        def now(tz=None):
            return datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(orch, "datetime", DummyDT)

    res = orch.run(run_live=False, ex=DummyExchange())

    assert build_called.get("called")
    payload_str = captured.get("user", "")
    payload_str = payload_str[payload_str.find("{") :]
    data = json.loads(payload_str)
    assert any(c.get("p") == "XAUUSD" for c in data.get("coins", []))
    assert data.get("positions")
    assert res == {
        "ts": "ts",
        "live": False,
        "capital": 1000.0,
        "coins": [],
        "placed": [],
        "closed": [],
    }
    assert "ts_orders.json" in fake_save_text.saved
    data = json.loads(fake_save_text.saved["ts_orders.json"])
    assert data["coins"] == []
    assert data["placed"] == []
    assert data["closed"] == []


def test_run_cancels_existing_orders(monkeypatch, tmp_path):
    class CancelExchange:
        def __init__(self):
            self.orders = []
            self.cancelled = []

        def fetch_balance(self):
            return {"total": {"USD": 1000}}

        def fetch_open_orders(self, symbol):
            return [{"id": "old1"}, {"id": "old2"}]

        def cancel_order(self, oid, symbol):
            self.cancelled.append((oid, symbol))

        def create_order(self, symbol, typ, side, qty, price, params):
            self.orders.append((symbol, typ, side, qty, price, params))
            return {"id": "new"}

    ex = CancelExchange()
    monkeypatch.setattr(orch, "load_env", lambda: None)
    monkeypatch.setattr(orch, "get_models", lambda: (None, "MODEL"))
    monkeypatch.setattr(orch, "ts_prefix", lambda: "ts")
    monkeypatch.setattr(orch, "save_text", lambda *a, **k: None)
    monkeypatch.setattr(orch, "build_payload", lambda ex, limit: {"coins": ["dummy"]})
    monkeypatch.setattr(orch, "send_openai", lambda *a, **k: {})
    monkeypatch.setattr(orch, "extract_content", lambda r: "")
    monkeypatch.setattr(
        orch,
        "parse_mini_actions",
        lambda text: {
            "coins": [
                {
                    "pair": "EURUSD",
                    "side": "buy",
                    "entry": 1,
                    "sl": 0.9,
                    "tp": 1.1,
                    "qty": 1,
                }
            ]
        },
    )
    monkeypatch.setattr(orch, "enrich_tp_qty", lambda ex, coins, capital: coins)
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    monkeypatch.setattr(orch, "cancel_unpositioned_limits", lambda e: None)
    monkeypatch.setattr(orch, "cancel_unpositioned_stops", lambda e: None)
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "EURUSD.json").write_text("{}")

    class DummyDT:
        @staticmethod
        def now(tz=None):
            return datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(orch, "datetime", DummyDT)

    orch.run(run_live=True, ex=ex)

    assert ex.cancelled == [("old1", "EUR/USD"), ("old2", "EUR/USD")]
    assert len(ex.orders) == 1
    assert not (tmp_path / "EURUSD.json").exists()


def test_run_skips_when_tp_missing(monkeypatch, tmp_path):
    class Ex:
        def __init__(self):
            self.orders = []

        def fetch_balance(self):
            return {"total": {"USD": 1000}}

        def fetch_open_orders(self, symbol):
            return []

        def cancel_order(self, oid, symbol):
            pass

        def create_order(self, symbol, typ, side, qty, price, params):
            self.orders.append((symbol, typ, side, qty, price, params))
            return {"id": "new"}

        def market(self, symbol):
            return {"limits": {"leverage": {"max": 100}}, "contractSize": 1}

    ex = Ex()
    monkeypatch.setattr(orch, "load_env", lambda: None)
    monkeypatch.setattr(orch, "get_models", lambda: (None, "MODEL"))
    monkeypatch.setattr(orch, "ts_prefix", lambda: "ts")
    monkeypatch.setattr(orch, "save_text", lambda *a, **k: None)
    monkeypatch.setattr(orch, "build_payload", lambda ex, limit: {"coins": ["dummy"]})
    monkeypatch.setattr(orch, "send_openai", lambda *a, **k: {})
    monkeypatch.setattr(orch, "extract_content", lambda r: "")
    monkeypatch.setattr(
        orch,
        "parse_mini_actions",
        lambda text: {"coins": [{"pair": "EURUSD", "entry": 1, "sl": 0.9}]},
    )
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    monkeypatch.setattr(orch, "cancel_unpositioned_limits", lambda e: None)
    monkeypatch.setattr(orch, "remove_unmapped_limit_files", lambda e: None)
    monkeypatch.setattr(orch, "cancel_unpositioned_stops", lambda e: None)
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    monkeypatch.setattr(trading_utils, "qty_step", lambda e, s: 1)
    monkeypatch.setattr(trading_utils, "calc_qty", lambda *a, **k: 1)
    monkeypatch.setattr(trading_utils, "infer_side", lambda entry, sl, tp: "buy")

    class DummyDT:
        @staticmethod
        def now(tz=None):
            return datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(orch, "datetime", DummyDT)

    orch.run(run_live=True, ex=ex)

    assert len(ex.orders) == 0


def test_run_closes_positions(monkeypatch):
    class Ex:
        def __init__(self):
            self.orders = []

        def fetch_balance(self):
            return {"total": {"USD": 1000}}

        def fetch_positions(self):
            return [
                {"symbol": "EUR/USD", "contracts": 1, "entryPrice": 1},
            ]

        def fetch_open_orders(self, symbol):
            return []

        def cancel_order(self, oid, symbol):
            pass

        def create_order(self, symbol, typ, side, qty, price, params):
            self.orders.append((symbol, typ, side, qty, price, params))
            return {"id": "close"}

    ex = Ex()
    monkeypatch.setattr(orch, "load_env", lambda: None)
    monkeypatch.setattr(orch, "get_models", lambda: (None, "MODEL"))
    monkeypatch.setattr(orch, "ts_prefix", lambda: "ts")
    monkeypatch.setattr(orch, "save_text", lambda *a, **k: None)
    monkeypatch.setattr(orch, "build_payload", lambda ex, limit: {"positions": ["p"]})
    monkeypatch.setattr(orch, "send_openai", lambda *a, **k: {})
    monkeypatch.setattr(orch, "extract_content", lambda r: "")
    monkeypatch.setattr(
        orch, "parse_mini_actions", lambda text: {"coins": [], "close": ["EURUSD"]}
    )
    monkeypatch.setattr(orch, "enrich_tp_qty", lambda ex, coins, capital: coins)
    monkeypatch.setattr(orch, "cancel_unpositioned_limits", lambda e: None)
    monkeypatch.setattr(orch, "remove_unmapped_limit_files", lambda e: None)
    monkeypatch.setattr(orch, "cancel_unpositioned_stops", lambda e: None)

    class DummyDT:
        @staticmethod
        def now(tz=None):
            return datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(orch, "datetime", DummyDT)

    res = orch.run(run_live=True, ex=ex)

    assert ex.orders == [
        (
            "EUR/USD",
            "market",
            "sell",
            1,
            None,
            {"reduceOnly": True, "closePosition": True},
        )
    ]
    assert res["closed"] == ["EURUSD"]


@pytest.mark.parametrize("side,exit_side", [("buy", "sell"), ("sell", "buy")])
def test_place_sl_tp(side, exit_side):
    ex = CaptureExchange()
    orch._place_sl_tp(ex, "EUR/USD", side, 10, 1, 2)
    assert ex.cancelled == []
    assert ex.orders == [
        (
            "EUR/USD",
            "STOP_MARKET",
            exit_side,
            None,
            None,
            {"stopPrice": 1, "closePosition": True},
        ),
        (
            "EUR/USD",
            "TAKE_PROFIT_MARKET",
            exit_side,
            None,
            None,
            {"stopPrice": 2, "closePosition": True},
        ),
    ]


class ExistingStopExchange(CaptureExchange):
    def fetch_open_orders(self, symbol):
        return [{"id": "old1", "info": {"closePosition": True}}]


def test_place_sl_tp_cancels_existing():
    ex = ExistingStopExchange()
    orch._place_sl_tp(ex, "EUR/USD", "buy", 10, 1, 2)
    assert ex.cancelled == [("old1", "EUR/USD")]
    assert ex.orders == [
        (
            "EUR/USD",
            "STOP_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 1, "closePosition": True},
        ),
        (
            "EUR/USD",
            "TAKE_PROFIT_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 2, "closePosition": True},
        ),
    ]


def test_add_sl_tp_from_json(tmp_path, monkeypatch):
    limit_dir = tmp_path / "limit"
    limit_dir.mkdir()
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", limit_dir)
    data = {
        "pair": "EURUSD",
        "order_id": "1",
        "side": "buy",
        "limit": 1,
        "qty": 10,
        "sl": 0.9,
        "tp": 1.1,
    }
    (limit_dir / "EURUSD.json").write_text(json.dumps(data))
    ex = FilledExchange()
    orch.add_sl_tp_from_json(ex)
    assert not (limit_dir / "EURUSD.json").exists()
    assert ex.orders == [
        (
            "EUR/USD",
            "STOP_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 0.9, "closePosition": True},
        ),
        (
            "EUR/USD",
            "TAKE_PROFIT_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 1.1, "closePosition": True},
        ),
    ]


class BreakEvenExchange(CaptureExchange):
    def __init__(self):
        super().__init__()
        self.cancelled = []

    def fetch_positions(self):
        return [{"symbol": "EUR/USD", "contracts": 10, "entryPrice": 100}]

    def fetch_open_orders(self, symbol):
        return [
            {
                "id": "sl1",
                "symbol": symbol,
                "info": {"closePosition": True},
                "stopPrice": 90,
            },
            {
                "id": "tp1",
                "symbol": symbol,
                "info": {"closePosition": True},
                "stopPrice": 120,
            },
        ]

    def fetch_ticker(self, symbol):
        return {"last": 111}

    def cancel_order(self, oid, sym):
        self.cancelled.append((oid, sym))


def test_move_sl_to_entry(monkeypatch):
    ex = BreakEvenExchange()
    monkeypatch.setattr(orch, "qty_step", lambda e, s: 1)
    monkeypatch.setattr(orch, "round_step", lambda q, s: q)
    orch.move_sl_to_entry(ex)
    assert ex.cancelled == [("sl1", "EUR/USD"), ("tp1", "EUR/USD")]
    assert ex.orders == [
        ("EUR/USD", "MARKET", "sell", 2.0, None, {"reduceOnly": True}),
        (
            "EUR/USD",
            "STOP_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 100, "closePosition": True},
        ),
        (
            "EUR/USD",
            "TAKE_PROFIT_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 120, "closePosition": True},
        ),
    ]


class StaleExchange:
    def __init__(self):
        self.options = {}
        self.cancelled = []

    def fetch_open_orders(self):
        return [
            {
                "id": "1",
                "symbol": "EUR/USD",
                "type": "limit",
                "timestamp": 1,
                "reduceOnly": False,
            }
        ]

    def cancel_order(self, oid, symbol):
        self.cancelled.append((oid, symbol))


def test_cancel_unpositioned_limits_clears_json(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "EURUSD.json").write_text("{}")
    ex = StaleExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.cancel_unpositioned_limits(ex, max_age_sec=0)
    assert ex.cancelled == [("1", "EUR/USD")]
    assert not (tmp_path / "EURUSD.json").exists()


def test_cancel_unpositioned_limits_skips_when_position(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "EURUSD.json").write_text("{}")
    ex = StaleExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: {"EURUSD"})
    orch.cancel_unpositioned_limits(ex, max_age_sec=0)
    assert ex.cancelled == []
    assert (tmp_path / "EURUSD.json").exists()


class SecTimestampExchange:
    def __init__(self):
        self.options = {}
        self.cancelled = []

    def fetch_open_orders(self):
        return [
            {
                "id": "1",
                "symbol": "EUR/USD",
                "type": "limit",
                "timestamp": time.time(),
                "reduceOnly": False,
            }
        ]

    def cancel_order(self, oid, symbol):
        self.cancelled.append((oid, symbol))


def test_cancel_unpositioned_limits_handles_second_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "EURUSD.json").write_text("{}")
    ex = SecTimestampExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.cancel_unpositioned_limits(ex, max_age_sec=60)
    assert ex.cancelled == []
    assert (tmp_path / "EURUSD.json").exists()


class StopExchange:
    def __init__(self):
        self.options = {}
        self.cancelled = []

    def fetch_open_orders(self):
        return [
            {
                "id": "1",
                "symbol": "EUR/USD",
                "type": "STOP_MARKET",
                "reduceOnly": True,
                "stopPrice": 1,
            }
        ]

    def cancel_order(self, oid, symbol):
        self.cancelled.append((oid, symbol))


def test_cancel_unpositioned_stops_cancels(monkeypatch):
    ex = StopExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.cancel_unpositioned_stops(ex)
    assert ex.cancelled == [("1", "EUR/USD")]


class StopExchangeTrigger:
    def __init__(self):
        self.options = {}
        self.cancelled = []

    def fetch_open_orders(self):
        return [
            {
                "id": "1",
                "symbol": "EUR/USD",
                "type": "STOP_MARKET",
                "reduceOnly": True,
                "triggerPrice": 1,
            }
        ]

    def cancel_order(self, oid, symbol):
        self.cancelled.append((oid, symbol))


def test_cancel_unpositioned_stops_cancels_trigger(monkeypatch):
    ex = StopExchangeTrigger()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.cancel_unpositioned_stops(ex)
    assert ex.cancelled == [("1", "EUR/USD")]


def test_cancel_unpositioned_stops_skips_when_position(monkeypatch):
    ex = StopExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: {"EURUSD"})
    orch.cancel_unpositioned_stops(ex)
    assert ex.cancelled == []


class NoOrderExchange:
    def __init__(self):
        self.options = {}

    def fetch_open_orders(self):
        return []


class OpenOrderExchange:
    def __init__(self):
        self.options = {}

    def fetch_open_orders(self):
        return [{"symbol": "EUR/USD", "type": "limit"}]


def test_remove_unmapped_limit_files_clears_json(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "EURUSD.json").write_text("{}")
    ex = NoOrderExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.remove_unmapped_limit_files(ex)
    assert not (tmp_path / "EURUSD.json").exists()


def test_remove_unmapped_limit_files_skips_when_order(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "EURUSD.json").write_text("{}")
    ex = OpenOrderExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.remove_unmapped_limit_files(ex)
    assert (tmp_path / "EURUSD.json").exists()


def test_cancel_expired_limit_orders(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    data = {
        "pair": "EURUSD",
        "order_id": "1",
        "expiry": 1,
        "ts": time.time() - 2,
    }
    (tmp_path / "EURUSD.json").write_text(json.dumps(data))

    class Ex:
        def __init__(self):
            self.cancelled = []

        def fetch_order(self, oid, sym):
            return {"status": "open"}

        def cancel_order(self, oid, sym):
            self.cancelled.append((oid, sym))

    ex = Ex()
    orch.cancel_expired_limit_orders(ex)
    assert ex.cancelled == [("1", "EUR/USD")]
    assert not (tmp_path / "EURUSD.json").exists()
