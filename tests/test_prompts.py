import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from prompts import build_prompts_mini, build_prompts_m15  # noqa: E402
from env_utils import dumps_min  # noqa: E402


def test_build_prompts_mini_injects_payload():
    payload = {"a": 1}
    pr = build_prompts_mini(payload)
    dumped = dumps_min(payload)
    assert dumped in pr["user"]
    assert pr["user"].count(dumped) == 1
    assert "{payload}" not in pr["user"]


def test_build_prompts_m15_injects_data():
    payload = {
        "atr_4h": 1.0,
        "atr_1h": 0.5,
        "data_15m": [{"time": "t", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
    }
    pr = build_prompts_m15(payload)
    dumped = dumps_min(payload["data_15m"])
    user = pr["messages"][1]["content"]
    assert dumped in user
    assert "ATR 4H: 1.0" in user
    assert "ATR 1H: 0.5" in user
    assert pr["model"] == "gpt-5"
    assert pr["temperature"] == 0.3

