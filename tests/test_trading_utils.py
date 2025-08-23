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
        '"coins":[{"pair":"BTCUSDT","entry":1,"sl":0.9,"tp2":1.1}],'
        '"close_all":[{"pair":"ETHUSDT"}],'
        '"close_partial":[{"pair":"LTCUSDT","pct":25}]}'
    )
    res = trading_utils.parse_mini_actions(text)
    assert res["coins"] and res["coins"][0]["pair"] == "BTCUSDT"
    assert res["close_all"] == [{"pair": "ETHUSDT"}]
    assert res["close_partial"] == [{"pair": "LTCUSDT", "pct": 25.0}]
