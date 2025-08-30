"""Prompt templates for the GPT model."""

from env_utils import dumps_min


PROMPT_SYS_MINI = (
    "You are a professional crypto trader. "
    "Analyze market data and output ONLY valid JSON. "
    "Output {\"coins\":[{\"pair\":\"SYMBOL\",\"entry\":0.0,\"sl\":0.0,\"tp\":0.0,\"conf\":0.0,\"expiry\":0}]}. "
    "No prose. No markdown. If no trade, return {\"coins\":[]}."
)

PROMPT_USER_MINI = (
    # "NHIỆM VỤ: Chọn ≤6 coin từ PAYLOAD 15m + H1/H4. "
    # "Trả JSON: {\"coins\":[{\"pair\":\"SYMBOL\",\"entry\":0.0,\"sl\":0.0,"
    # "\"tp\":0.0,\"conf\":0.0,\"expiry\":0}]}. Nếu không có: {\"coins\":[]}. "
    # "RULE: "
    # "- Long: last_close>ema20(15m) & H1.t∈{0,1} & H4.t∈{0,1} & rsi14>50 & macd_hist>0. "
    # "- Short: last_close<ema20(15m) & H1.t∈{-1,0} & H4.t∈{-1,0} & rsi14<50 & macd_hist<0. "
    # "- Funding: nếu |rate|>0.0003 & mins_to_close≤90 ⇒ bỏ. "
    # "- OB/CVD: ưu tiên cùng chiều, ngược mạnh ⇒ bỏ. "
    # "- RR≥1.8 & conf≥7.0. "
    # "CONF (0–10): start=5.0; +1.5 trend 3 khung đồng pha; +1.0 RSI>60(<40 short); "
    # "+0.5 macd_hist↑; +0.5 vol_spike>1.3; +0.5 im/CVD ủng hộ; -1.0 nếu H4.t trái pha nhẹ. "
    # "Clamp 0..10. "
    # "SẮP XẾP: conf↓, rồi RR↓. "
    # "OUTPUT: chỉ JSON đúng schema. "
    "DỮ LIỆU:\\n{payload}"
)


# PROMPT_USER_MINI = (
#     # "Nhiệm vụ: phân tích 15m (20 nến + chỉ báo) tham chiếu H1/H4 từ payload; chọn TỐI ĐA 6 coin phù hợp. "
#     # "Trả về JSON DUY NHẤT theo schema: "
#     # "{\"coins\":[{\"pair\":\"SYMBOL\",\"entry\":0.0,\"sl\":0.0,\"tp\":0.0,\"conf\":0.0,\"expiry\":0}]}. "
#     # "Chỉ chọn khi conf ≥ 7.0 và RR(=|tp-entry|/|entry-sl|) ≥ 1.8. "
#     # "Quy tắc: "
#     # "- Trend: Long khi close15m>EMA20 & H1/H4 trend=up; Short khi close15m<EMA20 & H1/H4 trend=down. "
#     # "- Momentum: Long cần RSI(15m)>50 & MACD hist>0; Short cần RSI<50 & MACD hist<0. "
#     # "- Price action ưu tiên: (1) breakout+retest ngắn, (2) pullback nông EMA9/20, (3) liquidity grab tại key level. "
#     # "- ETH bias: dùng ETH H1/H4 làm bộ lọc; ưu tiên cùng hướng với ETH (ngược hướng chỉ khi setup rất mạnh). "
#     # "- SL: đặt dưới/ trên swing gần nhất hoặc ≥1.1×ATR(15); tránh SL quá xa (R ảo). "
#     # "- TP: mục tiêu ~1.7–1.9R (bot tự ladder TP/BE). "
#     # "- Session: Asia siết filter; EU/US có thể nới theo momentum. "
#     # "- Funding: tính mins_to_funding=(funding.next_ts-now_utc)/60_000; nếu ≤2 nến 15m & rate bất lợi → bỏ kèo yếu. "
#     # "- Orderbook/CVD: imbalance/CVD thuận hướng → tăng conf; ngược hướng → giảm/bỏ. "
#     # "- Expiry LIMIT (phút): mặc định 30–45; nếu entry rất gần (<0.3R) → 15–20; breakout retest xa → 45–60. "
#     # "- Tránh trùng vị thế: nếu payload có pos.has=true với pair → bỏ. "
#     # "- Momentum filter:"
#     # "+ Long: cần RSI(15m) > 50 và MACD hist > 0"
#     # "+ Short: cần RSI(15m) < 50 và MACD hist < 0"
#     # "+ Nếu RSI(15m) < 30 (quá bán) hoặc > 70 (quá mua) → bỏ entry trực tiếp, chỉ chờ hồi kỹ thuật về EMA9/20 hoặc key level rồi xác nhận lại."

#     # "Chỉ output JSON hợp lệ, không prose/markdown. "
#     "DỮ LIỆU:\\n{payload}"
# )


# PROMPT_USER_MINI = (
#     "Phân tích vào lệnh khung nến 15m (tham khảo 1h/4h) như trader chuyên nghiệp ."
#     "Ưu tiên entry tốt, SL TP hợp lý cho khung 15m, confidence >= 7 và RR tốt ."
#     # "Dữ liệu đầy đủ dưới đây (không bỏ sót trường nào). "
#     # "Phân tích như trader chuyên nghiệp, dùng mọi phương pháp: price action & mô hình nến (pinbar, engulfing, doji, breakout...), "
#     # "EMA20/50/200, RSI, MACD, ATR, volume spike, đa khung (15m/H1/H4), ETH bias, orderbook. "
#     # "Ưu tiên LIMIT entry tại vùng giá tối ưu; nếu không có LIMIT hợp lý -> bỏ. "
#     # "Chỉ chọn khi: conf ≥ 7.0 và RR_TP1 ≥ 1.8. Nếu không đạt → bỏ. "

#     # "### Quy tắc vào lệnh: "
#     # "- Trend filter: Long chỉ khi close15m > EMA20 và H1/H4 trend = up. Short chỉ khi close15m < EMA20 và H1/H4 trend = down. "
#     # "- Momentum filter: Long cần RSI(15m) > 50 và MACD histogram dương. Short cần RSI(15m) < 50 và MACD histogram âm. "
#     # "- Funding filter: Chỉ xét nếu còn ≤60 phút tới kỳ funding; Long bất lợi khi rate>0, Short bất lợi khi rate<0. "
#     # "- Orderbook filter: imbalance ≥ 0.15 theo hướng lệnh và spread ≤ 0.1%. "
#     # "- ATR/SL filter: SL phải ≥ 0.6 × ATR(15m). "
#     # "- Nếu mins_to_close ≤ 15 và tín hiệu yếu → bỏ. "
#     # "- Entry rule: Ưu tiên LIMIT pullback về EMA20/key level; nếu tín hiệu nến (pinbar/engulfing/doji/breakout) → đặt LIMIT tại 30-> 50% thân nến, không đuổi breakout nến 2–3. "

#     "Trả về JSON duy nhất dạng {\"coins\":[{\"pair\":\"SYMBOL\",\"entry\":0.0,\"sl\":0.0,\"tp\":0.0,\"conf\":0.0,\"expiry\":0}]}. "
#     "Trong đó \"expiry\" là số phút trước khi lệnh LIMIT hết hạn; bot tự hủy nếu chưa khớp. "
#     "Không có tín hiệu hợp lệ → {\"coins\":[]}. "

#     "DATA:{payload}"
# )


def build_prompts_mini(payload_kept):
    """Return prompt dict for the mini model."""

    return {
        "system": PROMPT_SYS_MINI,
        "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept)),
    }
