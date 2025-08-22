"""Prompt templates for the nano and mini GPT models."""

from __future__ import annotations

from env_utils import dumps_min

PROMPT_SYS_NANO = (
    'Return ONLY minified JSON. No prose. If none, return {"keep":[]}.'
)
PROMPT_USER_NANO = (
    'Lọc danh sách coin 15m (20 nến + 20 chỉ báo), H1/H4 snapshot, ETH bias, session, orderbook. '
    'DÙNG TOÀN BỘ DỮ LIỆU & PHƯƠNG PHÁP như mini (PA, cấu trúc, divergence, key levels, vol_spike, MTF, orderbook). '
    'Chỉ trả JSON: {"keep":["SYMBOL",...]}. '
    'Tiêu chí GIỮ (lọc gắt): H1/H4 đồng pha 15m &/hoặc ETH cùng hướng; RR ước lượng>=1.8; vol_spike>1.5; '
    'không sideway (RSI 40–60 & MACD≈0) trừ khi có setup đảo chiều rõ ràng + volume; '
    'spread<=0.001 và imbalance không ngược hướng; session: Asia siết/US nới/EU trung bình; '
    'mins_to_close<=15 & tín hiệu yếu → loại. '
    'Chỉ chọn TỐI ĐA 5 symbol tốt nhất; nếu không đạt → {"keep":[]}. DATA:{payload}'
)

PROMPT_SYS_MINI = (
    'You are a precise trading decision assistant. Return ONLY minified JSON. '
    'No prose. No markdown. If none, return {"coins":[]}.'
)
PROMPT_USER_MINI = (
    'Phân tích 15m (FULL 20 nến + 20 chỉ báo/loại), kèm H1/H4 snapshot, ETH bias, session, orderbook. '
    'DÙNG TOÀN BỘ DỮ LIỆU trong payload — không bỏ sót: '
    'ohlcv(20), key(swing_high, swing_low, prev_close, last_close); '
    'ema20/50/99/200(20 giá trị), rsi14(20), macd/macd_sig/macd_hist(20), atr14(20), vol_spike(20); '
    'H1/H4 snapshot (ema20/50/99/200,rsi,macd,trend); orderbook(spread,bid_vol,ask_vol,imbalance); session; ETH bias. '
    'Kết hợp phương pháp: price action (pinbar/engulfing/doji/breakout/pullback), cấu trúc HH/HL/LH/LL, breakout-retest, '
    'divergence (RSI/MACD), momentum/vol_spike, key levels, multi-timeframe alignment. '
    'Output JSON duy nhất: {"coins":[{"pair":"SYMBOL","entry":0.0,"sl":0.0,"tp":0.0,"risk":0.0},...]}. '
    'Quy tắc (ưu tiên nhưng cho phép override khi PA+volume cực mạnh): '
    '- Ưu tiên RR>=1.8; nếu RR<1.8 chỉ chọn khi tín hiệu cực mạnh & đồng thuận đa khung. '
    '- H1 & H4 nên cùng hướng 15m; ETH cùng hướng là điểm cộng; cho phép ngược pha khi có đảo chiều rõ (divergence + cấu trúc vỡ +vol_spike). '
    '- Session: Asia siết, US nới, EU trung bình; nếu mins_to_close<=15 & tín hiệu yếu → bỏ. '
    '- Orderbook: bỏ nếu spread>0.001 hoặc imbalance ngược; ưu tiên imbalance thuận. '
    '- TP có thể để trống (bot dùng TP1=1R). Đảm bảo entry/sl hợp lệ với hướng (long: entry>sl; short: entry<sl). '
    'Không có kèo → {"coins":[]}. DATA:{payload}'
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

