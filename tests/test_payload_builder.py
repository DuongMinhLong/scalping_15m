import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import payload_builder  # noqa: E402
import requests  # noqa: E402


class DummyResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def test_news_snapshot(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        assert "auth_token" in params
        data = {
            "macro": "m" * 300,
            "crypto": "c" * 10,
            "unlock": "u",
        }
        return DummyResponse(data)

    monkeypatch.setenv("NEWS_API_KEY", "key")
    monkeypatch.setattr(requests, "get", fake_get)
    snap = payload_builder.news_snapshot()
    assert snap == {
        "macro": "m" * payload_builder.MAX_NEWS_LEN,
        "crypto": "c" * 10,
        "unlock": "u",
    }
