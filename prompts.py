"""Prompt templates for the GPT model."""

from env_utils import dumps_min
PROMPT_SYS_MINI = (
    "Bạn là chuyên gia trading. Hãy phân tích dữ liệu dưới đây theo các bước:\n"
    "1. Xác định xu hướng tổng quan dựa vào trend 1H và 4H đã cho.\n"
    "2. Kiểm tra dữ liệu 15m (100 nến OHLCV):\n"
    "   - Xác định tín hiệu từ EMA 7 và EMA 25 (cắt lên, cắt xuống, vị trí so với nhau).\n"
    "   - Nhận diện các mô hình nến đảo chiều hoặc tiếp diễn (pin bar, engulfing, doji, inside bar, morning star, evening star…).\n"
    "   - Phát hiện breakout và retest quan trọng.\n"
    "   - Phân tích volume: breakout mạnh hay trap.\n"
    "   - Tính ATR 15m để xác định biến động.\n"
    "3. Kết hợp các yếu tố trên với xu hướng chính (1H, 4H) để đưa ra khuyến nghị: Buy / Sell / Không vào lệnh.\n"
    "4. Đề xuất Entry, Stop Loss, Take Profit (dựa trên ATR hoặc swing high/low).\n"
    "5. Đưa ra nhận xét về rủi ro và độ tin cậy của kèo."
    "Trả về DUY NHẤT JSON: {\"coins\":[{\"pair\":\"SYMBOLUSDT\",\"entry\":0.00,\"sl\":0.00,\"tp\":0.00,\"conf\":0.0,\"rr\":0}]}.\n" 
    "Yêu cầu : + CONF ≥ 7.0 và RR ≥ 1.5 . + SL TP phù hợp khung 15m."
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
