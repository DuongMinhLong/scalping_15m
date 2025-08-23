"""Prompt templates for the nano and mini GPT models."""

from __future__ import annotations

from env_utils import dumps_min, drop_empty, rfloat
from indicators import trend_lbl

PROMPT_SYS_NANO = (
    'Return ONLY minified JSON. No prose. If none, return {"keep":[]}.'
)

# Nano user prompts in two reduced variants
PROMPT_USER_NANO_LITE = (
    "Nhiệm vụ: Lọc coin khung 15m (20 nến + chỉ báo). Có snapshot H1/H4, ETH bias, orderbook."
    " Chỉ dùng các tín hiệu tối thiểu: hướng (trend), vol_spike, RSI, MACD, spread, imbalance, swing/high-low."
    " Giữ coin nếu đáp ứng ÍT NHẤT MỘT trong hai điều sau: "
    " (A) H1/H4 cùng hướng với 15m hoặc cùng hướng với ETH; "
    " (B) vol_spike_15m > 1.5."
    " Và đồng thời đáp ứng 2 điều kiện mềm: spread <= 0.002; imbalance cùng chiều (không âm sâu khi long, không dương sâu khi short)."
    " Tránh sideway yếu rõ rệt: RSI_15m trong [45,55] VÀ |MACD_15m| rất nhỏ (~0) trong ≥3 nến liên tiếp."
    " Ưu tiên coin có RR_approx >= 1.6 (nếu có)."
    " Nếu >5 coin đạt, chọn 5 coin điểm cao nhất (điểm = 1*MTF_align + 1*(vol_spike>1.5) + 0.5*(RR>=1.6) + 0.5*imbalance_ok)."
    " Chỉ trả JSON duy nhất dạng: {\"keep\":[\"SYMBOL\",...]}; nếu không có kết quả, trả {\"keep\":[]}."
    " DATA:{payload}"
)

PROMPT_USER_NANO_ULTRA = (
    "Lọc nhanh coin 15m. Tiêu chí giữ (rất đơn giản):"
    " 1) MTF align: hướng 15m cùng H1/H4 hoặc cùng ETH; HOẶC 2) vol_spike_15m > 1.5."
    " Bộ lọc an toàn: spread <= 0.002 và imbalance thuận chiều."
    " Bỏ qua các trường hợp sideway yếu (RSI_15m 45-55 và MACD_15m≈0)."
    " Tối đa 5 symbol tốt nhất; nếu không có, trả {\"keep\":[]}."
    " Chỉ trả JSON duy nhất {\"keep\":[\"SYMBOL\",...]}; không kèm giải thích."
    " DATA:{payload}"
)

PROMPT_SYS_MINI = (
    'You are a precise trading decision assistant. Return ONLY minified JSON. '
    'No prose. No markdown. If none, return {"coins":[]}.'
)
PROMPT_USER_MINI = (
    'Phân tích 15m (20 ohlcv+chỉ báo), H1/H4 snapshot, ETH bias, session, orderbook. '
    'Dùng price action, cấu trúc HH/HL/LH/LL, breakout, divergence, momentum/vol_spike, key level, MTF. '
    'Output JSON: {"coins":[{"pair":"SYMBOL","entry":0.0,"sl":0.0,"tp2":0.0,"risk":0.0},...]}. '
    'Ưu tiên RR>=1.8; cho phép <1.8 khi PA+volume cực mạnh & đồng thuận đa khung. H1/H4 cùng hướng 15m; ETH cùng hướng thêm điểm; '
    'cho phép ngược pha khi có đảo chiều rõ + vol_spike. Session: Asia siết/US nới/EU tb; mins_to_close<=15 & yếu → bỏ. '
    'Orderbook: bỏ nếu spread>0.001 hoặc imbalance ngược. Bot dùng TP1=1R, TP2 nếu thiếu → 2R. '
    'Đảm bảo long entry>sl, short entry<sl. Không kèo → {"coins":[]}. DATA:{payload}'
)


def _eth_bias(eth: dict | None) -> str:
    """Derive a single trend label from ETH snapshots."""

    eth = eth or {}
    t1 = ((eth.get("h1") or {}).get("trend") or "").lower()
    t4 = ((eth.get("h4") or {}).get("trend") or "").lower()
    if t1 and t1 == t4:
        return t1
    if t1 in {"up", "down"}:
        return t1
    if t4 in {"up", "down"}:
        return t4
    return "flat"


def _rr_approx(c15: dict | None) -> float | None:
    """Approximate R:R using 15m swing high/low."""

    key = (c15 or {}).get("key") or {}
    last = key.get("last_close")
    high = key.get("swing_high")
    low = key.get("swing_low")
    if last is None or high is None or low is None:
        return None
    risk = last - low
    reward = high - last
    if risk <= 0:
        return None
    return rfloat(reward / risk)


def _nano_payload(payload_full: dict) -> dict:
    """Extract a minimal payload for the nano model."""

    eth_bias = _eth_bias(payload_full.get("eth"))
    coins_out = []
    for c in payload_full.get("coins", []):
        pair = c.get("pair")
        c15 = c.get("c15") or {}
        ind = c15.get("ind") or {}
        rsi = (ind.get("rsi14") or [None])[-1]
        macd = (ind.get("macd") or [None])[-1]
        vol_spike = (ind.get("vol_spike") or [None])[-1]
        ema20 = (ind.get("ema20") or [None])[-1]
        ema50 = (ind.get("ema50") or [None])[-1]
        ema200 = (ind.get("ema200") or [None])[-1]
        trend = None
        if None not in (ema20, ema50, ema200, macd, rsi):
            trend = trend_lbl(ema20, ema50, ema200, macd, rsi)
        orderbook = c.get("orderbook") or {}
        coin_out = drop_empty(
            {
                "pair": pair,
                "m15": drop_empty(
                    {
                        "rsi": rsi,
                        "macd": macd,
                        "vol_spike": vol_spike,
                        "trend": trend,
                    }
                ),
                "h1": drop_empty({"trend": (c.get("h1") or {}).get("trend")}),
                "h4": drop_empty({"trend": (c.get("h4") or {}).get("trend")}),
                "eth_bias": eth_bias,
                "orderbook": drop_empty(
                    {
                        "spread": orderbook.get("spread"),
                        "imbalance": orderbook.get("imbalance"),
                    }
                ),
                "rr_approx": _rr_approx(c15),
            }
        )
        coins_out.append(coin_out)
    return {"coins": coins_out}


def build_prompts_nano(payload_full: dict, mode: str = "lite") -> dict:
    """Return prompt dict for the nano model.

    Parameters
    ----------
    payload_full:
        The full payload generated by ``build_payload``.
    mode:
        Either ``"lite"`` or ``"ultra"`` to choose the corresponding user prompt.
    """

    mini = _nano_payload(payload_full)
    user_tmpl = PROMPT_USER_NANO_LITE if mode != "ultra" else PROMPT_USER_NANO_ULTRA
    return {
        "system": PROMPT_SYS_NANO,
        "user": user_tmpl.replace("{payload}", dumps_min(mini)),
    }


def build_prompts_mini(payload_kept):
    """Return prompt dict for the mini model."""

    return {
        "system": PROMPT_SYS_MINI,
        "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept)),
    }
