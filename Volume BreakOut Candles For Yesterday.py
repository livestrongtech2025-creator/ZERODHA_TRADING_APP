"""
NSE WebSocket Intraday Volume Spike Bias Engine

This production-ready engine subscribes to live NSE tick data using
Zerodha Kite WebSocket, builds real-time 5-minute candles, tracks
volume spikes before and after 1 PM, calculates Bullish/Bearish
probabilities, stores state in Redis, and auto-generates CSV files
every 5 minutes inside the 'exports' folder.

No historical API calls are used.
"""

from kiteconnect import KiteTicker, KiteConnect
from datetime import datetime, time
import pytz
import redis
import json
import pandas as pd
import os
from apscheduler.schedulers.background import BackgroundScheduler
from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN
from Nifty5X_margin import stocks

# ==============================
# CONFIG
# ==============================

IST = pytz.timezone("Asia/Kolkata")
BEFORE_1PM_END = time(12, 55)
AFTER_1PM_START = time(13, 0)

REDIS_HOST = "localhost"
REDIS_PORT = 6379

# ==============================
# INITIALIZE
# ==============================

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    decode_responses=True
)

print("Loading instruments...")
instruments = kite.instruments("NSE")

symbol_token_map = {
    row["tradingsymbol"]: row["instrument_token"]
    for row in instruments
}

tokens = [symbol_token_map[s] for s in stocks if s in symbol_token_map]
token_symbol_map = {symbol_token_map[s]: s for s in stocks if s in symbol_token_map}

# ==============================
# MEMORY STRUCTURES
# ==============================

candle_store = {}
volume_tracker = {}

# ==============================
# HELPER FUNCTIONS
# ==============================

def get_5min_bucket(dt):
    minute = (dt.minute // 5) * 5
    return dt.replace(minute=minute, second=0, microsecond=0)

def process_tick(symbol, price, volume, timestamp):

    bucket = get_5min_bucket(timestamp)

    if symbol not in candle_store:
        candle_store[symbol] = {}

    if bucket not in candle_store[symbol]:
        candle_store[symbol][bucket] = {
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume
        }
    else:
        candle = candle_store[symbol][bucket]
        candle["high"] = max(candle["high"], price)
        candle["low"] = min(candle["low"], price)
        candle["close"] = price
        candle["volume"] += volume

    return bucket, candle_store[symbol][bucket]

def initialize_symbol(symbol):
    if symbol not in volume_tracker:
        volume_tracker[symbol] = {
            "before_max": 0,
            "after_max": 0
        }

def evaluate_bias(symbol, candle, bucket_time):

    initialize_symbol(symbol)

    tracker = volume_tracker[symbol]
    vol = candle["volume"]

    if bucket_time.time() <= BEFORE_1PM_END:
        tracker["before_max"] = max(tracker["before_max"], vol)

    elif bucket_time.time() >= AFTER_1PM_START:

        if vol >= 2 * tracker["before_max"] and tracker["before_max"] > 0:

            score = 50

            if candle["close"] > candle["open"]:
                score += 5
            else:
                score -= 5

            rng = candle["high"] - candle["low"]
            if rng > 0:
                close_pos = (candle["close"] - candle["low"]) / rng
                if close_pos > 0.7:
                    score += 15
                elif close_pos < 0.3:
                    score -= 15

            score = max(0, min(100, score))

            result = {
                "symbol": f"NSE:{symbol}",
                "direction": "BULLISH BIAS" if score > 50 else "BEARISH BIAS",
                "bull_prob": score,
                "bear_prob": 100 - score,
                "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
            }

            redis_client.set(f"bias:{symbol}", json.dumps(result))

            print("Bias Detected:", result)

# ==============================
# CSV EXPORT SCHEDULER
# ==============================

def export_csv():

    keys = redis_client.keys("bias:*")
    if not keys:
        return

    records = []

    for key in keys:
        data = redis_client.get(key)
        if data:
            records.append(json.loads(data))

    if not records:
        return

    df = pd.DataFrame(records)

    bullish_df = df[df["direction"] == "BULLISH BIAS"].sort_values(by="bull_prob", ascending=False)
    bearish_df = df[df["direction"] == "BEARISH BIAS"].sort_values(by="bear_prob", ascending=False)

    final_df = pd.concat([bullish_df, bearish_df], ignore_index=True)

    folder = "exports"
    os.makedirs(folder, exist_ok=True)

    file_name = datetime.now().strftime("%Y-%m-%d_%H-%M") + "_bias.csv"
    file_path = os.path.join(folder, file_name)

    final_df.to_csv(file_path, index=False)

    print("CSV Exported:", file_path)

scheduler = BackgroundScheduler()
scheduler.add_job(export_csv, "cron", minute="*/5")
scheduler.start()

# ==============================
# WEBSOCKET HANDLERS
# ==============================

kws = KiteTicker(ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN)

def on_ticks(ws, ticks):

    now = datetime.now(IST)

    for tick in ticks:
        symbol = token_symbol_map.get(tick["instrument_token"])
        if not symbol:
            continue

        bucket, candle = process_tick(
            symbol,
            tick["last_price"],
            tick.get("volume", 0),
            now
        )

        evaluate_bias(symbol, candle, bucket)

def on_connect(ws, response):
    ws.subscribe(tokens)
    ws.set_mode(ws.MODE_FULL, tokens)
    print("WebSocket Connected")

def on_close(ws, code, reason):
    print("WebSocket Closed:", reason)

kws.on_ticks = on_ticks
kws.on_connect = on_connect
kws.on_close = on_close

print("Starting WebSocket Volume Bias Engine...")
kws.connect()
