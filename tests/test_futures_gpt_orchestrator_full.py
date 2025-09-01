import json
import os
import pathlib
import sys
import time

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "test")
import futures_gpt_orchestrator_full as orch  # noqa: E402
import trading_utils  # noqa: E402


class DummyExchange:
    def fetch_balance(self):
        return {"total": {"USDT": 1000}}


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
            "coins": [{"p": "ETHUSDT"}, {"p": "BTCUSDT"}],
            "positions": [
                {"pair": "ETHUSDT", "entry": 1, "sl": 0.9, "tp": 1.1, "pnl": 0.0}
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

    res = orch.run(run_live=False, ex=DummyExchange())

    assert build_called.get("called")
    payload_str = captured.get("user", "")
    payload_str = payload_str[payload_str.find("{") :]
    data = json.loads(payload_str)
    assert any(c.get("p") == "ETHUSDT" for c in data.get("coins", []))
    assert data.get("positions")
    assert res == {
        "ts": "ts",
        "live": False,
        "capital": 1000.0,
        "coins": [],
        "placed": [],
        "closed": [],
        "moved_sl": [],
        "closed_partial": [],
    }
    assert "ts_orders.json" in fake_save_text.saved
    data = json.loads(fake_save_text.saved["ts_orders.json"])
    assert data["coins"] == []
    assert data["placed"] == []
    assert data["closed"] == []
    assert data["moved_sl"] == []
    assert data["closed_partial"] == []


def test_run_cancels_existing_orders(monkeypatch, tmp_path):
    class CancelExchange:
        def __init__(self):
            self.orders = []
            self.cancelled = []

        def fetch_balance(self):
            return {"total": {"USDT": 1000}}

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
                    "pair": "BTCUSDT",
                    "side": "buy",
                    "entry": 1,
                    "sl": 0.9,
                    "tp1": 1.1,
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
    (tmp_path / "BTCUSDT.json").write_text("{}")

    orch.run(run_live=True, ex=ex)

    assert ex.cancelled == [("old1", "BTC/USDT"), ("old2", "BTC/USDT")]
    assert len(ex.orders) == 1
    assert not (tmp_path / "BTCUSDT.json").exists()


def test_run_skips_when_tp_missing(monkeypatch, tmp_path):
    class Ex:
        def __init__(self):
            self.orders = []

        def fetch_balance(self):
            return {"total": {"USDT": 1000}}

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
        lambda text: {"coins": [{"pair": "BTCUSDT", "entry": 1, "sl": 0.9}]},
    )
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    monkeypatch.setattr(orch, "cancel_unpositioned_limits", lambda e: None)
    monkeypatch.setattr(orch, "remove_unmapped_limit_files", lambda e: None)
    monkeypatch.setattr(orch, "cancel_unpositioned_stops", lambda e: None)
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    monkeypatch.setattr(trading_utils, "qty_step", lambda e, s: 1)
    monkeypatch.setattr(trading_utils, "calc_qty", lambda *a, **k: 1)
    monkeypatch.setattr(trading_utils, "infer_side", lambda entry, sl, tp1: "buy")

    orch.run(run_live=True, ex=ex)

    assert len(ex.orders) == 0


def test_run_handles_partial_and_move_sl(monkeypatch):
    ex = CaptureExchange()
    monkeypatch.setattr(orch, "load_env", lambda: None)
    monkeypatch.setattr(orch, "get_models", lambda: (None, "MODEL"))
    monkeypatch.setattr(orch, "ts_prefix", lambda: "ts")
    monkeypatch.setattr(orch, "save_text", lambda *a, **k: None)

    def fake_build_payload(ex2, limit):
        return {
            "coins": [],
            "positions": [
                {
                    "pair": "BTCUSDT",
                    "side": "buy",
                    "entry": 1,
                    "sl": 0.9,
                    "tp": 1.1,
                    "pnl": 0.0,
                    "qty": 2,
                }
            ],
        }

    monkeypatch.setattr(orch, "build_payload", fake_build_payload)
    monkeypatch.setattr(orch, "send_openai", lambda *a, **k: {})
    monkeypatch.setattr(orch, "extract_content", lambda r: "")
    monkeypatch.setattr(
        orch,
        "parse_mini_actions",
        lambda text: {
            "coins": [],
            "close": [],
            "move_sl": [{"pair": "BTCUSDT", "sl": 0.95}],
            "close_partial": [{"pair": "BTCUSDT", "pct": 50}],
            "close_all": False,
        },
    )
    monkeypatch.setattr(orch, "enrich_tp_qty", lambda ex, coins, capital: coins)
    monkeypatch.setattr(orch, "qty_step", lambda e, s: 1)
    monkeypatch.setattr(orch, "round_step", lambda q, s: q)

    called = {}

    def fake_place_sl_tp(exchange, symbol, side, qty, sl, tp1, tp2=None, tp3=None):
        called["args"] = (symbol, side, qty, sl, tp1, tp2, tp3)

    monkeypatch.setattr(orch, "_place_sl_tp", fake_place_sl_tp)

    res = orch.run(run_live=True, ex=ex)

    assert ex.orders == [
        ("BTC/USDT", "MARKET", "sell", 1.0, None, {"reduceOnly": True})
    ]
    assert called.get("args") == ("BTC/USDT", "buy", 2, 0.95, 1.1, None, None)
    assert res["closed_partial"]
    assert res["moved_sl"]


def test_run_handles_close_all(monkeypatch):
    ex = CaptureExchange()
    monkeypatch.setattr(orch, "load_env", lambda: None)
    monkeypatch.setattr(orch, "get_models", lambda: (None, "MODEL"))
    monkeypatch.setattr(orch, "ts_prefix", lambda: "ts")
    monkeypatch.setattr(orch, "save_text", lambda *a, **k: None)

    def fake_build_payload(ex2, limit):
        return {
            "coins": [],
            "positions": [
                {
                    "pair": "ETHUSDT",
                    "side": "sell",
                    "entry": 1,
                    "sl": 1.1,
                    "tp": 0.9,
                    "pnl": 0.0,
                    "qty": 3,
                }
            ],
        }

    monkeypatch.setattr(orch, "build_payload", fake_build_payload)
    monkeypatch.setattr(orch, "send_openai", lambda *a, **k: {})
    monkeypatch.setattr(orch, "extract_content", lambda r: "")
    monkeypatch.setattr(
        orch,
        "parse_mini_actions",
        lambda text: {
            "coins": [],
            "close": [],
            "move_sl": [],
            "close_partial": [],
            "close_all": True,
        },
    )
    monkeypatch.setattr(orch, "enrich_tp_qty", lambda ex, coins, capital: coins)

    res = orch.run(run_live=True, ex=ex)

    assert ex.orders == [
        ("ETH/USDT", "MARKET", "buy", None, None, {"reduceOnly": True, "closePosition": True})
    ]
    assert res["closed"] == [{"pair": "ETHUSDT"}]


def test_run_respects_max_open_positions(monkeypatch):
    class Ex:
        def fetch_balance(self):
            return {"total": {"USDT": 1000}}

    ex = Ex()
    monkeypatch.setattr(orch, "load_env", lambda: None)
    monkeypatch.setattr(orch, "get_models", lambda: (None, "MODEL"))
    monkeypatch.setattr(orch, "ts_prefix", lambda: "ts")
    monkeypatch.setattr(orch, "save_text", lambda *a, **k: None)
    monkeypatch.setattr(orch, "cancel_unpositioned_limits", lambda e: None)
    monkeypatch.setattr(orch, "remove_unmapped_limit_files", lambda e: None)
    monkeypatch.setattr(orch, "cancel_unpositioned_stops", lambda e: None)
    monkeypatch.setattr(orch, "env_int", lambda k, d: 10)
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: {f"p{i}" for i in range(11)})
    build_called = {}

    def fake_build_payload(*a, **k):
        build_called["called"] = True
        return {}

    monkeypatch.setattr(orch, "build_payload", fake_build_payload)

    res = orch.run(run_live=True, ex=ex)

    assert not build_called.get("called")
    assert res == {
        "ts": "ts",
        "live": True,
        "capital": 1000.0,
        "coins": [],
        "placed": [],
        "closed": [],
        "moved_sl": [],
        "closed_partial": [],
    }


@pytest.mark.parametrize("side,exit_side", [("buy", "sell"), ("sell", "buy")])
def test_place_sl_tp(side, exit_side):
    ex = CaptureExchange()
    orch._place_sl_tp(ex, "BTC/USDT", side, 10, 1, 2, 3, 4)
    assert ex.cancelled == []
    assert ex.orders == [
        (
            "BTC/USDT",
            "STOP_MARKET",
            exit_side,
            None,
            None,
            {"stopPrice": 1, "closePosition": True},
        ),
        (
            "BTC/USDT",
            "LIMIT",
            exit_side,
            3.0,
            2,
            {"reduceOnly": True},
        ),
        (
            "BTC/USDT",
            "LIMIT",
            exit_side,
            5.0,
            3,
            {"reduceOnly": True},
        ),
        (
            "BTC/USDT",
            "TAKE_PROFIT_MARKET",
            exit_side,
            2.0,
            None,
            {"stopPrice": 4, "reduceOnly": True},
        ),
    ]


class ExistingStopExchange(CaptureExchange):
    def fetch_open_orders(self, symbol):
        return [{"id": "old1", "info": {"closePosition": True}}]


def test_place_sl_tp_cancels_existing():
    ex = ExistingStopExchange()
    orch._place_sl_tp(ex, "BTC/USDT", "buy", 10, 1, 2, 3, 4)
    assert ex.cancelled == [("old1", "BTC/USDT")]
    assert len(ex.orders) == 4


def test_add_sl_tp_from_json(tmp_path, monkeypatch):
    limit_dir = tmp_path / "limit"
    limit_dir.mkdir()
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", limit_dir)
    data = {
        "pair": "BTCUSDT",
        "order_id": "1",
        "side": "buy",
        "limit": 1,
        "qty": 10,
        "sl": 0.9,
        "tp1": 1.1,
        "tp2": 1.2,
        "tp3": 1.3,
    }
    (limit_dir / "BTCUSDT.json").write_text(json.dumps(data))
    ex = FilledExchange()
    orch.add_sl_tp_from_json(ex)
    assert not (limit_dir / "BTCUSDT.json").exists()
    assert ex.orders == [
        (
            "BTC/USDT",
            "STOP_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 0.9, "closePosition": True},
        ),
        (
            "BTC/USDT",
            "LIMIT",
            "sell",
            3.0,
            1.1,
            {"reduceOnly": True},
        ),
        (
            "BTC/USDT",
            "LIMIT",
            "sell",
            5.0,
            1.2,
            {"reduceOnly": True},
        ),
        (
            "BTC/USDT",
            "TAKE_PROFIT_MARKET",
            "sell",
            2.0,
            None,
            {"stopPrice": 1.3, "reduceOnly": True},
        ),
    ]


class BreakEvenExchange(CaptureExchange):
    def __init__(self):
        super().__init__()
        self.cancelled = []

    def fetch_positions(self):
        return [{"symbol": "BTC/USDT", "contracts": 1, "entryPrice": 100}]

    def fetch_open_orders(self, symbol):
        return [
            {
                "id": "sl1",
                "symbol": symbol,
                "reduceOnly": True,
                "stopPrice": 90,
            }
        ]

    def fetch_ticker(self, symbol):
        return {"last": 110}

    def cancel_order(self, oid, sym):
        self.cancelled.append((oid, sym))


def test_move_sl_to_entry(monkeypatch):
    ex = BreakEvenExchange()
    orch.move_sl_to_entry(ex)
    assert ex.cancelled == [("sl1", "BTC/USDT")]
    assert ex.orders == [
        (
            "BTC/USDT",
            "STOP_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 100, "closePosition": True},
        )
    ]


class BreakEvenExchangeShort(CaptureExchange):
    def __init__(self):
        super().__init__()
        self.cancelled = []

    def fetch_positions(self):
        return [{"symbol": "BTC/USDT", "contracts": -1, "entryPrice": 100}]

    def fetch_open_orders(self, symbol):
        return [
            {
                "id": "sl1",
                "symbol": symbol,
                "reduceOnly": True,
                "stopPrice": 110,
            }
        ]

    def fetch_ticker(self, symbol):
        return {"last": 90}

    def cancel_order(self, oid, sym):
        self.cancelled.append((oid, sym))


def test_move_sl_to_entry_short(monkeypatch):
    ex = BreakEvenExchangeShort()
    orch.move_sl_to_entry(ex)
    assert ex.cancelled == [("sl1", "BTC/USDT")]
    assert ex.orders == [
        (
            "BTC/USDT",
            "STOP_MARKET",
            "buy",
            None,
            None,
            {"stopPrice": 100, "closePosition": True},
        )
    ]


class BreakEvenExchangeTrigger(CaptureExchange):
    def __init__(self):
        super().__init__()
        self.cancelled = []

    def fetch_positions(self):
        return [{"symbol": "BTC/USDT", "contracts": 1, "entryPrice": 100}]

    def fetch_open_orders(self, symbol):
        return [
            {
                "id": "sl1",
                "symbol": symbol,
                "reduceOnly": True,
                "triggerPrice": 90,
            }
        ]

    def fetch_ticker(self, symbol):
        return {"last": 110}

    def cancel_order(self, oid, sym):
        self.cancelled.append((oid, sym))


def test_move_sl_to_entry_trigger(monkeypatch):
    ex = BreakEvenExchangeTrigger()
    orch.move_sl_to_entry(ex)
    assert ex.cancelled == [("sl1", "BTC/USDT")]
    assert ex.orders == [
        (
            "BTC/USDT",
            "STOP_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 100, "closePosition": True},
        )
    ]


class StaleExchange:
    def __init__(self):
        self.options = {}
        self.cancelled = []

    def fetch_open_orders(self):
        return [
            {
                "id": "1",
                "symbol": "BTC/USDT",
                "type": "limit",
                "timestamp": 1,
                "reduceOnly": False,
            }
        ]

    def cancel_order(self, oid, symbol):
        self.cancelled.append((oid, symbol))


def test_cancel_unpositioned_limits_clears_json(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "BTCUSDT.json").write_text("{}")
    ex = StaleExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.cancel_unpositioned_limits(ex, max_age_sec=0)
    assert ex.cancelled == [("1", "BTC/USDT")]
    assert not (tmp_path / "BTCUSDT.json").exists()


def test_cancel_unpositioned_limits_skips_when_position(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "BTCUSDT.json").write_text("{}")
    ex = StaleExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: {"BTCUSDT"})
    orch.cancel_unpositioned_limits(ex, max_age_sec=0)
    assert ex.cancelled == []
    assert (tmp_path / "BTCUSDT.json").exists()


class SecTimestampExchange:
    def __init__(self):
        self.options = {}
        self.cancelled = []

    def fetch_open_orders(self):
        return [
            {
                "id": "1",
                "symbol": "BTC/USDT",
                "type": "limit",
                "timestamp": time.time(),
                "reduceOnly": False,
            }
        ]

    def cancel_order(self, oid, symbol):
        self.cancelled.append((oid, symbol))


def test_cancel_unpositioned_limits_handles_second_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "BTCUSDT.json").write_text("{}")
    ex = SecTimestampExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.cancel_unpositioned_limits(ex, max_age_sec=60)
    assert ex.cancelled == []
    assert (tmp_path / "BTCUSDT.json").exists()


class StopExchange:
    def __init__(self):
        self.options = {}
        self.cancelled = []

    def fetch_open_orders(self):
        return [
            {
                "id": "1",
                "symbol": "BTC/USDT",
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
    assert ex.cancelled == [("1", "BTC/USDT")]


class StopExchangeTrigger:
    def __init__(self):
        self.options = {}
        self.cancelled = []

    def fetch_open_orders(self):
        return [
            {
                "id": "1",
                "symbol": "BTC/USDT",
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
    assert ex.cancelled == [("1", "BTC/USDT")]


def test_cancel_unpositioned_stops_skips_when_position(monkeypatch):
    ex = StopExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: {"BTCUSDT"})
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
        return [{"symbol": "BTC/USDT", "type": "limit"}]


def test_remove_unmapped_limit_files_clears_json(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "BTCUSDT.json").write_text("{}")
    ex = NoOrderExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.remove_unmapped_limit_files(ex)
    assert not (tmp_path / "BTCUSDT.json").exists()


def test_remove_unmapped_limit_files_skips_when_order(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "BTCUSDT.json").write_text("{}")
    ex = OpenOrderExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    orch.remove_unmapped_limit_files(ex)
    assert (tmp_path / "BTCUSDT.json").exists()


def test_cancel_expired_limit_orders(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    data = {
        "pair": "BTCUSDT",
        "order_id": "1",
        "expiry": 1,
        "ts": time.time() - 2,
    }
    (tmp_path / "BTCUSDT.json").write_text(json.dumps(data))

    class Ex:
        def __init__(self):
            self.cancelled = []

        def fetch_order(self, oid, sym):
            return {"status": "open"}

        def cancel_order(self, oid, sym):
            self.cancelled.append((oid, sym))

    ex = Ex()
    orch.cancel_expired_limit_orders(ex)
    assert ex.cancelled == [("1", "BTC/USDT")]
    assert not (tmp_path / "BTCUSDT.json").exists()
