"""
Intraday Universe Selector v1.0

Scans 1500 NSE stocks and selects Top 500_most_active_momentum_stocks using:

- 30-minute timeframe
- Volume surge detection
- Momentum expansion
- Breakout priority
- Liquidity filter (min traded value 5 crore based on today's intraday volume)

Output:
active_500.py (single stocks array)
"""

import time
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
import numpy as np

from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN
from Nifty5X_margin import stocks as STOCK_UNIVERSE


# ==============================
# CONFIGURATION
# ==============================

EXCHANGE = "NSE"
BATCH_SIZE = 250
SLEEP_SECONDS = 1
MIN_TRADED_VALUE = 5_00_00_000  # 5 Crore (Today's Volume x LTP)
CANDLE_INTERVAL = "30minute"
OUTPUT_FILE = "active_500.py"


# ==============================
# INITIALIZE KITE
# ==============================

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)


# ==============================
# HELPER FUNCTIONS
# ==============================

def batch_list(data, batch_size):
    """Yield successive batches."""
    for i in range(0, len(data), batch_size):
        yield data[i:i + batch_size]


def get_instrument_tokens():
    """
    Fetch instrument dump once and create
    symbol -> instrument_token mapping.
    """
    instruments = kite.instruments(EXCHANGE)
    token_map = {}

    for inst in instruments:
        token_map[inst["tradingsymbol"]] = inst["instrument_token"]

    return token_map


def calculate_activity_score(candles):
    """
    Calculate:
    - Volume Surge
    - Momentum
    - Breakout Bonus
    - Final Activity Score
    """

    if len(candles) < 6:
        return None

    # Extract values
    closes = np.array([c[4] for c in candles])
    highs = np.array([c[2] for c in candles])
    lows = np.array([c[3] for c in candles])
    volumes = np.array([c[5] for c in candles])

    current_close = closes[-1]
    current_volume = volumes[-1]

    # Volume Surge
    avg_prev_volume = np.mean(volumes[-6:-1])
    if avg_prev_volume == 0:
        return None

    volume_surge = current_volume / avg_prev_volume

    # Momentum (% move from 2 candles back)
    prev_close = closes[-3]
    if prev_close == 0:
        return None

    momentum = ((current_close - prev_close) / prev_close) * 100
    abs_momentum = abs(momentum)

    # Breakout detection
    highest_high = np.max(highs[-4:-1])
    lowest_low = np.min(lows[-4:-1])

    breakout_bonus = 0
    if current_close > highest_high or current_close < lowest_low:
        breakout_bonus = 1

    # Final Activity Score
    activity_score = (
        (volume_surge * 0.55)
        + (abs_momentum * 0.35)
        + (breakout_bonus * 0.10)
    )

    return activity_score


# ==============================
# MAIN LOGIC
# ==============================

def main():

    print("Fetching instrument tokens...")
    token_map = get_instrument_tokens()

    print("Starting universe scan...")
    selected_stocks = []

    now = datetime.now()
    from_date = now - timedelta(days=5)
    today_date = now.date()

    for batch in batch_list(STOCK_UNIVERSE, BATCH_SIZE):

        instruments = []
        valid_symbols = []

        for symbol in batch:
            if symbol in token_map:
                instruments.append(f"{EXCHANGE}:{symbol}")
                valid_symbols.append(symbol)

        if not instruments:
            continue

        try:
            quotes = kite.quote(instruments)
        except Exception as e:
            print(f"Quote fetch error: {e}")
            continue

        for symbol in valid_symbols:
            try:
                quote = quotes[f"{EXCHANGE}:{symbol}"]
                ltp = quote["last_price"]

                token = token_map[symbol]

                candles = kite.historical_data(
                    token,
                    from_date,
                    now,
                    CANDLE_INTERVAL
                )

                if not candles:
                    continue

                # Liquidity filter: sum volume only from today's 30-min candles
                # This avoids stale/previous-day volume from quote["volume"]
                today_volume = sum(
                    c["volume"] for c in candles
                    if c["date"].date() == today_date
                )
                traded_value = today_volume * ltp

                if traded_value < MIN_TRADED_VALUE:
                    continue

                score = calculate_activity_score(
                    [[
                        c["date"],
                        c["open"],
                        c["high"],
                        c["low"],
                        c["close"],
                        c["volume"]
                    ] for c in candles[-6:]]
                )

                if score is None:
                    continue

                selected_stocks.append((symbol, score))

            except Exception:
                continue

        time.sleep(SLEEP_SECONDS)

    print("Sorting top 500 stocks...")

    # Sort by activity score descending
    selected_stocks.sort(key=lambda x: x[1], reverse=True)

    top_500 = [s[0] for s in selected_stocks[:500]]

    print(f"Writing output to {OUTPUT_FILE}...")

    with open(OUTPUT_FILE, "w") as f:
        f.write("stocks = [\n")
        for symbol in top_500:
            f.write(f'    "{symbol}",\n')
        f.write("]\n")

    print("Universe selection complete.")
    print(f"Total selected: {len(top_500)}")


# ==============================
# EXECUTION
# ==============================

if __name__ == "__main__":
    main()