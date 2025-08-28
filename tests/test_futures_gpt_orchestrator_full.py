import json
import os
import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "test")
import futures_gpt_orchestrator_full as orch  # noqa: E402


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
        return {"coins": [{"p": "ETHUSDT"}, {"p": "BTCUSDT"}]}

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
    payload_str = captured.get("user", "").split("DATA:")[-1]
    data = json.loads(payload_str)
    assert any(c.get("p") == "ETHUSDT" for c in data.get("coins", []))
    assert "positions" not in data
    assert res == {
        "ts": "ts",
        "live": False,
        "capital": 1000.0,
        "coins": [],
        "placed": [],
    }
    assert "ts_orders.json" in fake_save_text.saved
    data = json.loads(fake_save_text.saved["ts_orders.json"])
    assert data["coins"] == []
    assert data["placed"] == []


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
                    "tp2": 1.2,
                    "tp3": 1.3,
                    "qty": 1,
                    "qty1": 0.2,
                    "qty2": 0.3,
                }
            ]
        },
    )
    monkeypatch.setattr(orch, "enrich_tp_qty", lambda ex, coins, capital: coins)
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: set())
    monkeypatch.setattr(orch, "cancel_unpositioned_limits", lambda e: None)
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "BTCUSDT.json").write_text("{}")

    orch.run(run_live=True, ex=ex)

    assert ex.cancelled == [("old1", "BTC/USDT"), ("old2", "BTC/USDT")]
    assert len(ex.orders) == 1
    assert not (tmp_path / "BTCUSDT.json").exists()


@pytest.mark.parametrize("side,exit_side", [("buy", "sell"), ("sell", "buy")])
def test_place_sl_tp(side, exit_side):
    ex = CaptureExchange()
    orch._place_sl_tp(ex, "BTC/USDT", side, 2, 3, 0.9, 1.1, 1.2, 1.3)
    assert ex.cancelled == []
    assert ex.orders == [
        (
            "BTC/USDT",
            "STOP_MARKET",
            exit_side,
            None,
            None,
            {"stopPrice": 0.9, "closePosition": True},
        ),
        (
            "BTC/USDT",
            "TAKE_PROFIT_MARKET",
            exit_side,
            2,
            None,
            {"stopPrice": 1.1, "reduceOnly": True},
        ),
        (
            "BTC/USDT",
            "TAKE_PROFIT_MARKET",
            exit_side,
            3,
            None,
            {"stopPrice": 1.2, "reduceOnly": True},
        ),
        (
            "BTC/USDT",
            "TAKE_PROFIT_MARKET",
            exit_side,
            None,
            None,
            {"stopPrice": 1.3, "closePosition": True},
        ),
    ]


class ExistingStopExchange(CaptureExchange):
    def fetch_open_orders(self, symbol):
        return [{"id": "old1", "info": {"closePosition": True}}]


def test_place_sl_tp_cancels_existing():
    ex = ExistingStopExchange()
    orch._place_sl_tp(ex, "BTC/USDT", "buy", 2, 3, 1, 2, 3, 4)
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
        "qty1": 2,
        "qty2": 3,
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
            "TAKE_PROFIT_MARKET",
            "sell",
            2,
            None,
            {"stopPrice": 1.1, "reduceOnly": True},
        ),
        (
            "BTC/USDT",
            "TAKE_PROFIT_MARKET",
            "sell",
            3,
            None,
            {"stopPrice": 1.2, "reduceOnly": True},
        ),
        (
            "BTC/USDT",
            "TAKE_PROFIT_MARKET",
            "sell",
            None,
            None,
            {"stopPrice": 1.3, "closePosition": True},
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
    orch.cancel_unpositioned_limits(ex)
    assert ex.cancelled == [("1", "BTC/USDT")]
    assert not (tmp_path / "BTCUSDT.json").exists()


def test_cancel_unpositioned_limits_skips_when_position(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "LIMIT_ORDER_DIR", tmp_path)
    (tmp_path / "BTCUSDT.json").write_text("{}")
    ex = StaleExchange()
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda e: {"BTCUSDT"})
    orch.cancel_unpositioned_limits(ex)
    assert ex.cancelled == []
    assert (tmp_path / "BTCUSDT.json").exists()
