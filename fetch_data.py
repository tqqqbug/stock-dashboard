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

# ── 1. US Fear & Greed (VIX + RSI + SMA + 모멘텀 자체 계산) ──────────────────
# CNN API는 서버 요청을 차단하므로, 보유 지표로 직접 계산
def calc_fg_us(vix, rsi, price, sma200, spy_closes):
    if vix is None or rsi is None:
        return None, "N/A"
    # VIX: 낮을수록 탐욕 (정상 12~15, 공포 25+, 극도공포 40+)
    vix_score = max(0, min(100, (40 - vix) / 28 * 100))
    # RSI: 그대로 활용
    rsi_score = rsi
    # SMA: 가격이 200일선 위면 탐욕
    sma_score = 65 if (price and sma200 and price > sma200) else 35
    # 1개월 모멘텀
    momentum_score = 50
    if spy_closes and len(spy_closes) >= 21:
        mom = (spy_closes[-1] - spy_closes[-21]) / spy_closes[-21] * 100
        momentum_score = max(0, min(100, 50 + mom * 4))
    # 가중 평균
    score = round(vix_score * 0.35 + rsi_score * 0.30 + sma_score * 0.15 + momentum_score * 0.20)
    score = max(0, min(100, score))
    if score <= 25:   label = "Extreme Fear"
    elif score <= 45: label = "Fear"
    elif score <= 55: label = "Neutral"
    elif score <= 75: label = "Greed"
    else:             label = "Extreme Greed"
    return score, label
# 계산은 QQQ/SPY/VIX 수집 후에 처리 (아래에서 호출)
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
vix_val   = data["vix"]["value"]
rsi_val   = data["qqq"].get("rsi")
qqq_price = data["qqq"].get("price")
sma200    = data["qqq"].get("sma200")
fg_val, fg_label = calc_fg_us(vix_val, rsi_val, qqq_price, sma200, spy_closes)
data["fg_us"] = {"value": fg_val, "label": fg_label}

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Done:", data["updated"])
