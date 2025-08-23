import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from prompts import build_prompts_mini  # noqa: E402
from env_utils import dumps_min  # noqa: E402


def test_build_prompts_mini_injects_payload():
    payload = {"a": 1}
    pr = build_prompts_mini(payload)
    dumped = dumps_min(payload)
    assert dumped in pr["user"]
    assert pr["user"].count(dumped) == 1
    assert "{payload}" not in pr["user"]

