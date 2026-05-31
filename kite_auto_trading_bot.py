import time
import math
import pytz
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
from active_500 import stocks

# ==============================
# CONFIG
# ==============================

from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

CAPITAL_PER_STOCK = 80000
MIN_VOLUME = 5000
INTERVAL = 180  # 3 minutes
TIMEZONE = pytz.timezone("Asia/Kolkata")

START_TIME = (10, 0)
STOP_NEW_TRADES_TIME = (14, 30)
SQUARE_OFF_TIME = (15, 18)

# ==============================
# INITIALIZE
# ==============================
# ==============================
# HELPER FUNCTIONS
# ==============================

def now_ist():
    return datetime.now(TIMEZONE)

def time_check(hour, minute):
    t = now_ist()
    return t.hour > hour or (t.hour == hour and t.minute >= minute)

def get_ltp(symbol):
    ltp = kite.ltp(f"NSE:{symbol}")
    return ltp[f"NSE:{symbol}"]["last_price"]

def get_intraday_candles(symbol, interval, lookback=100):
    to_date = now_ist()
    from_date = to_date - timedelta(days=5)
    data = kite.historical_data(
        kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"],
        from_date,
        to_date,
        interval
    )
    return pd.DataFrame(data)

# ==============================
# INDICATORS
# ==============================

def compute_indicators(df):
    df["ema9"] = df["close"].ewm(span=9).mean()
    df["ema21"] = df["close"].ewm(span=21).mean()
    df["rsi"] = compute_rsi(df["close"], 14)
    df["atr"] = compute_atr(df, 14)
    df["vol_avg"] = df["volume"].rolling(20).mean()
    return df

def compute_rsi(series, period):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def compute_atr(df, period):
    high_low = df["high"] - df["low"]
    high_close = abs(df["high"] - df["close"].shift())
    low_close = abs(df["low"] - df["close"].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(period).mean()

# ==============================
# TREND LOGIC
# ==============================

def classify_trend(df):
    latest = df.iloc[-1]

    if (
        latest["ema9"] > latest["ema21"] and
        latest["rsi"] > 60 and
        latest["volume"] > latest["vol_avg"]
    ):
        return "STRONG_BULL"

    if (
        latest["ema9"] < latest["ema21"] and
        latest["rsi"] < 40 and
        latest["volume"] > latest["vol_avg"]
    ):
        return "STRONG_BEAR"

    if latest["ema9"] > latest["ema21"]:
        return "BULL"

    if latest["ema9"] < latest["ema21"]:
        return "BEAR"

    return "SIDEWAYS"

# ==============================
# POSITION MANAGEMENT
# ==============================

def square_off_all():
    positions = kite.positions()["net"]
    for pos in positions:
        if pos["product"] == "MIS" and pos["quantity"] != 0:
            side = kite.TRANSACTION_TYPE_SELL if pos["quantity"] > 0 else kite.TRANSACTION_TYPE_BUY
            kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=kite.EXCHANGE_NSE,
                tradingsymbol=pos["tradingsymbol"],
                transaction_type=side,
                quantity=abs(pos["quantity"]),
                product=kite.PRODUCT_MIS,
                order_type=kite.ORDER_TYPE_MARKET
            )

def manage_positions():
    positions = kite.positions()["net"]

    for pos in positions:
        if pos["product"] != "MIS" or pos["quantity"] == 0:
            continue

        symbol = pos["tradingsymbol"]
        qty = abs(pos["quantity"])
        side = "LONG" if pos["quantity"] > 0 else "SHORT"

        df5 = compute_indicators(get_intraday_candles(symbol, "5minute"))
        trend5 = classify_trend(df5)

        # Exit logic
        if side == "LONG" and trend5 in ["BEAR", "STRONG_BEAR"]:
            square_position(symbol, qty)

        if side == "SHORT" and trend5 in ["BULL", "STRONG_BULL"]:
            square_position(symbol, qty)

        # Dynamic trailing
        apply_trailing(symbol, pos, df5)

def square_position(symbol, qty):
    kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NSE,
        tradingsymbol=symbol,
        transaction_type=kite.TRANSACTION_TYPE_SELL,
        quantity=qty,
        product=kite.PRODUCT_MIS,
        order_type=kite.ORDER_TYPE_MARKET
    )

def apply_trailing(symbol, pos, df):
    atr = df["atr"].iloc[-1]
    ltp = get_ltp(symbol)
    entry = pos["average_price"]
    qty = abs(pos["quantity"])

    if pos["quantity"] > 0:
        new_sl = max(entry, ltp - atr)
    else:
        new_sl = min(entry, ltp + atr)

    # Modify existing SL order logic placeholder

# ==============================
# ENTRY ENGINE
# ==============================

def scan_and_trade():
    balance = kite.margins()["equity"]["available"]["cash"]
    max_positions = int(balance // CAPITAL_PER_STOCK)
    max_pairs = max_positions // 2

    if max_pairs < 1:
        return

    bulls = []
    bears = []

    for symbol in stocks:

        ltp = get_ltp(symbol)
        if ltp is None:
            continue

        df2 = compute_indicators(get_intraday_candles(symbol, "2minute"))
        df5 = compute_indicators(get_intraday_candles(symbol, "5minute"))
        df15 = compute_indicators(get_intraday_candles(symbol, "15minute"))

        if df5["volume"].sum() < MIN_VOLUME:
            continue

        t2 = classify_trend(df2)
        t5 = classify_trend(df5)
        t15 = classify_trend(df15)

        if t2 == t5 == t15 == "STRONG_BULL":
            bulls.append(symbol)

        if t2 == t5 == t15 == "STRONG_BEAR":
            bears.append(symbol)

    pairs = min(len(bulls), len(bears), max_pairs)

    for i in range(pairs):
        place_trade(bulls[i], "BUY")
        place_trade(bears[i], "SELL")

def place_trade(symbol, direction):
    ltp = get_ltp(symbol)
    qty = math.floor(CAPITAL_PER_STOCK / ltp)

    kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NSE,
        tradingsymbol=symbol,
        transaction_type=kite.TRANSACTION_TYPE_BUY if direction == "BUY" else kite.TRANSACTION_TYPE_SELL,
        quantity=qty,
        product=kite.PRODUCT_MIS,
        order_type=kite.ORDER_TYPE_MARKET
    )

# ==============================
# MAIN LOOP
# ==============================

while True:
    current = now_ist()

    if time_check(*SQUARE_OFF_TIME):
        square_off_all()
        break

    manage_positions()

    if time_check(*START_TIME) and not time_check(*STOP_NEW_TRADES_TIME):
        scan_and_trade()

    time.sleep(INTERVAL)