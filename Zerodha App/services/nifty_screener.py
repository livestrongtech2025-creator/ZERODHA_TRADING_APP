import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

# Initialize Kite
kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

NIFTY_TOKEN = 256265


def run_nifty_screener():
    try:
        # Fetch 1-minute data
        to_date = datetime.now()
        from_date = to_date - timedelta(days=2)

        records = kite.historical_data(NIFTY_TOKEN, from_date, to_date, "minute")
        data = pd.DataFrame(records)

        if data.empty or len(data) < 50:
            return {"error": "Not enough data"}

        # ==========================
        # TREND ENGINE (UNCHANGED)
        # ==========================

        data['EMA9'] = data['close'].ewm(span=9, adjust=False).mean()
        data['EMA21'] = data['close'].ewm(span=21, adjust=False).mean()

        current_price = float(data['close'].iloc[-1])
        ema9 = float(data['EMA9'].iloc[-1])
        ema21 = float(data['EMA21'].iloc[-1])

        gap_pct = ((ema9 - ema21) / ema21) * 100

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

        # ==========================
        # POWER SCALING (UNCHANGED)
        # ==========================

        total_power = min(100, abs(gap_pct / 0.20) * 100)
        bull_p = total_power if gap_pct > 0 else 0
        bear_p = total_power if gap_pct < 0 else 0

        # ==========================
        # DAILY PIVOTS (UNCHANGED)
        # ==========================

        hist = kite.historical_data(
            NIFTY_TOKEN,
            from_date.date(),
            to_date.date(),
            "day"
        )

        df_daily = pd.DataFrame(hist)

        if len(df_daily) < 2:
            return {"error": "Not enough daily data"}

        prev_day = df_daily.iloc[-2]

        H = float(prev_day['high'])
        L = float(prev_day['low'])
        C = float(prev_day['close'])

        pivot = (H + L + C) / 3
        r1 = (2 * pivot) - L
        r2 = pivot + (H - L)
        s1 = (2 * pivot) - H
        s2 = pivot - (H - L)

        # ==========================
        # RETURN FOR WEB
        # ==========================

        return {
            "time": datetime.now().strftime('%H:%M:%S'),
            "price": round(current_price, 2),
            "trend": trend,
            "trend_power": round(total_power, 2),
            "bull_power": round(bull_p, 2),
            "bear_power": round(bear_p, 2),
            "r2": round(r2, 2),
            "r1": round(r1, 2),
            "pivot": round(pivot, 2),
            "s1": round(s1, 2),
            "s2": round(s2, 2),
        }

    except Exception as e:
        return {"error": str(e)}