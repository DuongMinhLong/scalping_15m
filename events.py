import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests
from urllib.parse import parse_qsl, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

API_URL = "https://financialmodelingprep.com/api/v3/economic_calendar"


def _sanitize_url(url: str) -> str:
    if not url:
        return url
    parts = list(urlsplit(url))
    query = dict(parse_qsl(parts[3]))
    if "apikey" in query:
        query["apikey"] = "***"
    parts[3] = "&".join(f"{k}={v}" for k, v in query.items())
    return urlunsplit(parts)


def event_snapshot(days: int = 1) -> List[Dict]:
    """Return upcoming economic events using FinancialModelingPrep API.

    The function reads ``FMP_API_KEY`` from the environment. On network or
    parsing errors an empty list is returned and the error is logged.
    """

    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        logger.warning("FMP_API_KEY not set")
        return []

    now = datetime.now(timezone.utc)
    params = {
        "from": now.strftime("%Y-%m-%d"),
        "to": (now + timedelta(days=days)).strftime("%Y-%m-%d"),
        "apikey": api_key,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=10)
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
                    "time": item.get("date"),
                    "title": item.get("event"),
                    "impact": item.get("impact"),
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("event_snapshot parse error: %s", e)
    return events
