import types
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from exchange_utils import funding_rate


def test_funding_rate_returns_fields():
    def _fetch(symbol):
        return {"fundingRate": "0.0005", "nextFundingTime": 1234567890}

    dummy = types.SimpleNamespace(fetch_funding_rate=_fetch)
    snap = funding_rate(dummy, "FOO/USDT")
    assert snap["rate"] == 0.0005
    assert snap["next_funding"] == 1234567890

