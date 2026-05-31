# ==============================================================================
# PROGRAM: ZERODHA POSITION TREND & EXIT MONITOR
# ------------------------------------------------------------------------------
# OBJECTIVE:
#   - Fetch active MIS positions via KiteConnect API.
#   - Analyze Trend across 2min, 5min, and 15min timeframes using EMA & RSI.
#   - Calculate Dynamic Exit Levels (SL/Targets) using 1.0x and 1.8x ATR.
#   - Identify key Support/Resistance based on recent 15min price action.
#
# USAGE: 
#   Run this script to get an instant "Health Check" on all open intraday trades.
# ==============================================================================

from kiteconnect import KiteConnect
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
from prettytable import PrettyTable

from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

# ==============================
# INITIALIZE
# ==============================

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

EXCHANGE = "NSE"

# ==============================
# INDICATORS
# ==============================

def EMA(series, period):
    return series.ewm(span=period, adjust=False).mean()

def RSI(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
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
    if df.empty or len(df) < 40:
        return "Not Enough Data"

    last = df.iloc[-1]

    if last.close > last.ema20 > last.ema50 and last.rsi > 60:
        return "Strong Bullish"
    elif last.close > last.ema20 > last.ema50:
        return "Bullish"
    elif last.close < last.ema20 < last.ema50 and last.rsi < 40:
        return "Strong Bearish"
    elif last.close < last.ema20 < last.ema50:
        return "Bearish"
    else:
        return "Sideways"

def simplify_direction(trend):
    if "Bullish" in trend:
        return "UP"
    elif "Bearish" in trend:
        return "DOWN"
    return "SIDEWAYS"

# ==============================
# BUILD 2 MIN FROM 1 MIN
# ==============================

def build_2min(df_1m):
    df = df_1m.copy()
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    df_2m = df.resample('2min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    df_2m.reset_index(inplace=True)
    return df_2m

# ==============================
# GET MIS POSITIONS
# ==============================

def get_open_mis_positions():
    positions = kite.positions().get("net", [])
    stocks = []

    for pos in positions:
        if pos["product"] == "MIS" and pos["quantity"] != 0 and pos["exchange"] == EXCHANGE:
            stocks.append({
                "symbol": pos["tradingsymbol"],
                "quantity": pos["quantity"]
            })

    return stocks

# ==============================
# ANALYZE STOCK
# ==============================

def analyze_stock(symbol, quantity):

    instrument = kite.ltp(f"{EXCHANGE}:{symbol}")
    ltp_data = list(instrument.values())[0]
    token = ltp_data['instrument_token']
    ltp = ltp_data['last_price']

    current_time = datetime.now().strftime("%H:%M:%S")

    to_date = datetime.now()
    from_date = to_date - timedelta(days=7)

    df_1m = pd.DataFrame(kite.historical_data(token, from_date, to_date, "minute"))
    df_5m = pd.DataFrame(kite.historical_data(token, from_date, to_date, "5minute"))
    df_15m = pd.DataFrame(kite.historical_data(token, from_date, to_date, "15minute"))

    if df_1m.empty or df_5m.empty or df_15m.empty:
        return None

    df_2m = build_2min(df_1m)

    for df in [df_2m, df_5m, df_15m]:
        df['ema20'] = EMA(df['close'], 20)
        df['ema50'] = EMA(df['close'], 50)
        df['rsi'] = RSI(df)
        df['atr'] = ATR(df)

    trend_2m = classify_trend(df_2m)
    trend_5m = classify_trend(df_5m)
    trend_15m = classify_trend(df_15m)

    last_price = df_5m['close'].iloc[-1]
    atr_value = df_5m['atr'].iloc[-1]

    if quantity > 0:
        SL1 = round(last_price - atr_value, 2)
        SL2 = round(last_price - (1.8 * atr_value), 2)
        Target1 = round(last_price + (1.5 * atr_value), 2)
        Target2 = round(last_price + (2.5 * atr_value), 2)
    else:
        SL1 = round(last_price + atr_value, 2)
        SL2 = round(last_price + (1.8 * atr_value), 2)
        Target1 = round(last_price - (1.5 * atr_value), 2)
        Target2 = round(last_price - (2.5 * atr_value), 2)

    Support1 = round(df_15m['low'].tail(20).min(), 2)
    Resistance1 = round(df_15m['high'].tail(20).max(), 2)

    return {
        "symbol": symbol,
        "time": current_time,
        "ltp": ltp,
        "2m": trend_2m,
        "5m": trend_5m,
        "15m": trend_15m,
        "SL1": SL1,
        "SL2": SL2,
        "T1": Target1,
        "T2": Target2,
        "S1": Support1,
        "R1": Resistance1,
    }

# ==============================
# MAIN
# ==============================

if __name__ == "__main__":

    stocks = get_open_mis_positions()

    table = PrettyTable()
    table.field_names = [
        "Stock",
        "Time",
        "LTP",
        "2m",
        "5m",
        "15m",
        "SL1",
        "SL2",
        "T1",
        "T2",
        "S1",
        "R1"
    ]

    for s in stocks:

        result = analyze_stock(s["symbol"], s["quantity"])
        if result is None:
            continue

        table.add_row([
            result["symbol"],
            result["time"],
            result["ltp"],
            result["2m"],
            result["5m"],
            result["15m"],
            result["SL1"],
            result["SL2"],
            result["T1"],
            result["T2"],
            result["S1"],
            result["R1"]
        ])

        time.sleep(0.4)

    print("\n")
    print(table)