"""Prompt templates for the GPT model."""

from env_utils import dumps_min


PROMPT_SYS_MINI = (
    'You are a precise trading decision assistant. Return ONLY minified JSON. '
    'No prose. No markdown. If none, return {"coins":[]}.'
)
PROMPT_USER_MINI = (
    'Phân tích 1h (20 ohlcv+chỉ báo+sr_levels), H4/D1 snapshot, ETH bias, session, orderbook. '
    'Dùng price action, cấu trúc HH/HL/LH/LL, breakout, divergence, momentum/vol_spike, sr_levels, key level, MTF. '
    'Output JSON: {"coins":[{"pair":"SYMBOL","entry":0.0,"sl":0.0,"tp2":0.0,"risk":0.0},...]}. '
    'Ưu tiên RR>=1.8; cho phép <1.8 khi PA+volume cực mạnh & đồng thuận đa khung. H4/D1 cùng hướng 1h; ETH cùng hướng thêm điểm; '
    'cho phép ngược pha khi có đảo chiều rõ + vol_spike. Session: Asia siết/US nới/EU tb; mins_to_close<=15 & yếu → bỏ. '
    'Orderbook: bỏ nếu spread>0.001 hoặc imbalance ngược. Bot dùng TP1=1R, TP2 nếu thiếu → 2R. '
    'Đảm bảo long entry>sl, short entry<sl. Không kèo → {"coins":[]}. DATA:{payload}'
)


def build_prompts_mini(payload_kept):
    """Return prompt dict for the mini model."""

    return {
        "system": PROMPT_SYS_MINI,
        "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept)),
    }

