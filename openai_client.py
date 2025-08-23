"""Thin wrapper around the OpenAI chat completion API."""

from __future__ import annotations

import os
import re
from threading import Lock
from typing import Any, Dict, Optional

from openai import OpenAI


CLIENT = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
CLIENT_LOCK = Lock()


def send_openai(system_text: str, user_text: str, model: str) -> Dict[str, Any]:
    """Send a chat completion request and return the raw response dict."""

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "response_format": {"type": "text"},
    }
    with CLIENT_LOCK:
        resp = CLIENT.chat.completions.create(**body)
    try:
        return resp.to_dict()
    except Exception:
        return resp


def extract_content(resp: Dict[str, Any]) -> str:
    """Extract message content from a chat completion response."""

    if not resp or not isinstance(resp, dict):
        return ""
    choices = resp.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message") or {}).get("content") or ""


def try_extract_json(text: Any) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of the first JSON object found in ``text``."""

    if not isinstance(text, str):
        return None
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        import json

        return json.loads(match.group(0))
    except Exception:
        return None

