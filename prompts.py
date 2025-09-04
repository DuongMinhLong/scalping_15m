"""Prompt templates for the GPT model."""

from env_utils import dumps_min
PROMPT_SYS_MINI = (
    "Bạn là chuyên gia trading dùng mô hình sóng + nến + at -> phân tích vào lệnh \n"
    "Hãy phân tích dữ liệu 15m (200 nến OHLCV) - kết hợp với data 1h 4h.\n"
    "Đề xuất Entry, Stop Loss, Take Profit phù hợp khung 15m.\n"
    "Trả về DUY NHẤT JSON: {\"coins\":[{\"pair\":\"SYMBOLUSDT\",\"entry\":0.00,\"sl\":0.00,\"tp\":0.00,\"conf\":0.0,\"rr\":0,\"reason\":""}]}.\n" 
    "Yêu cầu : + CONF ≥ 7.0 và RR ≥ 2."
)

PROMPT_USER_MINI = (
    "DỮ LIỆU:\\n{payload}\n"
)

def build_prompts_mini(payload_kept):
    """Return prompt dict for the mini model."""

    return {
        "system": PROMPT_SYS_MINI,
        "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept)),
    }
