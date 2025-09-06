import logging
import os
from unittest.mock import patch

import events
import requests


def test_event_snapshot_masks_api_key_on_http_error(caplog):
    class FakeResp:
        def raise_for_status(self):
            request = requests.Request(
                "GET",
                "https://api.tradingeconomics.com/calendar/country/All/2025-09-03/2025-09-04?c=SECRET&f=json",
            ).prepare()
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError("403 Client Error", request=request, response=response)

    with patch("events.requests.get", return_value=FakeResp()):
        with patch.dict(os.environ, {"TE_API_KEY": "SECRET"}):
            caplog.set_level(logging.WARNING)
            events.event_snapshot()
    assert "SECRET" not in caplog.text
    assert "c=***" in caplog.text


def test_news_snapshot_masks_api_key_on_http_error(caplog):
    class FakeResp:
        def raise_for_status(self):
            request = requests.Request(
                "GET",
                "https://api.tradingeconomics.com/news?c=SECRET&f=json",
            ).prepare()
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError("403 Client Error", request=request, response=response)

    with patch("events.requests.get", return_value=FakeResp()):
        with patch.dict(os.environ, {"TE_API_KEY": "SECRET"}):
            caplog.set_level(logging.WARNING)
            events.news_snapshot()
    assert "SECRET" not in caplog.text
    assert "c=***" in caplog.text
