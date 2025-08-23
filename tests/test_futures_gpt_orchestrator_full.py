import json
import json
import os
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "test")
import futures_gpt_orchestrator_full as orch  # noqa: E402


class DummyExchange:
    def fetch_balance(self):
        return {"total": {"USDT": 1000}}


def test_run_includes_positions_in_gpt_payload(monkeypatch):
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
            "time": {},
            "eth": {},
            "news": {},
            "coins": [{"pair": "ETHUSDT"}, {"pair": "BTCUSDT"}],
            "positions": [
                {"pair": "ETHUSDT", "entry": 1, "sl": 0.9, "tp1": 1.1, "tp2": 1.2}
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
    monkeypatch.setattr(
        orch,
        "parse_mini_actions",
        lambda text: {"coins": [], "close_all": [], "close_partial": []},
    )
    monkeypatch.setattr(orch, "enrich_tp_qty", lambda ex, coins, capital: coins)

    res = orch.run(run_live=False, ex=DummyExchange())

    assert build_called.get("called")
    payload_str = captured.get("user", "").split("DATA:")[-1]
    data = json.loads(payload_str)
    assert any(c.get("pair") == "ETHUSDT" for c in data.get("coins", []))
    assert any(p.get("pair") == "ETHUSDT" for p in data.get("positions", []))
    assert res == {
        "ts": "ts",
        "live": False,
        "capital": 1000.0,
        "coins": [],
        "close_all": [],
        "close_partial": [],
        "placed": [],
        "closed": [],
    }
    assert "ts_orders.json" in fake_save_text.saved
    data = json.loads(fake_save_text.saved["ts_orders.json"])
    assert "reason" not in data
    assert data["coins"] == []
    assert data["close_all"] == []
    assert data["close_partial"] == []
    assert data["closed"] == []
