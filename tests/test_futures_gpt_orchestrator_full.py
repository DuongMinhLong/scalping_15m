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


def test_run_skips_gpt_when_positions(monkeypatch):
    monkeypatch.setattr(orch, "load_env", lambda: None)
    monkeypatch.setattr(orch, "get_models", lambda: (None, "MODEL"))
    monkeypatch.setattr(orch, "ts_prefix", lambda: "ts")

    def fake_save_text(path, text):
        fake_save_text.saved[path] = text

    fake_save_text.saved = {}
    monkeypatch.setattr(orch, "save_text", fake_save_text)
    monkeypatch.setattr(orch, "get_open_position_pairs", lambda ex: {"ETHUSDT"})

    def boom(*args, **kwargs):  # should never be called
        raise AssertionError("should not be called")

    monkeypatch.setattr(orch, "build_payload", boom)
    monkeypatch.setattr(orch, "send_openai", boom)

    res = orch.run(run_live=False, ex=DummyExchange())

    assert res == {"ts": "ts", "capital": 1000.0, "coins": [], "placed": []}
    assert "ts_orders.json" in fake_save_text.saved
    data = json.loads(fake_save_text.saved["ts_orders.json"])
    assert data["reason"] == "existing_positions"
