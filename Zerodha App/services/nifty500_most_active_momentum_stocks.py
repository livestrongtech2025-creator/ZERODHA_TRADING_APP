import time
import os
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore

from kiteconnect import KiteConnect
import numpy as np

from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from .Nifty5X_margin import stocks as STOCK_UNIVERSE

# ==============================
# CONFIG
# ==============================
EXCHANGE      = "NSE"
BATCH_SIZE    = 250      # Zerodha max per quote() call
MIN_VOLUME    = 50000
CANDLE_INTERVAL = "30minute"
OUTPUT_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "active_500.py")

MAX_WORKERS   = 10       # Parallel threads for historical_data()
RATE_LIMIT    = 3        # Zerodha allows ~3 requests/sec
rate_semaphore = Semaphore(RATE_LIMIT)

# ==============================
# HELPERS
# ==============================

def batch_list(data, batch_size):
    for i in range(0, len(data), batch_size):
        yield data[i:i + batch_size]


def get_instrument_tokens(kite):
    instruments = kite.instruments(EXCHANGE)
    return {inst["tradingsymbol"]: inst["instrument_token"] for inst in instruments}


def calculate_activity_score(candles):
    if len(candles) < 6:
        return None

    closes  = np.array([c[4] for c in candles])
    highs   = np.array([c[2] for c in candles])
    lows    = np.array([c[3] for c in candles])
    volumes = np.array([c[5] for c in candles])

    current_close  = closes[-1]
    current_volume = volumes[-1]
    avg_prev_volume = np.mean(volumes[-6:-1])

    if avg_prev_volume == 0:
        return None

    volume_surge = current_volume / avg_prev_volume

    prev_close = closes[-3]
    if prev_close == 0:
        return None

    momentum     = ((current_close - prev_close) / prev_close) * 100
    abs_momentum = abs(momentum)

    highest_high   = np.max(highs[-4:-1])
    lowest_low     = np.min(lows[-4:-1])
    breakout_bonus = 1 if (current_close > highest_high or current_close < lowest_low) else 0

    return (volume_surge * 0.55) + (abs_momentum * 0.35) + (breakout_bonus * 0.10)


# ==============================
# FETCH ONE STOCK (runs in thread)
# ==============================

def fetch_stock(kite, symbol, token, from_date, now):
    try:
        with rate_semaphore:
            # Timeout prevents any single call hanging forever
            candles = kite.historical_data(token, from_date, now, CANDLE_INTERVAL,
                                           timeout=5)
            time.sleep(1 / RATE_LIMIT)

        if not candles:
            return None

        formatted = [[c["date"], c["open"], c["high"], c["low"], c["close"], c["volume"]]
                     for c in candles[-6:]]

        score = calculate_activity_score(formatted)
        if score is None:
            return None

        return (symbol, score)

    except Exception:
        return None


# ==============================
# MAIN
# ==============================

def run_universe_selector():

    kite = KiteConnect(api_key=ZERODHA_API_KEY)
    kite.set_access_token(ZERODHA_ACCESS_TOKEN)

    print("Fetching instrument tokens...")
    token_map = get_instrument_tokens(kite)

    now       = datetime.now()
    from_date = now - timedelta(days=2)

    # ── Step 1: Filter by volume using batch quote() calls ──────────────────
    print("Filtering by volume (batch quotes)...")
    eligible = []   # symbols that pass MIN_VOLUME check

    for batch in batch_list(STOCK_UNIVERSE, BATCH_SIZE):
        instruments  = [f"{EXCHANGE}:{s}" for s in batch if s in token_map]
        valid_symbols = [s for s in batch if s in token_map]

        if not instruments:
            continue

        try:
            quotes = kite.quote(instruments)
        except Exception:
            continue

        for symbol in valid_symbols:
            key = f"{EXCHANGE}:{symbol}"
            q   = quotes.get(key, {})
            if q.get("volume", 0) >= MIN_VOLUME:
                eligible.append(symbol)

        time.sleep(0.4)   # stay within rate limit for quote() calls

    print(f"Eligible after volume filter: {len(eligible)} stocks")

    # ── Step 2: Fetch historical data in parallel ────────────────────────────
    print(f"Fetching historical data with {MAX_WORKERS} parallel threads...")
    selected_stocks = []

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {
            executor.submit(fetch_stock, kite, symbol, token_map[symbol], from_date, now): symbol
            for symbol in eligible
            if symbol in token_map
        }

    done = 0
    total = len(futures)

    for future in as_completed(futures, timeout=300):  # 5 min hard cap total
        try:
            result = future.result(timeout=10)  # 10s per stock max
            done += 1

            if result:
                selected_stocks.append(result)

            if done % 50 == 0:
                print(f"  Progress: {done}/{total} stocks processed...")

        except Exception:
            done += 1
            continue

    # ── Step 3: Rank and write output ────────────────────────────────────────
    print("Sorting top 500 stocks...")
    selected_stocks.sort(key=lambda x: x[1], reverse=True)
    top_500 = [s[0] for s in selected_stocks[:500]]

    print(f"Writing to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w") as f:
        f.write("stocks = [\n")
        for symbol in top_500:
            f.write(f'    "{symbol}",\n')
        f.write("]\n")

    print(f"Done. Total selected: {len(top_500)}")
    return True