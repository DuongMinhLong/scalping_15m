import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import payload_builder as pb


class DummyExchange:
    pass


def test_build_payload_fills_from_market_cap(monkeypatch):
    monkeypatch.setattr(pb, "positions_snapshot", lambda ex: [])
    monkeypatch.setattr(pb, "eth_bias", lambda ex: {})
    monkeypatch.setattr(pb, "news_snapshot", lambda: {})
    monkeypatch.setattr(pb, "coin_payload", lambda ex, sym: {"pair": pb.norm_pair_symbol(sym)})
    monkeypatch.setattr(pb, "top_by_qv", lambda ex, lim: ["AAA/USDT:USDT"])
    monkeypatch.setattr(pb, "top_by_market_cap", lambda lim: ["AAA", "BBB"])
    monkeypatch.setattr(pb, "load_usdtm", lambda ex: {"AAA/USDT:USDT": {}, "BBB/USDT:USDT": {}})

    payload = pb.build_payload(DummyExchange(), limit=2)
    pairs = {c["pair"] for c in payload["coins"]}
    assert pairs == {"AAAUSDT", "BBBUSDT"}
