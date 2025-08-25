"""Prompt templates for the GPT model."""

from env_utils import dumps_min


PROMPT_SYS_MINI = (
    "You are a professional crypto trader. "
    "Analyze market data and output ONLY valid JSON. "
    "No prose. No markdown. If no trade, return {\"coins\":[]}."
)

PROMPT_USER_MINI = (
    "Dữ liệu 15m dưới đây cho các coin. "
    "Phân tích toàn bộ như một trader chuyên nghiệp, kết hợp price action, đa khung (1H/H4/D1), ETH bias. "
    "Chỉ vào lệnh khi độ tự tin cao và tỉ lệ RR tốt. "
    "Trả về JSON duy nhất với 3 mức chốt lời tp1,tp2,tp3 và kèm conf (0-10) cùng rr (tỉ lệ R/R) dạng {\\\"coins\\\":[{\\\"pair\\\":\\\"SYMBOL\\\",\\\"entry\\\":0.0,\\\"sl\\\":0.0,\\\"tp1\\\":0.0,\\\"tp2\\\":0.0,\\\"tp3\\\":0.0,\\\"conf\\\":0,\\\"rr\\\":0.0}]}. "
    "Không có tín hiệu → {\\\"coins\\\":[]}. "
    "DATA:{payload}"
)


def build_prompts_mini(payload_kept):
    """Return prompt dict for the mini model."""

    return {
        "system": PROMPT_SYS_MINI,
        "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept)),
    }
