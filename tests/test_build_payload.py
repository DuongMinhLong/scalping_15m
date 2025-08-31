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
