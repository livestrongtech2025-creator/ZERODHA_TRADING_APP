"""
===========================================================
NSE 5X Margin Stock Daily Bias Ranking System
===========================================================

PURPOSE:
This script scans all NSE equity stocks eligible for 5X margin
and ranks the Top 200 stocks daily based on bullish probability.

The output is a CSV file containing:
- NSE Symbol (formatted for TradingView)
- Bias (Bullish / Bearish)
- Bull %
- Bear %

-----------------------------------------------------------
HOW THE LOGIC WORKS
-----------------------------------------------------------

1. STOCK UNIVERSE
   - Fetch all NSE equity instruments from Zerodha Kite.
   - Filter only stocks present in Nifty5X_margin list.

2. DATA COLLECTION
   - Pull last ~60 days of daily OHLCV data for each stock.

3. SCORING SYSTEM (Total = 100 Points)

   A) Volume Strength (0–40 points)
      - Compare today's volume with 20-day average volume.
      - Higher relative volume = higher probability.
      - Captures accumulation / distribution activity.

   B) Breakout Strength (0–30 points)
      - If today's close > yesterday high → Bullish breakout.
      - If today's close < yesterday low → Bearish breakdown.
      - Strong price expansion gets full score.

   C) RSI Strength (0–15 points)
      - RSI near 50 is considered balanced and strong.
      - Extreme RSI reduces score.
      - Helps avoid overbought/oversold traps.

   D) EMA Trend Strength (0–15 points)
      - If price > 15 EMA → bullish structure.
      - If price < 15 EMA → weak structure.
      - Confirms trend direction.

4. FINAL BIAS CALCULATION
   - Total score is capped between 0 and 100.
   - Bull % = Total Score
   - Bear % = 100 - Bull %

5. RANKING
   - Stocks are sorted by Bull % (descending).
   - Top 200 stocks are saved daily.

6. OUTPUT
   - CSV file saved in folder: StockBias/
   - Format: YYYY-MM-DD_5X_Share_Bias.csv

-----------------------------------------------------------
WHAT THIS SYSTEM IDENTIFIES
-----------------------------------------------------------

• High volume breakout candidates
• Trend continuation stocks
• Strong momentum setups
• Institutional accumulation signals

This is a probability ranking model,
NOT a guaranteed prediction system.

-----------------------------------------------------------
Author Notes:
Modify scoring weights to adjust aggressiveness.
Increase volume weight for breakout strategy.
Increase EMA weight for trend-following strategy.
===========================================================
"""

from kiteconnect import KiteConnect
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os

# --- CONFIGURATION ---
from config import (
    ZERODHA_API_KEY,
    ZERODHA_ACCESS_TOKEN
)

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

# --- PARAMETERS ---
N_DAYS_AVG = 20
RSI_PERIOD = 14
EMA_PERIOD = 15
TOP_N = 200

# --- LOAD NIFTY5X MARGIN STOCKS ---
def load_nifty5X():
    from Nifty5X_margin import stocks
    return set(stocks)

# --- GET NSE STOCK LIST ---
def get_nse_stocks():
    instruments = kite.instruments("NSE")
    stocks = [
        i for i in instruments
        if i['segment'] == 'NSE' and i['instrument_type'] == 'EQ'
    ]
    nifty5X_symbols = load_nifty5X()
    stocks = [s for s in stocks if s['tradingsymbol'] in nifty5X_symbols]
    return stocks

# --- FETCH HISTORICAL DATA ---
def get_ohlcv(token, from_date, to_date):
    try:
        data = kite.historical_data(
            instrument_token=token,
            from_date=from_date,
            to_date=to_date,
            interval="day"
        )
        df = pd.DataFrame(data)
        if df.empty:
            return df
        df.set_index('date', inplace=True)
        return df
    except:
        return pd.DataFrame()

# --- RSI ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# --- EMA ---
def calculate_ema(series, period=15):
    return series.ewm(span=period, adjust=False).mean()

# --- SCORING FUNCTION ---
def calculate_score(df):

    if df.empty or len(df) < N_DAYS_AVG + 2:
        return None

    avg_vol = df['volume'].iloc[-N_DAYS_AVG-1:-1].mean()
    vol_today = df['volume'].iloc[-1]
    close_today = df['close'].iloc[-1]
    high_yesterday = df['high'].iloc[-2]
    low_yesterday = df['low'].iloc[-2]

    # --- Volume Score (0–40) ---
    vol_ratio = vol_today / avg_vol if avg_vol > 0 else 0
    volume_score = min(vol_ratio * 20, 40)

    # --- Breakout Score (0–30) ---
    breakout_score = 0
    bias = None

    if close_today > high_yesterday:
        breakout_score = 30
        bias = "BULLISH BIAS"
    elif close_today < low_yesterday:
        breakout_score = 30
        bias = "BEARISH BIAS"

    # --- RSI Score (0–15) ---
    rsi_series = calculate_rsi(df['close'], RSI_PERIOD)
    rsi = rsi_series.iloc[-1]

    rsi_score = 15 - abs(50 - rsi) * 0.3
    rsi_score = max(0, min(rsi_score, 15))

    # --- EMA Score (0–15) ---
    ema_series = calculate_ema(df['close'], EMA_PERIOD)
    ema = ema_series.iloc[-1]

    if close_today > ema:
        ema_score = 15
        if not bias:
            bias = "BULLISH BIAS"
    else:
        ema_score = 5
        if not bias:
            bias = "BEARISH BIAS"

    # --- Final Score ---
    total_score = volume_score + breakout_score + rsi_score + ema_score
    total_score = min(100, max(0, total_score))

    bull_percent = int(total_score)
    bear_percent = 100 - bull_percent

    return bias, bull_percent, bear_percent

# --- MAIN ---
def main():

    today = date.today()
    from_date = today - timedelta(days=60)
    to_date = today

    stocks = get_nse_stocks()
    results = []

    print(f"Scoring {len(stocks)} 5X Margin stocks...")

    for s in stocks:
        df = get_ohlcv(s['instrument_token'], from_date, to_date)

        score_data = calculate_score(df)

        if score_data:
            bias, bull_percent, bear_percent = score_data
            results.append({
                "symbol": f"NSE:{s['tradingsymbol']},",
                "bias": bias,
                "bull_percent": bull_percent,
                "bear_percent": bear_percent
            })

    if not results:
        print("No valid data processed.")
        return

    # Sort by Bull %
    results = sorted(results, key=lambda x: x['bull_percent'], reverse=True)

    # Keep Top 200
    results = results[:TOP_N]

    # Create folder
    folder = "Stock Bias"
    os.makedirs(folder, exist_ok=True)

    filename = f"{today}_5X_Share_Bias.csv"
    filepath = os.path.join(folder, filename)

    df_output = pd.DataFrame(results)
    df_output.to_csv(filepath, index=False)

    print(f"\nTop {TOP_N} stocks saved to {filepath}")

if __name__ == "__main__":
    main()

