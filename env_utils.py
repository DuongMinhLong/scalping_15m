"""Utility helpers for environment configuration and generic tasks.

This module centralises helper functions that were previously spread
throughout the monolithic script.  Functions here are intentionally small
and documented to keep the rest of the codebase clean.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def load_env() -> None:
    """Load variables from a ``.env`` file if :mod:`python-dotenv` exists.

    The function silently falls back to manual parsing when the package is
    not available.  Existing environment variables are preserved.
    """

    try:  # pragma: no cover - optional dependency
        from dotenv import load_dotenv as _load

        _load(override=False)
    except Exception:
        path = Path(".env")
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = [x.strip() for x in line.split("=", 1)]
                if key and val and not os.getenv(key):
                    os.environ[key] = val


def env_int(key: str, default: int) -> int:
    """Read integer configuration from environment."""

    try:
        return int(os.getenv(key, default))
    except Exception:
        return default


def env_bool(key: str, default: bool = False) -> bool:
    """Read boolean configuration from environment."""

    value = str(os.getenv(key, str(default))).strip().lower()
    return value in ("1", "true", "yes", "y", "on")


def get_models() -> tuple[str, str]:
    """Return names of the nano and mini models used for analysis."""

    return os.getenv("NANO_MODEL", "gpt-5-nano"), os.getenv(
        "MINI_MODEL", "gpt-5-mini"
    )


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def now_ms() -> int:
    """Return current UTC timestamp in milliseconds."""

    return int(time.time() * 1000)


def ts_prefix() -> str:
    """Timestamp prefix used when saving files."""

    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def dumps_min(obj: Any) -> str:
    """Minified JSON dumper with UTF-8 support."""

    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def save_text(path: str, text: str) -> None:
    """Persist text to ``path`` using UTF-8 encoding."""

    Path(path).write_text(text, encoding="utf-8")


def rfloat(value: Any, nd: int = 8) -> float | None:
    """Return ``value`` rounded to ``nd`` significant digits.

    ``None`` or non-finite numbers yield ``None``.
    """

    try:
        if value is None or (
            isinstance(value, float) and (math.isnan(value) or math.isinf(value))
        ):
            return None
        return float(f"{value:.{nd}g}")
    except Exception:
        return None


def compact(arr: List[Any], nd: int = 8) -> List[float | None]:
    """Apply :func:`rfloat` to every element in ``arr``."""

    return [rfloat(v, nd) for v in arr]


def drop_empty(obj: Any) -> Any:
    """Recursively drop ``None``/empty values from lists and dictionaries."""

    if isinstance(obj, dict):
        return {k: drop_empty(v) for k, v in obj.items() if v not in (None, "", [], {})}
    if isinstance(obj, list):
        return [drop_empty(x) for x in obj if x not in (None, "", [], {})]
    return obj

