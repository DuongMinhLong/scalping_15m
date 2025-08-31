import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import payload_builder as pb


class DummyExchange:
    pass


def test_build_payload_from_env_pairs(monkeypatch):
    monkeypatch.setenv("COIN_PAIRS", "AAA,BBB")
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [])
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(pb, "_tf_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=2)
    pairs = {c["p"] for c in payload["coins"]}
    assert pairs == {"AAAUSDT", "BBBUSDT"}
    assert "time" in payload and "eth" not in payload


def test_build_payload_handles_numeric_prefix(monkeypatch):
    monkeypatch.setenv("COIN_PAIRS", "1000PEPE")
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [])
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(pb, "_tf_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=1)
    pairs = {c["p"] for c in payload["coins"]}
    assert pairs == {"1000PEPEUSDT"}
    assert "time" in payload and "eth" not in payload


def test_build_payload_skips_positions(monkeypatch):
    monkeypatch.setenv("COIN_PAIRS", "CCCUSDT,BBBUSDT,AAAUSDT")
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [{"pair": "BBBUSDT"}])
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(pb, "_tf_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=2)
    pairs = {c["p"] for c in payload["coins"]}
    assert pairs == {"CCCUSDT", "AAAUSDT", "BBBUSDT"}


def test_build_payload_preserves_sl(monkeypatch):
    monkeypatch.setenv("COIN_PAIRS", "")

    def fake_positions_snapshot(ex):
        return [
            {"pair": "AAAUSDT", "side": "buy", "entry": 1.0, "sl": None},
            {"pair": "BBBUSDT", "side": "sell", "entry": 2.0, "sl": 1.5},
        ]

    monkeypatch.setattr(pb, "positions_snapshot", fake_positions_snapshot)
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(pb, "_tf_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=0)
    positions = payload["positions"]
    assert "sl" in positions[0] and positions[0]["sl"] is None
    assert positions[1]["sl"] == 1.5


def test_build_payload_keeps_empty_positions(monkeypatch):
    monkeypatch.setenv("COIN_PAIRS", "")
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [])
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(pb, "_tf_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=0)
    assert "positions" in payload and payload["positions"] == []
