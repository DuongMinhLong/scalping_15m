import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import payload_builder as pb


class DummyExchange:
    pass


def test_build_payload_uses_top_volume(monkeypatch):
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [])
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(
        pb,
        "cache_top_by_qv",
        lambda ex, limit=10, min_qv=0: ["AAA/USDT:USDT", "BBB/USDT:USDT"],
    )
    monkeypatch.setattr(pb, "top_by_market_cap", lambda limit=200: ["AAA", "BBB"])
    monkeypatch.setattr(pb, "_snap_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=2, min_qv=0)
    pairs = {c["p"] for c in payload["coins"]}
    assert pairs == {"AAAUSDT", "BBBUSDT"}
    assert "time" in payload and "eth" in payload


def test_build_payload_handles_numeric_prefix(monkeypatch):
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [])
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(
        pb,
        "cache_top_by_qv",
        lambda ex, limit=10, min_qv=0: ["1000PEPE/USDT:USDT"],
    )
    monkeypatch.setattr(pb, "top_by_market_cap", lambda limit=200: ["PEPE"])
    monkeypatch.setattr(pb, "_snap_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=1, min_qv=0)
    pairs = {c["p"] for c in payload["coins"]}
    assert pairs == {"1000PEPEUSDT"}
    assert "time" in payload and "eth" in payload


def test_build_payload_skips_positions(monkeypatch):
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [{"pair": "BBBUSDT"}])
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(
        pb,
        "cache_top_by_qv",
        lambda ex, limit=10, min_qv=0: [
            "CCC/USDT:USDT",
            "BBB/USDT:USDT",
            "AAA/USDT:USDT",
        ],
    )
    monkeypatch.setattr(pb, "top_by_market_cap", lambda limit=200: ["CCC", "BBB", "AAA"])
    monkeypatch.setattr(pb, "_snap_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=2, min_qv=0)
    pairs = [c["p"] for c in payload["coins"]]
    assert pairs == ["CCCUSDT", "AAAUSDT"]
