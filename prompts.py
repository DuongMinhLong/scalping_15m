"""Prompt templates for the nano and mini GPT models."""

from __future__ import annotations

from env_utils import dumps_min

PROMPT_SYS_NANO = (
    'Return ONLY minified JSON. No prose. If none, return {"keep":[]}.'
)
PROMPT_USER_NANO = (
    'Lọc coin 15m (20 nến+chỉ báo), H1/H4 snapshot, ETH bias, session, orderbook. '
    'Dùng full data & phương pháp mini (PA, cấu trúc, divergence, key level, vol_spike, MTF, orderbook). '
    'Chỉ trả JSON {"keep":["SYMBOL",...]}. '
    'Giữ khi H1/H4 cùng hướng 15m hoặc ETH; RR>=1.8; vol_spike>1.5; tránh sideway (RSI40-60 & MACD~0) trừ đảo chiều rõ; '
    'spread<=0.001, imbalance thuận; session: Asia siết/US nới/EU tb; mins_to_close<=15 & yếu → loại. '
    'Tối đa 5 symbol tốt nhất; không đạt → {"keep":[]}. DATA:{payload}'
)

PROMPT_SYS_MINI = (
    'You are a precise trading decision assistant. Return ONLY minified JSON. '
    'No prose. No markdown. If none, return {"coins":[]}.'
)
PROMPT_USER_MINI = (
    'Phân tích 15m (20 ohlcv+chỉ báo), H1/H4 snapshot, ETH bias, session, orderbook. '
    'Dùng price action, cấu trúc HH/HL/LH/LL, breakout, divergence, momentum/vol_spike, key level, MTF. '
    'Output JSON: {"coins":[{"pair":"SYMBOL","entry":0.0,"sl":0.0,"tp2":0.0,"risk":0.0},...]}. '
    'Ưu tiên RR>=1.8; cho phép <1.8 khi PA+volume cực mạnh & đồng thuận đa khung. H1/H4 cùng hướng 15m; ETH cùng hướng thêm điểm; '
    'cho phép ngược pha khi có đảo chiều rõ + vol_spike. Session: Asia siết/US nới/EU tb; mins_to_close<=15 & yếu → bỏ. '
    'Orderbook: bỏ nếu spread>0.001 hoặc imbalance ngược. Bot dùng TP1=1R, TP2 nếu thiếu → 2R. '
    'Đảm bảo long entry>sl, short entry<sl. Không kèo → {"coins":[]}. DATA:{payload}'
)


def build_prompts_nano(payload_full):
    """Return prompt dict for the nano model."""

    return {
        "system": PROMPT_SYS_NANO,
        "user": PROMPT_USER_NANO.replace("{payload}", dumps_min(payload_full)),
    }


def build_prompts_mini(payload_kept):
    """Return prompt dict for the mini model."""

    return {
        "system": PROMPT_SYS_MINI,
        "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept)),
    }
