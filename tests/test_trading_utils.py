import types
import pathlib
import sys
import os

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "test")
import trading_utils


def test_to_ccxt_symbol_known_quotes():
    assert trading_utils.to_ccxt_symbol("BTCUSDT") == "BTC/USDT"
    assert trading_utils.to_ccxt_symbol("ETHBTC") == "ETH/BTC"
    assert trading_utils.to_ccxt_symbol("LTCBUSD") == "LTC/BUSD"


def test_to_ccxt_symbol_with_exchange_markets():
    dummy = types.SimpleNamespace(markets={"FOO/USDC": {"symbol": "FOO/USDC"}})
    assert trading_utils.to_ccxt_symbol("FOOUSDC", dummy) == "FOO/USDC"


def test_parse_mini_actions_handles_close():
    text = (
        "{"
        '"coins":[{"pair":"BTCUSDT","entry":1,"sl":0.9,"tp1":1.05,"tp2":1.1,"tp3":1.2,"conf":8,"rr":2.5}],'
        '"close_all":[{"pair":"ETHUSDT"}],'
        '"close_partial":[{"pair":"LTCUSDT","pct":25}]}'
    )
    res = trading_utils.parse_mini_actions(text)
    assert res["coins"] and res["coins"][0]["pair"] == "BTCUSDT"
    assert res["coins"][0]["tp1"] == 1.05
    assert res["coins"][0]["tp2"] == 1.1
    assert res["coins"][0]["tp3"] == 1.2
    assert res["coins"][0]["conf"] == 8.0
    assert res["coins"][0]["rr"] == 2.5
    assert res["close_all"] == [{"pair": "ETHUSDT"}]
    assert res["close_partial"] == [{"pair": "LTCUSDT", "pct": 25.0}]


def test_enrich_tp_qty_keeps_tps(monkeypatch):
    ex = types.SimpleNamespace(
        market=lambda symbol: {"limits": {"leverage": {"max": 100}}, "contractSize": 1}
    )
    monkeypatch.setattr(trading_utils, "qty_step", lambda e, s: 1)
    monkeypatch.setattr(
        trading_utils,
        "calc_qty",
        lambda capital, rf, entry, sl, step, max_lev, contract: 1,
    )
    monkeypatch.setattr(trading_utils, "infer_side", lambda entry, sl, tp1: "buy")
    acts = [
        {"pair": "BTCUSDT", "entry": 100, "sl": 90, "tp1": 110, "tp2": 115, "tp3": 150}
    ]
    res = trading_utils.enrich_tp_qty(ex, acts, capital=1000)
    assert res[0]["tp1"] == 110
    assert res[0]["tp2"] == 115
    assert res[0]["tp3"] == 150


def test_enrich_tp_qty_skips_when_tp_missing(monkeypatch):
    ex = types.SimpleNamespace(
        market=lambda symbol: {"limits": {"leverage": {"max": 100}}, "contractSize": 1}
    )
    monkeypatch.setattr(trading_utils, "qty_step", lambda e, s: 1)
    monkeypatch.setattr(
        trading_utils,
        "calc_qty",
        lambda capital, rf, entry, sl, step, max_lev, contract: 1,
    )
    monkeypatch.setattr(trading_utils, "infer_side", lambda entry, sl, tp1: "buy")
    acts = [{"pair": "BTCUSDT", "entry": 100, "sl": 90, "tp1": 110}]
    res = trading_utils.enrich_tp_qty(ex, acts, capital=1000)
    assert res == []
