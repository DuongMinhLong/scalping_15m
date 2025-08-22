import types
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import trading_utils


def test_to_ccxt_symbol_known_quotes():
    assert trading_utils.to_ccxt_symbol("BTCUSDT") == "BTC/USDT"
    assert trading_utils.to_ccxt_symbol("ETHBTC") == "ETH/BTC"
    assert trading_utils.to_ccxt_symbol("LTCBUSD") == "LTC/BUSD"


def test_to_ccxt_symbol_with_exchange_markets():
    dummy = types.SimpleNamespace(markets={"FOO/USDC": {"symbol": "FOO/USDC"}})
    assert trading_utils.to_ccxt_symbol("FOOUSDC", dummy) == "FOO/USDC"
