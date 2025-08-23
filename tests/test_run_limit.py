import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("OPENAI_API_KEY", "test")

import futures_gpt_orchestrator_full as fgo


def test_run_limits_new_orders(monkeypatch):
    monkeypatch.setattr(fgo, "load_env", lambda: None)
    monkeypatch.setattr(fgo, "get_models", lambda: ("nano", "mini"))
    monkeypatch.setattr(fgo, "save_text", lambda *a, **k: None)
    monkeypatch.setattr(fgo, "ts_prefix", lambda: "0")
    monkeypatch.setattr(fgo, "call_locked", lambda func, *a, **k: func(*a, **k))

    class DummyExchange:
        def fetch_balance(self):
            return {"total": {"USDT": 1000}}

    monkeypatch.setattr(fgo, "make_exchange", lambda: DummyExchange())

    def fake_get_open_positions_with_risk(ex):
        pairs = {f"P{i}USDT" for i in range(9)}
        risk = {p: False for p in pairs}
        return pairs, risk

    monkeypatch.setattr(fgo, "get_open_positions_with_risk", fake_get_open_positions_with_risk)

    def fake_build_payload(ex, limit, exclude_pairs=None):
        return {
            "time": 0,
            "eth": {},
            "coins": [{"pair": "AAAUSDT"}, {"pair": "BBBUSDT"}, {"pair": "CCCUSDT"}],
        }

    monkeypatch.setattr(fgo, "build_payload", fake_build_payload)
    monkeypatch.setattr(fgo, "build_prompts_nano", lambda payload: {"system": "", "user": ""})
    monkeypatch.setattr(fgo, "build_prompts_mini", lambda payload: {"system": "", "user": ""})

    count = {"n": 0}

    def fake_send_openai(system, user, model):
        count["n"] += 1
        if count["n"] == 1:
            return '{"keep": ["AAAUSDT", "BBBUSDT", "CCCUSDT"]}'
        return "mini_output"

    monkeypatch.setattr(fgo, "send_openai", fake_send_openai)
    monkeypatch.setattr(fgo, "extract_content", lambda resp: resp)

    def fake_parse_mini_actions(text):
        return [
            {
                "pair": "AAAUSDT",
                "entry": 1.0,
                "sl": 0.9,
                "tp": 1.1,
                "qty": 1.0,
                "side": "buy",
            },
            {
                "pair": "BBBUSDT",
                "entry": 1.0,
                "sl": 0.9,
                "tp": 1.1,
                "qty": 1.0,
                "side": "buy",
            },
            {
                "pair": "CCCUSDT",
                "entry": 1.0,
                "sl": 0.9,
                "tp": 1.1,
                "qty": 1.0,
                "side": "buy",
            },
        ]

    monkeypatch.setattr(fgo, "parse_mini_actions", fake_parse_mini_actions)
    monkeypatch.setattr(fgo, "enrich_tp_qty", lambda ex, acts, capital: acts)

    result = fgo.run(run_live=False, limit=20)
    assert [c["pair"] for c in result["coins"]] == ["AAAUSDT"]
