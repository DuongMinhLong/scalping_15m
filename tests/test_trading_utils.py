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


def test_parse_mini_actions_coins_only():
    text = (
        "{"
        '"coins":[{"pair":"BTCUSDT","entry":1,"sl":0.9,"tp":1.05,"risk":0.1}],'
        '"close":[{"pair":"ETHUSDT"}]}'
    )
    res = trading_utils.parse_mini_actions(text)
    assert res["coins"] and res["coins"][0]["pair"] == "BTCUSDT"
    assert res["coins"][0]["tp"] == 1.05
    assert res["coins"][0]["risk"] == 0.1
    assert "close" not in res


def test_parse_mini_actions_requires_tp():
    text = '{"coins":[{"pair":"BTCUSDT","entry":1,"sl":0.9,"tp1":1.05}]}'
    res = trading_utils.parse_mini_actions(text)
    assert res["coins"] == []


def test_enrich_tp_qty_keeps_tp(monkeypatch):
    ex = types.SimpleNamespace(
        market=lambda symbol: {"limits": {"leverage": {"max": 100}}, "contractSize": 1}
    )
    monkeypatch.setattr(trading_utils, "qty_step", lambda e, s: 1)
    monkeypatch.setattr(
        trading_utils,
        "calc_qty",
        lambda capital, rf, entry, sl, step, max_lev, contract: 1,
    )
    monkeypatch.setattr(trading_utils, "infer_side", lambda entry, sl, tp: "buy")
    acts = [
        {
            "pair": "BTCUSDT",
            "entry": 100,
            "sl": 90,
            "tp": 110,
        }
    ]
    res = trading_utils.enrich_tp_qty(ex, acts, capital=1000)
    assert res[0]["tp"] == 110


def test_enrich_tp_qty_uses_env_default_risk(monkeypatch):
    ex = types.SimpleNamespace(
        market=lambda symbol: {"limits": {"leverage": {"max": 100}}, "contractSize": 1}
    )
    monkeypatch.setattr(trading_utils, "qty_step", lambda e, s: 1)
    monkeypatch.setattr(
        trading_utils,
        "calc_qty",
        lambda capital, rf, entry, sl, step, max_lev, contract: 1,
    )
    monkeypatch.setattr(trading_utils, "infer_side", lambda entry, sl, tp: "buy")
    monkeypatch.setattr(trading_utils, "DEFAULT_RISK_FRAC", 0.02)
    acts = [
        {
            "pair": "BTCUSDT",
            "entry": 100,
            "sl": 90,
            "tp": 110,
        }
    ]
    res = trading_utils.enrich_tp_qty(ex, acts, capital=1000)
    assert res[0]["risk"] == 0.02


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
    monkeypatch.setattr(trading_utils, "infer_side", lambda entry, sl, tp: "buy")
    acts = [{"pair": "BTCUSDT", "entry": 100, "sl": 90}]
    res = trading_utils.enrich_tp_qty(ex, acts, capital=1000)
    assert res == []

