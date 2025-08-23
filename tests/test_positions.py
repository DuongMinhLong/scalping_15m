import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from positions import get_open_positions_with_risk


class DummyExchange:
    def fetch_positions(self):
        return [
            {"symbol": "BTC/USDT", "contracts": "1", "entryPrice": "30000"},
            {"symbol": "ETH/USDT", "contracts": "1", "entryPrice": "2000"},
            {"symbol": "XRP/USDT", "contracts": "0", "entryPrice": "0"},
        ]

    def fetch_open_orders(self):
        return [
            {"symbol": "BTC/USDT", "type": "stop", "stopPrice": "30000"},
            {"symbol": "ETH/USDT", "type": "stop", "stopPrice": "1900"},
        ]


def test_get_open_positions_with_risk():
    pairs, risk = get_open_positions_with_risk(DummyExchange())
    assert pairs == {"BTCUSDT", "ETHUSDT"}
    assert risk["BTCUSDT"] is True
    assert risk["ETHUSDT"] is False
    assert "XRPUSDT" not in pairs
