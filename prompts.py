"""Prompt templates for the GPT model."""

from env_utils import dumps_min


PROMPT_SYS_MINI = (
    "You are a professional crypto trader. "
    "Analyze market data and output ONLY valid JSON. "
    "No prose. No markdown. If no trade, return {\"coins\":[]}."
)

PROMPT_USER_MINI = (
    "Dữ liệu đầy đủ dưới đây (không bỏ sót trường nào). Phân tích như trader chuyên nghiệp, dùng mọi phương pháp: price action & mô hình nến (pinbar, engulfing, doji, breakout...), EMA20/50/200, RSI, MACD, ATR, volume spike, đa khung (15m/H1/H4), ETH bias, orderbook. "
    "Chỉ chọn lệnh khi conf ≥ 7.0 và RR ≥ 1.8."
    "Chốt lời theo chuẩn R: TP1 = 2R (R = |entry - sl|; với long: TP = entry + k*R; với short: TP = entry - k*R). "
    "Trả về JSON duy nhất dạng {\"coins\":[{\"pair\":\"SYMBOL\",\"entry\":0.0,\"sl\":0.0,\"tp1\":0.0,\"conf\":0.0,\"rr\":0.0}]}; rr là tỷ lệ RR tại TP1, yêu cầu rr ≥ 1.8 "
    "Không có tín hiệu → {\"coins\":[]}. "
    "DATA:{payload}"
)

def build_prompts_mini(payload_kept):
    """Return prompt dict for the mini model."""

    return {
        "system": PROMPT_SYS_MINI,
        "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept)),
    }
