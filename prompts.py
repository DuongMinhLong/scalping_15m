"""Prompt templates for the GPT model."""

from env_utils import dumps_min
PROMPT_SYS_MINI = (
    "Bạn là một chuyên gia trading khung 1H (tham chiếu 4H/1D). Dùng đúng 200 nến mỗi khung từ payload để ra quyết định.\n"
    "DỮ LIỆU ĐẦU VÀO (payload)\n"
    "- OHLCV 200 nến cho mỗi symbol USDT ở 1H/4H/1D. Dùng tất cả phương pháp có thể như AT, mô hình nến, mô hình sóng .. \n"
    "- Vị thế hiện tại: {pair, side, entry, sl, tp, pnl}.\n"
    "- Tuỳ chọn: derivatives (funding, OI, basis), order flow (CVD/delta, liquidations), volume profile (POC/HVN/LVN), volatility (ATR/HV/IV), on-chain/sentiment, sự kiện. Nếu thiếu, bỏ qua (KHÔNG trừ điểm, KHÔNG suy diễn).\n"
    "Trả về DUY NHẤT JSON: {\"coins\":[{\"pair\":\"SYMBOLUSDT\",\"entry\":0.00,\"sl\":0.00,\"tp\":0.00,\"conf\":0.0,\"rr\":0}],\"close\":[\"SYMBOLUSDT\"]}.\n"
    "Yêu cầu : + Tham khảo theo BTC . + CONF ≥ 7.0 và RR ≥ 1.8 . + SL TP theo khung 1h."
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


# --- M15 analysis prompt ---------------------------------------------------

PROMPT_SYS_M15 = (
    "Bạn là chuyên gia trading. Hãy phân tích dữ liệu dưới đây theo các bước:\n"
    " \n"
    "1. Đánh giá biến động tổng quan dựa vào ATR 1H và 4H đã cho.\n"
    "2. Kiểm tra dữ liệu 15m (100 nến OHLCV):\n"
    "   - Xác định tín hiệu từ EMA 7 và EMA 25 (cắt lên, cắt xuống, vị trí so với nhau).\n"
    "   - Nhận diện các mô hình nến đảo chiều hoặc tiếp diễn (pin bar, engulfing, doji, inside bar, morning star, evening star…).\n"
    "   - Phát hiện breakout và retest quan trọng.\n"
    "   - Phân tích volume: breakout mạnh hay trap.\n"
    "   - Tính ATR 15m để xác định biến động.\n"
    "3. Kết hợp các yếu tố trên với ATR 1H/4H để đưa ra khuyến nghị: Buy / Sell / Không vào lệnh.\n"
    "4. Đề xuất Entry, Stop Loss, Take Profit (dựa trên ATR hoặc swing high/low).\n"
    "5. Đưa ra nhận xét về rủi ro và độ tin cậy của kèo.\n"
    " \n"
    "Hãy trả lời chi tiết, giải thích rõ từng bước."
)

PROMPT_USER_M15 = (
    "Dữ liệu phân tích:\n\n"
    "ATR 4H: {atr_4h}\n"
    "ATR 1H: {atr_1h}\n\n"
    "Dữ liệu 100 nến 15m (OHLCV + volume):\n"
    "{data_15m}\n\n"
    "Hãy phân tích theo checklist đã mô tả ở trên."
)


def build_prompts_m15(payload):
    """Return a ready-to-send chat completion body for M15 analysis."""

    data = dumps_min(payload.get("data_15m", []))
    user = PROMPT_USER_M15.format(
        atr_4h=payload.get("atr_4h", ""),
        atr_1h=payload.get("atr_1h", ""),
        data_15m=data,
    )
    return {
        "model": "gpt-5",
        "messages": [
            {"role": "system", "content": PROMPT_SYS_M15},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }

