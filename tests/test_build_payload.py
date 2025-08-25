import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import payload_builder as pb


class DummyExchange:
    pass


def test_build_payload_fills_from_market_cap(monkeypatch):
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [])
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(pb, "top_by_qv", lambda ex, lim: ["AAA/USDT:USDT"])
    monkeypatch.setattr(pb, "top_by_market_cap", lambda lim, ttl=3600: ["AAA", "BBB"])
    monkeypatch.setattr(
        pb,
        "load_usdtm",
        lambda ex: {
            "AAA/USDT:USDT": {"base": "AAA"},
            "BBB/USDT:USDT": {"base": "BBB"},
        },
    )
    monkeypatch.setattr(pb, "_snap_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=2)
    pairs = {c["p"] for c in payload["coins"]}
    assert pairs == {"AAAUSDT", "BBBUSDT"}
    assert "time" in payload and "eth" in payload


def test_build_payload_handles_numeric_prefix(monkeypatch):
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [])
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"p": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(pb, "top_by_qv", lambda ex, lim: [])
    monkeypatch.setattr(pb, "top_by_market_cap", lambda lim, ttl=3600: ["PEPE"])
    monkeypatch.setattr(
        pb,
        "load_usdtm",
        lambda ex: {"1000PEPE/USDT:USDT": {"base": "1000PEPE"}},
    )
    monkeypatch.setattr(pb, "_snap_with_cache", lambda *a, **k: {"ema": 0})

    payload = pb.build_payload(DummyExchange(), limit=1)
    pairs = {c["p"] for c in payload["coins"]}
    assert pairs == {"1000PEPEUSDT"}
    assert "time" in payload and "eth" in payload
