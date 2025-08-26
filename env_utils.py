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


def save_text(path: str, text: str, folder: str = "outputs") -> None:
    """
    Persist text to ``folder/path`` using UTF-8 encoding.
    Tự tạo folder nếu chưa tồn tại.
    """
    # Tạo đối tượng Path trỏ đến folder + filename
    folder_path = Path(folder)
    folder_path.mkdir(parents=True, exist_ok=True)  # đảm bảo folder tồn tại

    file_path = folder_path / path
    file_path.write_text(text, encoding="utf-8")



def rfloat(value: Any, nd: int = 6) -> float | None:
    """Return ``value`` rounded to ``nd`` significant digits.

    The default precision was lowered from 8 to 6 digits to keep price
    values compact in generated payloads while remaining sufficiently
    accurate for analysis.

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


def rprice(value: Any) -> float | None:
    """Round price ``value`` using adaptive decimal places.

    ``value`` above ``100`` uses two decimals, between ``1`` and ``100``
    three decimals, and below ``1`` four decimals.  Non-finite inputs yield
    ``None``.
    """

    try:
        if value is None or (
            isinstance(value, float) and (math.isnan(value) or math.isinf(value))
        ):
            return None
        v = float(value)
        av = abs(v)
        if av >= 100:
            return round(v, 2)
        if av >= 1:
            return round(v, 3)
        return round(v, 4)
    except Exception:
        return None


def compact_price(arr: List[Any]) -> List[float | None]:
    """Apply :func:`rprice` to every element in ``arr``."""

    return [rprice(v) for v in arr]


def compact(arr: List[Any], nd: int = 6) -> List[float | None]:
    """Apply :func:`rfloat` to every element in ``arr``."""

    return [rfloat(v, nd) for v in arr]


def human_num(value: Any, nd: int = 3) -> float | str | None:
    """Return ``value`` formatted with K/M/B/T suffixes to save tokens.

    Values below ``1e3`` are returned as floats. Larger magnitudes are
    represented as compact strings such as ``312M``.
    """

    try:
        n = float(value)
    except Exception:
        return None

    for factor, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= factor:
            val = rfloat(n / factor, nd)
            if val is None:
                return None
            return f"{val:g}{suffix}"

    return rfloat(n, nd)


def drop_empty(obj: Any) -> Any:
    """Recursively drop ``None``/empty values from lists and dictionaries."""

    if isinstance(obj, dict):
        return {k: drop_empty(v) for k, v in obj.items() if v not in (None, "", [], {})}
    if isinstance(obj, list):
        return [drop_empty(x) for x in obj if x not in (None, "", [], {})]
    return obj

