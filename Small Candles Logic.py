"""
ULTRA FAST 5-MIN INTRADAY SCANNER (ZERODHA KITE)

Purpose:
This script scans a predefined list of NSE stocks using 5-minute candles
from Zerodha Kite API and identifies stocks meeting strict intraday
volatility contraction conditions.

Core Logic:
1. Uses last 3 days of 5-minute historical data.
2. Considers ONLY today’s candles (except for yesterday’s close).
3. Ignores the first 10 minutes of today’s trading session.
4. Stock must be moving at least ±2% from yesterday’s closing price.
5. Today’s candles must be small:
   - Maximum 3 candles between 1%–1.3% of current price.
   - No candle greater than 1.3% of current price.
6. Scans multiple stocks in parallel using threading (rate-limit safe).

Goal:
Identify strong ±2% movers that are currently forming tight,
low-volatility intraday structures — suitable for breakout setups.

Optimized For:
• ~1500 stocks
• Production-safe execution
• Zerodha rate-limit compliance
"""
from kiteconnect import KiteConnect
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

# -----------------------------------------
# CONFIG
# -----------------------------------------
MAX_WORKERS = 5              # Safe for Zerodha
LOOKBACK_DAYS = 3
IGNORE_FIRST_CANDLES = 2

# -----------------------------------------
# INIT KITE
# -----------------------------------------
kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

# -----------------------------------------
# LOAD STOCK LIST
# -----------------------------------------
def load_stocks():
    from Nifty5X_margin import stocks
    return stocks

# -----------------------------------------
# GET INSTRUMENT MAP
# -----------------------------------------
def get_instrument_map():
    instruments = kite.instruments("NSE")
    return {
        inst["tradingsymbol"]: inst["instrument_token"]
        for inst in instruments
    }

# -----------------------------------------
# SCAN SINGLE STOCK (ORIGINAL LOGIC)
# -----------------------------------------
def scan_stock(symbol, token):
    try:
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=LOOKBACK_DAYS)

        candles = kite.historical_data(
            token,
            from_dt,
            to_dt,
            interval="5minute"
        )

        if not candles:
            return None

        df = pd.DataFrame(candles)
        df["date"] = pd.to_datetime(df["date"])
        df["only_date"] = df["date"].dt.date
        
        latest_trading_date = df["only_date"].max()

        today_df = df[df["only_date"] == latest_trading_date].copy()

        prev_dates = sorted(df["only_date"].unique())
        prev_dates = [d for d in prev_dates if d < latest_trading_date]

        if not prev_dates:
            return None

        last_trading_day = prev_dates[-1]
        prev_df = df[df["only_date"] == last_trading_day].copy()


        # Yesterday close
        last_day_close = prev_df.iloc[-1]["close"]

        # Ignore first 10 minutes
        today_df = today_df.iloc[IGNORE_FIRST_CANDLES:]

        if len(today_df) < 5:
            return None

        # Current traded price
        current_price = today_df.iloc[-1]["close"]

        # ±2% condition
        price_change_pct = (
            (current_price - last_day_close) / last_day_close * 100
        )

        if not (price_change_pct >= 2 or price_change_pct <= -2):
            return None

        # Candle size % of CURRENT price
        today_df["candle_pct"] = (
            (today_df["high"] - today_df["low"]) / current_price * 100
        )

        medium = today_df[
            (today_df["candle_pct"] >= 1) &
            (today_df["candle_pct"] <= 1.3)
        ]

        large = today_df[today_df["candle_pct"] > 1.3]

        if len(medium) > 3:
            return None

        if len(large) > 0:
            return None

        return symbol

    except Exception:
        return None


# -----------------------------------------
# RUN THREADED SCANNER
# -----------------------------------------
def run_scanner():
    print("\n🚀 Ultra Fast Scanner Starting...\n")

    stocks = load_stocks()
    instrument_map = get_instrument_map()

    qualified = []

    print(f"Scanning {len(stocks)} stocks using {MAX_WORKERS} threads...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []

        for stock in stocks:
            token = instrument_map.get(stock)
            if token:
                futures.append(
                    executor.submit(scan_stock, stock, token)
                )

        for future in as_completed(futures):
            result = future.result()
            if result:
                qualified.append(result)

    print("\n🎯 FINAL QUALIFIED STOCKS:\n")

    if qualified:
        for s in sorted(qualified):
            print(f"NSE:{s},")
    else:
        print("None")


# -----------------------------------------
# ENTRY
# -----------------------------------------
if __name__ == "__main__":
    run_scanner()
