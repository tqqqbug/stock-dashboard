import requests
import json
import yfinance as yf
from datetime import datetime, timedelta

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def fetch_ticker(symbol, period="1y"):
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period=period)
        if hist.empty:
            return None
        return list(hist["Close"].dropna())
    except Exception as e:
        print(f"[WARN] {symbol}: {e}")
        return None

def pct_change(closes):
    if closes is None or len(closes) < 2:
        return None
    return round((closes[-1] - closes[-2]) / closes[-2] * 100, 2)

data = {"updated": datetime.utcnow().isoformat() + "Z"}

# ── 1. US Fear & Greed (CNN 방식 근사 계산) ───────────────────────────────────
# CNN은 7가지 지표를 사용하며, 각 지표를 52주 범위로 정규화함
# 여기서는 수집 가능한 4가지 핵심 지표로 근사
def normalize_to_100(value, min_val, max_val, invert=False):
    """값을 0~100 범위로 정규화. invert=True면 높을수록 낮은 점수(공포)"""
    if min_val == max_val:
        return 50
    score = (value - min_val) / (max_val - min_val) * 100
    score = max(0, min(100, score))
    return round(100 - score if invert else score, 2)

def calc_fg_us(vix_closes, rsi, qqq_closes, spy_closes):
    scores = []

    # ① VIX vs 50일 이평선 (CNN 방식: 상대적 변동성)
    # VIX가 MA보다 높을수록 공포
    if vix_closes and len(vix_closes) >= 50:
        vix_now = vix_closes[-1]
        vix_ma50 = sum(vix_closes[-50:]) / 50
        ratio = vix_now / vix_ma50   # 1.0 = 평균, >1 = 공포
        # ratio: 0.5(극도탐욕) ~ 2.0(극도공포) → 0~100으로 변환
        vix_score = max(0, min(100, (2.0 - ratio) / 1.5 * 100))
        scores.append(vix_score * 0.30)

    # ② 125일 모멘텀 (CNN: S&P500 vs 125일 MA)
    if spy_closes and len(spy_closes) >= 125:
        ma125 = sum(spy_closes[-125:]) / 125
        pct = (spy_closes[-1] - ma125) / ma125 * 100
        # -15%(극도공포) ~ +15%(극도탐욕) → 0~100
        mom_score = max(0, min(100, 50 + pct * 3.3))
        scores.append(mom_score * 0.25)

    # ③ RSI (과매도=공포, 과매수=탐욕)
    if rsi is not None:
        scores.append(rsi * 0.25)

    # ④ QQQ vs 200일 SMA (추세 강도)
    if qqq_closes and len(qqq_closes) >= 200:
        sma200 = sum(qqq_closes[-200:]) / 200
        pct = (qqq_closes[-1] - sma200) / sma200 * 100
        # -10% ~ +10% → 0~100
        sma_score = max(0, min(100, 50 + pct * 5))
        scores.append(sma_score * 0.20)

    if not scores:
        return None, "N/A"

    score = round(sum(scores) / (0.30 + 0.25 + 0.25 + 0.20) * (1 / max(len(scores)/4, 1) + (len(scores)-1)/4))
    # 실제 가중합 재계산
    weights = [0.30, 0.25, 0.25, 0.20]
    raw_scores = []
    if vix_closes and len(vix_closes) >= 50:
        vix_now = vix_closes[-1]; vix_ma50 = sum(vix_closes[-50:]) / 50
        raw_scores.append((max(0, min(100, (2.0 - vix_now/vix_ma50) / 1.5 * 100)), weights[0]))
    if spy_closes and len(spy_closes) >= 125:
        ma125 = sum(spy_closes[-125:]) / 125
        pct = (spy_closes[-1] - ma125) / ma125 * 100
        raw_scores.append((max(0, min(100, 50 + pct * 3.3)), weights[1]))
    if rsi is not None:
        raw_scores.append((rsi, weights[2]))
    if qqq_closes and len(qqq_closes) >= 200:
        sma200 = sum(qqq_closes[-200:]) / 200
        pct = (qqq_closes[-1] - sma200) / sma200 * 100
        raw_scores.append((max(0, min(100, 50 + pct * 5)), weights[3]))

    total_w = sum(w for _, w in raw_scores)
    score = round(sum(s * w for s, w in raw_scores) / total_w) if total_w > 0 else 50
    score = max(0, min(100, score))

    if score <= 25:   label = "Extreme Fear"
    elif score <= 45: label = "Fear"
    elif score <= 55: label = "Neutral"
    elif score <= 75: label = "Greed"
    else:             label = "Extreme Greed"
    return score, label

data["fg_us"] = {"value": None, "label": "N/A"}

# ── 2. Crypto Fear & Greed (Alternative.me) ───────────────────────────────────
try:
    r = requests.get("https://api.alternative.me/fng/", timeout=10)
    fg = r.json()["data"][0]
    data["fg_crypto"] = {"value": int(fg["value"]), "label": fg["value_classification"]}
except Exception as e:
    print(f"[WARN] fg_crypto: {e}")
    data["fg_crypto"] = {"value": None, "label": "N/A"}

# ── 3. Bitcoin & Ethereum (CoinGecko) ─────────────────────────────────────────
try:
    r = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "bitcoin,ethereum", "vs_currencies": "usd", "include_24hr_change": "true"},
        timeout=10,
    )
    coins = r.json()
    data["bitcoin"] = {
        "price": coins["bitcoin"]["usd"],
        "change_pct": round(coins["bitcoin"]["usd_24h_change"], 2),
    }
    data["ethereum"] = {
        "price": coins["ethereum"]["usd"],
        "change_pct": round(coins["ethereum"]["usd_24h_change"], 2),
    }
except Exception as e:
    print(f"[WARN] crypto prices: {e}")
    data["bitcoin"] = {"price": None, "change_pct": None}
    data["ethereum"] = {"price": None, "change_pct": None}

# ── 4. QQQ (price, 200-day SMA, RSI) ─────────────────────────────────────────
qqq_closes = fetch_ticker("QQQ")
if qqq_closes:
    price = round(qqq_closes[-1], 2)
    sma200 = round(sum(qqq_closes[-200:]) / min(len(qqq_closes), 200), 2)
    rsi = calc_rsi(qqq_closes)
    data["qqq"] = {"price": price, "sma200": sma200, "rsi": rsi,
                   "change_pct": pct_change(qqq_closes)}
else:
    data["qqq"] = {"price": None, "sma200": None, "rsi": None, "change_pct": None}

# ── 5. SPY ────────────────────────────────────────────────────────────────────
spy_closes = fetch_ticker("SPY")
data["spy"] = {
    "price": round(spy_closes[-1], 2) if spy_closes else None,
    "change_pct": pct_change(spy_closes),
}

# ── 6. VIX ────────────────────────────────────────────────────────────────────
vix_closes = fetch_ticker("^VIX")
data["vix"] = {"value": round(vix_closes[-1], 2) if vix_closes else None}

# ── 7. NASDAQ 100 ─────────────────────────────────────────────────────────────
ndx_closes = fetch_ticker("^NDX")
data["ndx"] = {
    "price": round(ndx_closes[-1], 2) if ndx_closes else None,
    "change_pct": pct_change(ndx_closes),
}

# ── 8. Gold ───────────────────────────────────────────────────────────────────
gold_closes = fetch_ticker("GC=F")
data["gold"] = {
    "price": round(gold_closes[-1], 2) if gold_closes else None,
    "change_pct": pct_change(gold_closes),
}

# ── 9. WTI Oil ────────────────────────────────────────────────────────────────
oil_closes = fetch_ticker("CL=F")
data["oil"] = {
    "price": round(oil_closes[-1], 2) if oil_closes else None,
    "change_pct": pct_change(oil_closes),
}

# ── 10. USD/KRW ───────────────────────────────────────────────────────────────
usd_closes = fetch_ticker("USDKRW=X")
data["usdkrw"] = {
    "price": round(usd_closes[-1], 2) if usd_closes else None,
    "change_pct": pct_change(usd_closes),
}

# ── 11. JPY/KRW (100엔 기준) ──────────────────────────────────────────────────
jpy_closes = fetch_ticker("JPYKRW=X")
if jpy_closes:
    # Yahoo Finance returns per-1-JPY rate; multiply by 100 for 100엔 기준
    data["jpykrw"] = {
        "price": round(jpy_closes[-1] * 100, 2),
        "change_pct": pct_change(jpy_closes),
    }
else:
    data["jpykrw"] = {"price": None, "change_pct": None}

# ── 12. KOSPI → Korean Fear & Greed (RSI 기반 추정) ──────────────────────────
ks_closes = fetch_ticker("^KS11")
if ks_closes:
    rsi_kr = calc_rsi(ks_closes)
    if rsi_kr is not None:
        # RSI를 공포/탐욕 지수로 변환 (단순 선형 매핑)
        fg_kr = round(rsi_kr)
        if fg_kr <= 25:
            label_kr = "Extreme Fear"
        elif fg_kr <= 45:
            label_kr = "Fear"
        elif fg_kr <= 55:
            label_kr = "Neutral"
        elif fg_kr <= 75:
            label_kr = "Greed"
        else:
            label_kr = "Extreme Greed"
        data["fg_kr"] = {"value": fg_kr, "label": label_kr}
    else:
        data["fg_kr"] = {"value": None, "label": "N/A"}
else:
    data["fg_kr"] = {"value": None, "label": "N/A"}

# ── 13. Put/Call Ratio (SPY 옵션 데이터로 계산) ───────────────────────────────
try:
    spy_ticker = yf.Ticker("SPY")
    expirations = spy_ticker.options          # 만기일 목록
    if expirations:
        chain = spy_ticker.option_chain(expirations[0])
        put_vol  = chain.puts["volume"].dropna().sum()
        call_vol = chain.calls["volume"].dropna().sum()
        if call_vol > 0:
            pc = round(put_vol / call_vol, 3)
            data["put_call"] = {"value": pc}
        else:
            data["put_call"] = {"value": None}
    else:
        data["put_call"] = {"value": None}
except Exception as e:
    print(f"[WARN] put_call: {e}")
    data["put_call"] = {"value": None}

# ── 14. US Fear & Greed 최종 계산 (모든 지표 수집 후) ────────────────────────
rsi_val = data["qqq"].get("rsi")
fg_val, fg_label = calc_fg_us(vix_closes, rsi_val, qqq_closes, spy_closes)
data["fg_us"] = {"value": fg_val, "label": fg_label}
print(f"[INFO] fg_us = {fg_val} ({fg_label})")

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Done:", data["updated"])
