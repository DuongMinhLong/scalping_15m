from positions import positions_snapshot


class DummyExchange:
    def fetch_positions(self):
        return [
            {
                "symbol": "BTC/USDT:USDT",
                "contracts": 1,
                "entryPrice": 100,
                "unrealizedPnl": 5,
            }
        ]

    def fetch_open_orders(self, symbol):
        return [
            {"info": {"closePosition": True, "stopPrice": 90}},
            {"info": {"closePosition": True, "stopPrice": 110}},
        ]


def test_positions_snapshot_includes_close_position_orders():
    ex = DummyExchange()
    res = positions_snapshot(ex)
    assert len(res) == 1
    pos = res[0]
    assert pos["pair"] == "BTCUSDT"
    assert pos["qty"] == 1.0
    assert pos["sl"] == 90.0
    assert pos["tp"] == 110.0
    assert pos["tp1"] == 110.0
