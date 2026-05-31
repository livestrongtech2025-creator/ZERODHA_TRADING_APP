"""
NIFTY 50 REAL-TIME TREND SCREENER (Zerodha Kite Edition)
-------------------------------------------------------
Logic:
1. Data Source: Zerodha Kite Connect (1-minute intervals).
2. Trend Engine: Uses the percentage gap between 9 EMA and 21 EMA.
3. Volatility Filter:
    - Sideways: Gap < 0.05% (Prevents false "Bear" signals in flat markets).
    - Weak Bull/Bear: Gap between 0.05% and 0.15%.
    - Strong Bull/Bear: Gap > 0.15% (Confirmed momentum).
4. Alerts: macOS System Notification + Audio 'Ping' on trend change.
5. Updates: Runs every 120 seconds.

Requirements:
- config.py (containing ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN)
- pip install plyer kiteconnect pandas numpy
-------------------------------------------------------
"""

import os
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from plyer import notification
from kiteconnect import KiteConnect
from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

# Initialize Kite
kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

NIFTY_TOKEN = 256265 
last_trend = None 

def trigger_mac_alert(new_trend):
    """Triggers macOS system popup and a vocal alert."""
    # 1. System Notification Popup
    try:
        notification.notify(
            title="Nifty 50 Trend Change!",
            message=f"Direction: {new_trend}",
            app_name="Nifty Screener",
            timeout=20000
        )
    except Exception as e:
        print(f"Notification Error: {e}")

    # 2. Audio Alert (Choose one of the two options below)
    
    # Option A: Play a system sound (like 'Ping' or 'Sosumi')
    os.system('afplay /System/Library/Sounds/Ping.aiff')
    
    # Option B: Have the Mac SPEAK the trend (Comment out the line above and uncomment this to use)
    # os.system(f'say "Trend changed to {new_trend}"')

def calculate_nifty_analysis():
    global last_trend
    
    # Fetch data
    to_date = datetime.now()
    from_date = to_date - timedelta(days=2)
    records = kite.historical_data(NIFTY_TOKEN, from_date, to_date, "minute")
    data = pd.DataFrame(records)
    
    if data.empty or len(data) < 50:
        return

    # --- Trend Engine ---
    data['EMA9'] = data['close'].ewm(span=9, adjust=False).mean()
    data['EMA21'] = data['close'].ewm(span=21, adjust=False).mean()
    
    current_price = float(data['close'].iloc[-1])
    ema9 = float(data['EMA9'].iloc[-1])
    ema21 = float(data['EMA21'].iloc[-1])
    
    gap_pct = ((ema9 - ema21) / ema21) * 100
    
    # Thresholds
    SIDEWAYS_THRESHOLD = 0.05 
    STRONG_THRESHOLD = 0.15

    if gap_pct > STRONG_THRESHOLD:
        trend = "Strong Bullish 🚀"
    elif SIDEWAYS_THRESHOLD < gap_pct <= STRONG_THRESHOLD:
        trend = "Bullish Sideways 📈"
    elif -SIDEWAYS_THRESHOLD <= gap_pct <= SIDEWAYS_THRESHOLD:
        trend = "Sideways (Rangebound) ↔️"
    elif -STRONG_THRESHOLD <= gap_pct < -SIDEWAYS_THRESHOLD:
        trend = "Bearish Sideways 📉"
    else:
        trend = "Strong Bearish 🧨"

    # --- Trend Change Detection ---
    if last_trend is not None and last_trend != trend:
        trigger_mac_alert(trend)
    last_trend = trend

    # Power Scaling
    total_power = min(100, abs(gap_pct / 0.20) * 100)
    bull_p = total_power if gap_pct > 0 else 0
    bear_p = total_power if gap_pct < 0 else 0

    # Pivot points (simplified check)
    hist = kite.historical_data(NIFTY_TOKEN, from_date.date(), to_date.date(), "day")
    df_daily = pd.DataFrame(hist)
    prev_day = df_daily.iloc[-2]
    H, L, C = float(prev_day['high']), float(prev_day['low']), float(prev_day['close'])
    
    pivot = (H + L + C) / 3
    r1, r2 = (2 * pivot) - L, pivot + (H - L)
    s1, s2 = (2 * pivot) - H, pivot - (H - L)

    output_text = f"""
--- Nifty 50 Analysis ({datetime.now().strftime('%H:%M:%S')}) ---
Current Price: {current_price:.2f}
Trend:         {trend}
Trend Power:   {total_power:.2f}% (Bull: {bull_p:.2f}% | Bear: {bear_p:.2f}%)
-----------------------------------
Resistance 2: {r2:.2f}
Resistance 1: {r1:.2f}
Pivot Point:  {pivot:.2f}
Support 1:    {s1:.2f}
Support 2:    {s2:.2f}
    """
    
    print(output_text)
    # with open("nifty_output.txt", "w") as f:
    #     f.write(output_text)

if __name__ == "__main__":
    print("Mac Screener Running...")
    while True:
        try:
            calculate_nifty_analysis()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(120)