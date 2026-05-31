from kiteconnect import KiteConnect
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

# ==============================
# INITIALIZE
# ==============================

EXCHANGE = "NSE"


# ==============================
# INDICATORS
# ==============================

def EMA(series, period):
    return series.ewm(span=period, adjust=False).mean()

def RSI_Wilder(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))

def ATR(df, period=14):
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ==============================
# TREND LOGIC
# ==============================

def classify_trend(df):
    if df.empty or len(df) < 50:
        return "Low Data"

    last = df.iloc[-1]
    prev = df.iloc[-2]

    is_bull = last.close > last.ema20 > last.ema50 and last.ema20 > prev.ema20
    is_bear = last.close < last.ema20 < last.ema50 and last.ema20 < prev.ema20

    if is_bull and last.rsi > 65:
        return "Strong Bullish"
    if is_bull:
        return "Bullish"
    if is_bear and last.rsi < 35:
        return "Strong Bearish"
    if is_bear:
        return "Bearish"

    return "Sideways"


def get_direction_val(trend_str):
    if "Bullish" in trend_str:
        return "UP"
    if "Bearish" in trend_str:
        return "DOWN"
    return "SIDEWAYS"


# ==============================
# DATA FUNCTIONS
# ==============================

def build_2min(df_1m):
    df = df_1m.copy()
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    df_2 = df.resample('2min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna().reset_index()

    return df_2


def get_open_mis_positions(kite):
    positions = kite.positions().get("net", [])

    return [
        {"symbol": p["tradingsymbol"], "qty": p["quantity"]}
        for p in positions
        if p["product"] == "MIS"
        and p["quantity"] != 0
        and p["exchange"] == EXCHANGE
    ]


# ==============================
# ANALYSIS ENGINE
# ==============================

def analyze_position(kite, symbol, quantity):

    full_symbol = f"{EXCHANGE}:{symbol}"
    token = kite.ltp(full_symbol)[full_symbol]['instrument_token']

    to_date = datetime.now()
    from_date = to_date - timedelta(days=5)

    d1 = pd.DataFrame(kite.historical_data(token, from_date, to_date, "minute"))
    d5 = pd.DataFrame(kite.historical_data(token, from_date, to_date, "5minute"))
    d15 = pd.DataFrame(kite.historical_data(token, from_date, to_date, "15minute"))

    d2 = build_2min(d1)

    for df in [d2, d5, d15]:
        df['ema20'] = EMA(df['close'], 20)
        df['ema50'] = EMA(df['close'], 50)
        df['rsi'] = RSI_Wilder(df)
        df['atr'] = ATR(df)

    t2 = classify_trend(d2)
    t5 = classify_trend(d5)
    t15 = classify_trend(d15)

    pos_dir = "UP" if quantity > 0 else "DOWN"
    trends = [get_direction_val(t2), get_direction_val(t5), get_direction_val(t15)]

    if all(d == pos_dir for d in trends):
        category = "FULLY_ALIGNED"
    elif trends.count(pos_dir) >= 2:
        category = "PARTIAL_ALIGNED"
    elif all(d != pos_dir and d != "SIDEWAYS" for d in trends):
        category = "OPPOSITE"
    else:
        category = "CONFLICT"

    ltp = d2['close'].iloc[-1]
    atr_v = d15['atr'].iloc[-1]
    side = 1 if quantity > 0 else -1

    sl1 = round(ltp - (1.5 * atr_v * side), 2)
    sl2 = round(ltp - (2.5 * atr_v * side), 2)
    tg1 = round(ltp + (2.0 * atr_v * side), 2)
    tg2 = round(ltp + (4.0 * atr_v * side), 2)

    s1 = round(d15['low'].tail(20).min(), 2)
    r1 = round(d15['high'].tail(20).max(), 2)

    return {
        "symbol": symbol,
        "t2": t2,
        "t5": t5,
        "t15": t15,
        "sl1": sl1,
        "sl2": sl2,
        "tg1": tg1,
        "tg2": tg2,
        "s1": s1,
        "r1": r1,
        "category": category
    }


# ==============================
# WEB ENTRY FUNCTION
# ==============================

def run_position_monitor():

    kite = KiteConnect(api_key=ZERODHA_API_KEY)
    kite.set_access_token(ZERODHA_ACCESS_TOKEN)

    stocks = get_open_mis_positions(kite)

    if not stocks:
        return []

    final_results = []

    for s in stocks:
        result = analyze_position(kite, s["symbol"], s["qty"])
        if result:
            final_results.append(result)
        time.sleep(0.3)

    return final_results