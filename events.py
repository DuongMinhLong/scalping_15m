import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests
from urllib.parse import parse_qsl, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# Trading Economics calendar endpoint. Country "All" is included in the
# base URL; start and end dates are appended as path segments.
API_URL = "https://api.tradingeconomics.com/calendar/country/All"

# Trading Economics news endpoint.
NEWS_URL = "https://api.tradingeconomics.com/news"


def _sanitize_url(url: str) -> str:
    if not url:
        return url
    parts = list(urlsplit(url))
    query = dict(parse_qsl(parts[3]))
    for key in ("apikey", "c"):
        if key in query:
            query[key] = "***"
    parts[3] = "&".join(f"{k}={v}" for k, v in query.items())
    return urlunsplit(parts)


def event_snapshot(days: int = 1) -> List[Dict]:
    """Return upcoming economic events using Trading Economics API.

    The function reads ``TE_API_KEY`` from the environment. If it is not set,
    the public ``guest:guest`` key is used and a warning is logged. On network
    or parsing errors an empty list is returned and the error is logged.
    """

    api_key = os.getenv("TE_API_KEY")
    if not api_key:
        logger.warning("TE_API_KEY not set, using guest:guest")
        api_key = "guest:guest"

    now = datetime.now(timezone.utc)
    start = now.strftime("%Y-%m-%d")
    end = (now + timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"c": api_key, "f": "json"}

    try:
        resp = requests.get(f"{API_URL}/{start}/{end}", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        url = _sanitize_url(getattr(e.request, "url", ""))
        status = getattr(e.response, "status_code", "")
        logger.warning("event_snapshot request failed: %s %s", status, url)
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("event_snapshot request failed: %s", e)
        return []

    events: List[Dict] = []
    for item in data if isinstance(data, list) else []:
        try:
            events.append(
                {
                    "time": item.get("Date"),
                    "title": item.get("Event"),
                    "impact": item.get("Importance"),
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("event_snapshot parse error: %s", e)
    return events


def news_snapshot(limit: int = 5) -> List[Dict]:
    """Return latest forex-related news using Trading Economics API.

    Reads ``TE_API_KEY`` from the environment, defaulting to the public
    ``guest:guest`` key if missing. On network or parsing errors, an empty
    list is returned and the error is logged.
    """

    api_key = os.getenv("TE_API_KEY")
    if not api_key:
        logger.warning("TE_API_KEY not set, using guest:guest")
        api_key = "guest:guest"

    params = {"c": api_key, "f": "json"}

    try:
        resp = requests.get(NEWS_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        url = _sanitize_url(getattr(e.request, "url", ""))
        status = getattr(e.response, "status_code", "")
        logger.warning("news_snapshot request failed: %s %s", status, url)
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("news_snapshot request failed: %s", e)
        return []

    news: List[Dict] = []
    for item in data[:limit] if isinstance(data, list) else []:
        try:
            news.append(
                {
                    "time": item.get("Date"),
                    "title": item.get("Title"),
                    "url": item.get("Url"),
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("news_snapshot parse error: %s", e)
    return news
