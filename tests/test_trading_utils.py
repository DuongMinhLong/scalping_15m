import types
import pathlib
import sys
import os

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

# ``trading_utils`` indirectly requires an OpenAI API key during import.
# Tests supply a dummy value so the import does not fail.
os.environ.setdefault("OPENAI_API_KEY", "test")

import trading_utils


def test_to_ccxt_symbol_known_quotes():
    assert trading_utils.to_ccxt_symbol("BTCUSDT") == "BTC/USDT"
    assert trading_utils.to_ccxt_symbol("ETHBTC") == "ETH/BTC"
    assert trading_utils.to_ccxt_symbol("LTCBUSD") == "LTC/BUSD"


def test_to_ccxt_symbol_with_exchange_markets():
    dummy = types.SimpleNamespace(markets={"FOO/USDC": {"symbol": "FOO/USDC"}})
    assert trading_utils.to_ccxt_symbol("FOOUSDC", dummy) == "FOO/USDC"
