"""Thin wrapper around the OpenAI chat completion API."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, Optional

from openai import (
    APIConnectionError,
    APITimeoutError,
    OpenAI,
)

logger = logging.getLogger(__name__)


API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

CLIENT = OpenAI(api_key=API_KEY)


def send_openai(system_text: str, user_text: str, model: str) -> Dict[str, Any]:
    """Gửi yêu cầu chat completion với cơ chế retry đơn giản."""

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "trade_list",
                "schema": {
                    "type": "object",
                    "properties": {
                        "coins": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "pair": {"type": "string"},
                                    "entry": {"type": "number"},
                                    "sl": {"type": "number"},
                                    "tp1": {"type": "number"},
                                    "tp2": {"type": "number"},
                                    "tp3": {"type": "number"},
                                    "conf": {"type": "number"},
                                },
                                "required": [
                                    "pair", "entry", "sl", "tp1", "tp2", "tp3", "conf"
                                ]
                            }
                        }
                    },
                    "required": ["coins"],
                    "additionalProperties": False
                }
            }
        }
    }
    for attempt in range(3):  # thử tối đa 3 lần
        try:
            resp = CLIENT.chat.completions.create(**body)
            try:
                return resp.to_dict()  # trả về dict nếu có thể
            except Exception:
                return resp  # fallback nguyên bản
        except (APIConnectionError, APITimeoutError) as e:
            if attempt < 2:
                wait = 2 * (attempt + 1)
                logger.warning("send_openai lỗi kết nối %s, đợi %ss rồi thử lại", e, wait)
                time.sleep(wait)
                continue
            logger.error("send_openai lỗi kết nối: %s", e)
            raise
        except Exception as e:
            code = getattr(e, "status", None) or getattr(e, "http_status", None)
            if attempt < 2 and (code is None or code >= 500 or code == 429):
                wait = 2 * (attempt + 1)
                logger.warning(
                    "send_openai lỗi tạm thời %s, đợi %ss rồi thử lại", code, wait
                )
                time.sleep(wait)
                continue
            logger.error("send_openai lỗi vĩnh viễn: %s", e)
            raise


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

