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
                "https://financialmodelingprep.com/api/v3/economic_calendar?from=2025-09-03&to=2025-09-04&apikey=SECRET",
            ).prepare()
            response = requests.Response()
            response.status_code = 403
            raise requests.HTTPError("403 Client Error", request=request, response=response)

    with patch("events.requests.get", return_value=FakeResp()):
        with patch.dict(os.environ, {"FMP_API_KEY": "SECRET"}):
            caplog.set_level(logging.WARNING)
            events.event_snapshot()
    assert "SECRET" not in caplog.text
    assert "apikey=***" in caplog.text
