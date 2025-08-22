# -*- coding: utf-8 -*-
"""
Futures → GPT Orchestrator (15m scalping, H1/H4, ETH bias) — FULL
- Sàn: Binance USDT-M futures
- Flow: Build FULL payload (20 nến + 20 AT) -> NANO prefilter -> MINI decisions
- CAPITAL lấy từ Binance, RISK per-coin từ GPT
- TP1 = 1R nếu GPT không trả tp; tính quantity theo risk & vốn
- Skip coin đang có position (payload + live order)
- MINI output schema (mới): {"coins":[{"pair":"SYMBOL","entry":0.0,"sl":0.0,"tp":0.0,"risk":0.0}, ...]}

Run:
  python futures_gpt_payload_fixed_finally.py --run --limit 20 [--live]
"""

import os, json, math, re, time, argparse
from typing import Any, Dict, List, Optional, Set
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np
import ccxt

# =============== .env (python-dotenv nếu có) ===============
def load_env():
    try:
        from dotenv import load_dotenv as _ld
        _ld(override=False)
    except Exception:
        p = Path(".env")
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line=line.strip()
                if not line or line.startswith("#") or "=" not in line: continue
                k,v=[x.strip() for x in line.split("=",1)]
                if k and v and not os.getenv(k): os.environ[k]=v

def env_int(k, d):
    try: return int(os.getenv(k, d))
    except: return d

def env_bool(k, d=False):
    v=str(os.getenv(k, str(d))).strip().lower()
    return v in ("1","true","yes","y","on")

def get_models():
    return os.getenv("NANO_MODEL","gpt-5-nano"), os.getenv("MINI_MODEL","gpt-5-mini")

# =============== Utils ===============
def now_ms(): return int(time.time()*1000)
def ts_prefix(): return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
def dumps_min(o): return json.dumps(o, separators=(",", ":"), ensure_ascii=False)
def save_text(path, text): Path(path).write_text(text, encoding="utf-8")

def rfloat(x, nd=8):
    try:
        if x is None or (isinstance(x,float) and (math.isnan(x) or math.isinf(x))): return None
        return float(f"{x:.{nd}g}")
    except: return None

def compact(arr, nd=8): return [rfloat(v, nd) for v in arr]
def drop_empty(o):
    if isinstance(o, dict):
        return {k: drop_empty(v) for k,v in o.items() if v not in (None,"",[],{})}
    if isinstance(o, list):
        return [drop_empty(x) for x in o if x not in (None,"",[],{})]
    return o

# =============== Exchange (Binance futures only) ===============
def make_exchange():
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType":"future"}})
    k,s = os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET")
    if k and s: ex.apiKey, ex.secret = k, s
    return ex

BLACKLIST_BASES = {"BTC","BNB"}  # tùy chỉnh nếu muốn loại
def load_usdtm(ex):
    mk = ex.load_markets()
    out={}
    for m in mk.values():
        if m.get("linear") and m.get("swap") and m.get("quote")=="USDT" and m.get("active"):
            base=m.get("base","")
            if base not in BLACKLIST_BASES:
                out[m["symbol"]] = m
    return out

def top_by_qv(ex, limit=20):
    mk = load_usdtm(ex)
    syms = list(mk.keys())
    try:
        t = ex.fetch_tickers()
        scored=[]
        for s in syms:
            qv = (t.get(s) or {}).get("quoteVolume") or 0
            scored.append((s, float(qv)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s,_ in scored[:limit]]
    except:
        return syms[:limit]

def fetch_ohlcv_df(ex, sym, tf, limit):
    raw = ex.fetch_ohlcv(sym, tf, since=None, limit=limit)
    df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"])
    df["ts"]=pd.to_datetime(df.ts, unit="ms", utc=True)
    return df.set_index("ts").sort_index()

def orderbook_snapshot(ex, sym, depth=10):
    try:
        ob = ex.fetch_order_book(sym, limit=depth)
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        if not bids or not asks: return {}
        best_bid = float(bids[0][0]); best_ask=float(asks[0][0])
        mid = (best_bid+best_ask)/2.0
        spread = (best_ask-best_bid)/mid if mid>0 else 0.0
        bid_vol = sum(float(p)*float(a) for p,a in bids[:depth])
        ask_vol = sum(float(p)*float(a) for p,a in asks[:depth])
        den = (bid_vol+ask_vol) or 1.0
        imb = (bid_vol-ask_vol)/den
        return {"spread": rfloat(spread,6), "bid_vol": rfloat(bid_vol,6), "ask_vol": rfloat(ask_vol,6), "imbalance": rfloat(imb,6)}
    except: return {}

# =============== Indicators (pandas-ta preferred) ===============
USE_PTA=False
try:
    import pandas_ta as ta
    USE_PTA=True
except Exception:
    USE_PTA=False

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d=df.copy()
    if USE_PTA:
        d["ema20"]=ta.ema(d["close"], length=20)
        d["ema50"]=ta.ema(d["close"], length=50)
        d["ema99"]=ta.ema(d["close"], length=99)
        d["ema200"]=ta.ema(d["close"], length=200)
        d["rsi14"]=ta.rsi(d["close"], length=14)
        macd=ta.macd(d["close"], fast=12, slow=26, signal=9)
        d["macd"]=macd["MACD_12_26_9"]; d["macd_sig"]=macd["MACDs_12_26_9"]; d["macd_hist"]=macd["MACDh_12_26_9"]
        tr=ta.true_range(d["high"], d["low"], d["close"])
        d["atr14"]=ta.ema(tr, length=14)
        d["vol_spike"]=d["volume"]/ (ta.ema(d["volume"], length=20)+1e-12)
    else:
        def ema(s,n): return s.ewm(span=n, adjust=False).mean()
        def rsi(s,n=14):
            ch=s.diff(); up=ch.clip(lower=0).ewm(alpha=1/n, adjust=False).mean(); dn=(-ch.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
            rs=up/(dn+1e-12); return 100-(100/(1+rs))
        def macd(s,f=12,sl=26,sig=9):
            m=ema(s,f)-ema(s,sl); sg=ema(m,sig); return m,sg,m-sg
        def atr(df_,n=14):
            h,l,c=df_["high"],df_["low"],df_["close"]; pc=c.shift(1)
            tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
            return tr.ewm(alpha=1/n, adjust=False).mean()
        d["ema20"],d["ema50"],d["ema99"],d["ema200"]=ema(d.close,20),ema(d.close,50),ema(d.close,99),ema(d.close,200)
        d["rsi14"]=rsi(d.close,14)
        m,sg,hist=macd(d.close); d["macd"],d["macd_sig"],d["macd_hist"]=m,sg,hist
        d["atr14"]=atr(d,14)
        d["vol_spike"]=d["volume"]/(d["volume"].ewm(span=20, adjust=False).mean()+1e-12)
    return d

def trend_lbl(e20,e50,e200,macd_val,rsi_val):
    if e20>e50>e200 and macd_val>0 and rsi_val>50: return "up"
    if e20<e50<e200 and macd_val<0 and rsi_val<50: return "down"
    return "flat"

# =============== Builders (FULL 20 nến + 20 AT) ===============
def build_15m(df):
    d=add_indicators(df)
    tail20=d.tail(20)
    ohlcv20=[[rfloat(r.open),rfloat(r.high),rfloat(r.low),rfloat(r.close),rfloat(r.volume)] for _,r in tail20.iterrows()]
    swing_high = rfloat(d["high"].tail(20).max()); swing_low = rfloat(d["low"].tail(20).min())
    key={"prev_close": rfloat(d.close.iloc[-2]), "last_close": rfloat(d.close.iloc[-1]),
         "swing_high": swing_high, "swing_low": swing_low}
    ind = {
        "ema20":     compact(d["ema20"].tail(20).tolist()),
        "ema50":     compact(d["ema50"].tail(20).tolist()),
        "ema99":     compact(d["ema99"].tail(20).tolist()),
        "ema200":    compact(d["ema200"].tail(20).tolist()),
        "rsi14":     compact(d["rsi14"].tail(20).tolist()),
        "macd":      compact(d["macd"].tail(20).tolist()),
        "macd_sig":  compact(d["macd_sig"].tail(20).tolist()),
        "macd_hist": compact(d["macd_hist"].tail(20).tolist()),
        "atr14":     compact(d["atr14"].tail(20).tolist()),
        "vol_spike": compact(d["vol_spike"].tail(20).tolist()),
    }
    return {"ohlcv": ohlcv20, "ind": ind, "key": key}

def build_snap(df):
    d=add_indicators(df)
    return {
        "ema20": rfloat(d["ema20"].iloc[-1]),
        "ema50": rfloat(d["ema50"].iloc[-1]),
        "ema99": rfloat(d["ema99"].iloc[-1]),
        "ema200": rfloat(d["ema200"].iloc[-1]),
        "rsi":   rfloat(d["rsi14"].iloc[-1]),
        "macd":  rfloat(d["macd"].iloc[-1]),
        "trend": trend_lbl(d["ema20"].iloc[-1], d["ema50"].iloc[-1], d["ema200"].iloc[-1], d["macd"].iloc[-1], d["rsi14"].iloc[-1]),
    }

def session_meta():
    now=datetime.now(timezone.utc); h=now.hour
    if 0<=h<8: label="Asia"; end=now.replace(hour=8,minute=0,second=0,microsecond=0)
    elif 8<=h<16: label="Europe"; end=now.replace(hour=16,minute=0,second=0,microsecond=0)
    else: label="US"; end=(now+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    return {"label":label,"utc_hour":h,"mins_to_close":max(0,int((end-now).total_seconds()//60))}

CACHE_H1, CACHE_H4 = {}, {}
def norm_pair_symbol(sym: str) -> str:
    # 'ETH/USDT:USDT' -> 'ETHUSDT' ; 'ETHUSDT:USDT' -> 'ETHUSDT' ; 'ETH/USDT' -> 'ETHUSDT'
    if not sym:
        return ""
    return sym.split(":")[0].replace("/", "").upper()


def coin_payload(ex, sym):
    df15 = fetch_ohlcv_df(ex, sym, "15m", 300)
    if sym not in CACHE_H1: CACHE_H1[sym]=fetch_ohlcv_df(ex, sym, "1h", 300)
    if sym not in CACHE_H4: CACHE_H4[sym]=fetch_ohlcv_df(ex, sym, "4h", 300)
    c={
        "pair": norm_pair_symbol(sym),
        "c15":  build_15m(df15),
        "h1":   build_snap(CACHE_H1[sym]),
        "h4":   build_snap(CACHE_H4[sym]),
        "orderbook": orderbook_snapshot(ex, sym, depth=10)
    }
    return drop_empty(c)

def eth_bias(ex):
    sym="ETH/USDT"
    if sym not in CACHE_H1: CACHE_H1[sym]=fetch_ohlcv_df(ex, sym, "1h", 300)
    if sym not in CACHE_H4: CACHE_H4[sym]=fetch_ohlcv_df(ex, sym, "4h", 300)
    return {"h1": build_snap(CACHE_H1[sym]), "h4": build_snap(CACHE_H4[sym])}

# =============== Positions helpers ===============
def _norm_pair_from_symbol(sym: str) -> str:
    if not sym: return ""
    sym = sym.split(":")[0]
    return sym.replace("/", "").upper()

def get_open_position_pairs(ex) -> Set[str]:
    out=set()
    try:
        poss = ex.fetch_positions()
        for p in poss or []:
            sym = p.get("symbol") or (p.get("info") or {}).get("symbol")
            pair = _norm_pair_from_symbol(sym)
            amt = p.get("contracts", None)
            if amt is None: amt = p.get("amount", None)
            if amt is None: amt = (p.get("info") or {}).get("positionAmt", 0)
            try:
                if abs(float(amt))>0: out.add(pair)
            except: continue
    except Exception:
        pass
    return out

# =============== Builders: payload with position exclude ===============
def build_payload(ex, limit=20, exclude_pairs: Set[str]=None):
    exclude_pairs = exclude_pairs or set()
    syms_raw = top_by_qv(ex, limit*3)
    syms=[]
    for s in syms_raw:
        pair = s.replace("/","").upper()
        if pair in exclude_pairs: continue
        syms.append(s)
        if len(syms)>=limit: break
    coins=[coin_payload(ex, s) for s in syms]
    return {"time":{"now_utc":now_ms(),"session":session_meta()}, "eth":eth_bias(ex), "coins":[drop_empty(c) for c in coins]}

# =============== Prompts (FULL payload, nano->mini) ===============
PROMPT_SYS_NANO='Return ONLY minified JSON. No prose. If none, return {"keep":[]}.'
PROMPT_USER_NANO=(
 'Prefilter coins. Output schema:{"keep":["SYMBOL",...]}. '
 'Rules: prefer H1/H4 aligned with 15m momentum & ETH bias; drop spread too big or opposite Imbalance; '
 'skip sideway/weak. DATA:{payload}'
)

PROMPT_SYS_MINI='You are a precise trading decision assistant. Return ONLY minified JSON. No prose. No markdown. If none, return {"coins":[]}.'
# === UPDATED: no limit 5; new schema with pair, entry, sl, tp, risk ===
PROMPT_USER_MINI=(
 'Nhiệm vụ: phân tích khung 15m (FULL 20 nến + 20 chỉ báo mỗi loại), kèm H1/H4 snapshot, ETH bias, session, orderbook. '
 'Không giới hạn số coin. Trả về JSON duy nhất:\n'
 ' {"coins":[{"pair":"SYMBOL","entry":0.0,"sl":0.0,"tp":0.0,"risk":0.0}, ...]}\n'
 'Quy tắc: nếu không có tín hiệu thì trả {"coins":[]}; ưu tiên RR>=1.8; Asia siết, US nới; '
 'mins_to_close<=15 & tín hiệu yếu -> bỏ; orderbook: spread lớn hoặc imbalance ngược hướng -> bỏ. '
 'Nếu không tự tin về tp, có thể bỏ trống tp (bot sẽ dùng TP1=1R). DATA:{payload}'
)

def build_prompts_nano(payload_full): 
    return {"system": PROMPT_SYS_NANO, "user": PROMPT_USER_NANO.replace("{payload}", dumps_min(payload_full))}
def build_prompts_mini(payload_kept):
    return {"system": PROMPT_SYS_MINI, "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept))}

# =============== OpenAI (no temperature) ===============
def send_openai(sys_txt, usr_txt, model):
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    body = {"model": model, "messages":[{"role":"system","content":sys_txt},{"role":"user","content":usr_txt}], "response_format":{"type":"text"}}
    resp = client.chat.completions.create(**body)
    try: return resp.to_dict()
    except: return resp

def extract_content(resp):
    if not resp or not isinstance(resp, dict): return ""
    ch=resp.get("choices") or []
    if not ch: return ""
    return (ch[0].get("message") or {}).get("content") or ""

def try_extract_json(text):
    if not isinstance(text,str): return None
    m=re.search(r"\{[\s\S]*\}", text)
    if not m: return None
    try: return json.loads(m.group(0))
    except: return None

# =============== Parsing, sizing & order helpers ===============
def parse_mini_actions(text)->List[Dict[str,Any]]:
    """
    Expect: {"coins":[{"pair":"SYMBOL","entry":x,"sl":y,"tp":z,"risk":r}, ...]}
    tp có thể thiếu/0 -> sẽ tự tính 1R.
    """
    j=try_extract_json(text)
    arr = j.get("coins",[]) if isinstance(j,dict) else []
    out=[]
    for it in arr:
        if not isinstance(it, dict): continue
        pair = (it.get("pair") or "").upper().replace("/","")
        if not pair: continue
        entry = it.get("entry"); sl = it.get("sl"); tp = it.get("tp")
        risk = it.get("risk")
        try:
            entry = float(entry) if entry is not None else None
            sl    = float(sl) if sl is not None else None
            tp    = float(tp) if tp not in (None, "") else None
            risk  = float(risk) if risk not in (None,"") else None
        except:
            continue
        out.append({"pair": pair, "entry": entry, "sl": sl, "tp": tp, "risk": risk})
    return out

def to_ccxt_symbol(pair_no_slash:str)->str:
    base=pair_no_slash[:-4]; quote=pair_no_slash[-4:]
    return f"{base}/{quote}"

def qty_step(ex, ccxt_symbol:str)->float:
    try:
        m=ex.market(ccxt_symbol)
        step = (m.get("limits",{}).get("amount",{}) or {}).get("step") \
               or m.get("precision",{}).get("amount") \
               or (m.get("limits",{}).get("amount",{}) or {}).get("min")
        return float(step or 0.0001)
    except: return 0.0001

def round_step(qty:float, step:float)->float:
    if step<=0: return qty
    return math.floor(qty/step)*step

def calc_qty(capital:float, risk_frac:float, entry:float, sl:float, step:float)->float:
    dist=abs(entry-sl)
    if dist<=0 or risk_frac<=0 or capital<=0: return 0.0
    raw=(capital*risk_frac)/dist
    return round_step(raw, step)

def infer_side(entry: float, sl: float, tp: Optional[float]) -> Optional[str]:
    """
    Suy luận side từ bộ entry/sl/tp:
    - long nếu tp>entry>sl
    - short nếu tp<entry<sl
    - nếu tp thiếu: long nếu entry>sl; short nếu entry<sl; else None
    """
    try:
        if tp is not None:
            if tp > entry > sl: return "buy"
            if tp < entry < sl: return "sell"
        else:
            if entry > sl: return "buy"
            if entry < sl: return "sell"
    except:
        pass
    return None

def enrich_tp_qty(ex, acts:List[Dict[str,Any]], capital:float)->List[Dict[str,Any]]:
    """
    - Điền tp (nếu thiếu) = TP1 = 1R
    - Tính qty theo capital & risk (per coin; fallback 0.005)
    - Suy luận side để chuẩn bị đặt lệnh
    """
    out=[]
    for a in acts:
        entry=a.get("entry"); sl=a.get("sl"); tp=a.get("tp"); risk=a.get("risk")
        if not (isinstance(entry,(int,float)) and isinstance(sl,(int,float))): 
            continue
        # tp fallback = 1R
        if not (isinstance(tp,(int,float)) and tp>0 and tp!=entry):
            tp = entry + (entry - sl) if entry>sl else entry - (sl - entry)
            a["tp"] = rfloat(tp,8)
        # risk fallback
        rf = float(risk) if isinstance(risk,(int,float)) and risk>0 else 0.005
        # qty
        ccxt_sym = to_ccxt_symbol(a["pair"])
        step = qty_step(ex, ccxt_sym)
        qty = calc_qty(capital, rf, float(entry), float(sl), step)
        a["qty"]=rfloat(qty,8)
        a["risk"]=rfloat(rf,6)
        # side
        side = infer_side(float(entry), float(sl), float(tp))
        a["side"]=side
        out.append(a)
    return out

# =============== Prompts build ===============
PROMPT_SYS_NANO='Return ONLY minified JSON. No prose. If none, return {"keep":[]}.'
# NANO (prefilter mạnh, “giống mini” nhưng chỉ trả danh sách keep; giới hạn tối đa 5)
PROMPT_USER_NANO=(
 'Lọc danh sách coin 15m (20 nến + 20 chỉ báo), H1/H4 snapshot, ETH bias, session, orderbook. '
 'DÙNG TOÀN BỘ DỮ LIỆU & PHƯƠNG PHÁP như mini (PA, cấu trúc, divergence, key levels, vol_spike, MTF, orderbook). '
 'Chỉ trả JSON: {"keep":["SYMBOL",...]}. '
 'Tiêu chí GIỮ (lọc gắt): H1/H4 đồng pha 15m &/hoặc ETH cùng hướng; RR ước lượng>=1.8; vol_spike>1.5; '
 'không sideway (RSI 40–60 & MACD≈0) trừ khi có setup đảo chiều rõ ràng + volume; '
 'spread<=0.001 và imbalance không ngược hướng; session: Asia siết/US nới/EU trung bình; '
 'mins_to_close<=15 & tín hiệu yếu → loại. '
 'Chỉ chọn TỐI ĐA 5 symbol tốt nhất; nếu không đạt → {"keep":[]}. DATA:{payload}'
)

PROMPT_SYS_MINI='You are a precise trading decision assistant. Return ONLY minified JSON. No prose. No markdown. If none, return {"coins":[]}.'
# MINI (ra quyết định)
PROMPT_USER_MINI=(
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
 '- H1 & H4 nên cùng hướng 15m; ETH cùng hướng là điểm cộng; cho phép ngược pha khi có đảo chiều rõ (divergence + cấu trúc vỡ + vol_spike). '
 '- Session: Asia siết, US nới, EU trung bình; nếu mins_to_close<=15 & tín hiệu yếu → bỏ. '
 '- Orderbook: bỏ nếu spread>0.001 hoặc imbalance ngược; ưu tiên imbalance thuận. '
 '- TP có thể để trống (bot dùng TP1=1R). Đảm bảo entry/sl hợp lệ với hướng (long: entry>sl; short: entry<sl). '
 'Không có kèo → {"coins":[]}. DATA:{payload}'
)

def build_prompts_nano(payload_full): 
    return {"system": PROMPT_SYS_NANO, "user": PROMPT_USER_NANO.replace("{payload}", dumps_min(payload_full))}
def build_prompts_mini(payload_kept):
    return {"system": PROMPT_SYS_MINI, "user": PROMPT_USER_MINI.replace("{payload}", dumps_min(payload_kept))}

# =============== Flow ===============
def run(run_live=False, limit=20):
    load_env()
    nano_model, mini_model = get_models()
    ex = make_exchange()

    # Capital (USDT) từ Binance
    try:
        bal = ex.fetch_balance()
        capital = float((bal.get("total") or {}).get("USDT", 0.0))
    except Exception:
        capital = 0.0

    # Skip coin đang có open position
    pos_pairs = get_open_position_pairs(ex)

    # 1) Build & save FULL payload (đã exclude positions)
    payload_full = build_payload(ex, limit, exclude_pairs=pos_pairs)
    stamp=ts_prefix()
    save_text(f"{stamp}_payload_full.json", dumps_min(payload_full))
    save_text(f"{stamp}_positions_excluded.json", dumps_min({"positions": sorted(list(pos_pairs))}))

    if not payload_full["coins"]:
        save_text(f"{stamp}_orders.json", dumps_min({"live": run_live, "capital": capital, "coins": [], "placed": [], "reason":"no_coins_after_exclude"}))
        return {"ts": stamp, "capital": capital, "coins": [], "placed": []}

    # 2) NANO prefilter
    pr_nano = build_prompts_nano(payload_full)
    rsp_nano = send_openai(pr_nano["system"], pr_nano["user"], nano_model)
    nano_text = extract_content(rsp_nano)
    save_text(f"{stamp}_nano_output.json", nano_text)
    keep = []
    try:
        j = try_extract_json(nano_text) or {}
        keep = [s.replace("/","").upper() for s in (j.get("keep") or []) if isinstance(s,str)]
    except:
        keep = []

    kept = [c for c in payload_full["coins"] if c["pair"] in keep] if keep else []
    payload_kept = {"time":payload_full["time"], "eth":payload_full["eth"], "coins": kept}
    save_text(f"{stamp}_payload_kept.json", dumps_min(payload_kept))

    # 3) MINI decisions on kept (FULL payload_kept)
    mini_text=""; coins=[]
    if kept:
        pr_mini = build_prompts_mini(payload_kept)
        rsp_mini = send_openai(pr_mini["system"], pr_mini["user"], mini_model)
        mini_text = extract_content(rsp_mini)
        save_text(f"{stamp}_mini_output.json", mini_text)
        coins = parse_mini_actions(mini_text)

    # 4) Enrich tp & qty & side
    coins = enrich_tp_qty(ex, coins, capital)

    # 5) Place orders (mock) — nếu live, skip pair đang có position
    placed=[]
    if run_live and coins:
        pos_pairs_live = get_open_position_pairs(ex)
        for c in coins:
            pair=(c.get("pair") or "").upper()
            side=c.get("side")
            entry=c.get("entry"); sl=c.get("sl"); tp=c.get("tp"); qty=c.get("qty")
            if side not in ("buy","sell"): continue
            if pair in pos_pairs_live:  # tránh trùng lệnh
                continue
            placed.append({"pair": pair, "side": side, "entry": entry, "sl": sl, "tp": tp, "qty": qty})
            # Thực thi thật (tùy bạn mở):
            ccxt_sym = to_ccxt_symbol(pair)
            ex.create_order(ccxt_sym, "limit", "buy" if side=="buy" else "sell", qty, entry, {"reduceOnly": False})

    result = {"live": run_live, "capital": capital, "coins": coins, "placed": placed}
    save_text(f"{stamp}_orders.json", dumps_min(result))
    return {"ts": stamp, **result}

# =============== CLI ===============
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--live", action="store_true", default=env_bool("LIVE",False))
    ap.add_argument("--limit", type=int, default=env_int("LIMIT",20))
    args=ap.parse_args()
    if args.run:
        print(dumps_min(run(run_live=args.live, limit=args.limit)))
    else:
        print(dumps_min(run(run_live=env_bool("LIVE",False), limit=env_int("LIMIT",20))))
