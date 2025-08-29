"""Prompt templates for the GPT model."""

from env_utils import dumps_min


PROMPT_SYS_MINI = (
    "You are a professional crypto trader. "
    "Analyze market data and output ONLY valid JSON. "
    "No prose. No markdown. If no trade, return {\"coins\":[]}."
)

PROMPT_USER_MINI = (
    "Phân tích vào lệnh như trader chuyên nghiệp. Ưu tiên confidence và RR tốt."
    # "Dữ liệu đầy đủ dưới đây (không bỏ sót trường nào). "
    # "Phân tích như trader chuyên nghiệp, dùng mọi phương pháp: price action & mô hình nến (pinbar, engulfing, doji, breakout...), "
    # "EMA20/50/200, RSI, MACD, ATR, volume spike, đa khung (15m/H1/H4), ETH bias, orderbook. "
    # "Ưu tiên LIMIT entry tại vùng giá tối ưu; nếu không có LIMIT hợp lý -> bỏ. "
    # "Chỉ chọn khi: conf ≥ 7.0 và RR_TP1 ≥ 1.8. Nếu không đạt → bỏ. "

    # "### Quy tắc vào lệnh: "
    # "- Trend filter: Long chỉ khi close15m > EMA20 và H1/H4 trend = up. Short chỉ khi close15m < EMA20 và H1/H4 trend = down. "
    # "- Momentum filter: Long cần RSI(15m) > 50 và MACD histogram dương. Short cần RSI(15m) < 50 và MACD histogram âm. "
    # "- Funding filter: Chỉ xét nếu còn ≤60 phút tới kỳ funding; Long bất lợi khi rate>0, Short bất lợi khi rate<0. "
    # "- Orderbook filter: imbalance ≥ 0.15 theo hướng lệnh và spread ≤ 0.1%. "
    # "- ATR/SL filter: SL phải ≥ 0.6 × ATR(15m). "
    # "- Nếu mins_to_close ≤ 15 và tín hiệu yếu → bỏ. "
    # "- Entry rule: Ưu tiên LIMIT pullback về EMA20/key level; nếu tín hiệu nến (pinbar/engulfing/doji/breakout) → đặt LIMIT tại 30-> 50% thân nến, không đuổi breakout nến 2–3. "

    "Trả về JSON duy nhất dạng {\"coins\":[{\"pair\":\"SYMBOL\",\"entry\":0.0,\"sl\":0.0,\"tp\":0.0,\"conf\":0.0,\"expiry\":0}]}. "
    "Trong đó \"expiry\" là số phút trước khi lệnh LIMIT hết hạn; bot tự hủy nếu chưa khớp. "
    "Không có tín hiệu hợp lệ → {\"coins\":[]}. "

    "DATA:{payload}"
)


def build_prompts_mini(payload_kept):
    """Return prompt dict for the mini model."""

    return {
        "system": PROMPT_SYS_MINI,
        "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept)),
    }
