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

# ── 1. US Fear & Greed (CNN) ──────────────────────────────────────────────────
try:
    r = requests.get(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    fg = r.json()["fear_and_greed"]
    data["fg_us"] = {"value": round(fg["score"]), "label": fg["rating"]}
except Exception as e:
    print(f"[WARN] fg_us: {e}")
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

# ── 13. Put/Call Ratio (CBOE) ─────────────────────────────────────────────────
try:
    r = requests.get(
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/PC_TOTAL.csv",
        timeout=10,
    )
    lines = r.text.strip().split("\n")
    # CSV: DATE,PC_RATIO
    last = lines[-1].split(",")
    data["put_call"] = {"value": float(last[1])}
except Exception as e:
    print(f"[WARN] put_call: {e}")
    data["put_call"] = {"value": None}

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Done:", data["updated"])
