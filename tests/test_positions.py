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


class DummyExchangeNoStops:
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
        return []


def test_positions_snapshot_includes_sl_key_without_stop_orders():
    ex = DummyExchangeNoStops()
    res = positions_snapshot(ex)
    assert len(res) == 1
    pos = res[0]
    assert "sl" in pos
    assert pos["sl"] is None


class DummyExchangeTrigger:
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
            {"info": {"closePosition": True, "triggerPrice": 90}},
            {"info": {"closePosition": True, "triggerPrice": 110}},
        ]


def test_positions_snapshot_handles_trigger_price():
    ex = DummyExchangeTrigger()
    res = positions_snapshot(ex)
    assert len(res) == 1
    pos = res[0]
    assert pos["sl"] == 90.0
    assert pos["tp"] == 110.0


class DummyExchangeAltFields:
    def fetch_positions(self):
        return [
            {
                "symbol": "ETH/USDT:USDT",
                "size": 2,
                "avgPrice": "2000",
                "unrealizedPnl": 10,
            }
        ]

    def fetch_open_orders(self, symbol):
        return []


def test_positions_snapshot_handles_size_and_avgprice():
    ex = DummyExchangeAltFields()
    res = positions_snapshot(ex)
    assert len(res) == 1
    pos = res[0]
    assert pos["pair"] == "ETHUSDT"
    assert pos["qty"] == 2.0
    assert pos["entry"] == 2000.0


class DummyExchangePairsAlt:
    def fetch_positions(self):
        return [
            {"symbol": "ETH/USDT:USDT", "size": 1}
        ]


def test_get_open_position_pairs_supports_size():
    from positions import get_open_position_pairs

    ex = DummyExchangePairsAlt()
    res = get_open_position_pairs(ex)
    assert res == {"ETHUSDT"}


class DummyExchangeTopLevelClose:
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
            {"closePosition": True, "stopLossPrice": 90},
            {"closePosition": True, "takeProfitPrice": 110},
        ]


def test_positions_snapshot_handles_top_level_close_and_price_fields():
    ex = DummyExchangeTopLevelClose()
    res = positions_snapshot(ex)
    assert len(res) == 1
    pos = res[0]
    assert pos["sl"] == 90.0
    assert pos["tp"] == 110.0
