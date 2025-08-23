"""Prompt templates for the GPT model."""

from env_utils import dumps_min


PROMPT_SYS_MINI = (
    "You are a professional crypto trader. "
    "Analyze market data and output ONLY valid JSON. "
    "No prose. No markdown. If no trade, return {\"coins\":[]}."
)

PROMPT_USER_MINI = (
    "Dữ liệu đầy đủ dưới đây (không bỏ sót bất kỳ trường nào). "
    "Phân tích toàn bộ như 1 trader chuyên nghiệp, kết hợp price action, đa khung (1H/H4/D1), ETH bias, "
    "orderbook, funding/OI/CVD/liquidation, news. "
    "Trả về JSON duy nhất dạng {\"coins\":[{\"pair\":\"SYMBOL\",\"entry\":0.0,\"sl\":0.0,\"tp2\":0.0}, ...]}. "
    "Không có tín hiệu → {\"coins\":[]}. "
    "Chỉ chọn LIMIT entry tối ưu (best limit entry). "
    "DATA:{payload}"
)


def build_prompts_mini(payload_kept):
    """Return prompt dict for the mini model."""

    return {
        "system": PROMPT_SYS_MINI,
        "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept)),
    }
