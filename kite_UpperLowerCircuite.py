"""
-----------------------------------------------------------------------
PROGRAM: Stable Upper/Lower Circuit Scanner

WHAT THIS DOES:
- Reads 1500 stocks from Nifty5X_margin.py
- Uses Zerodha quote() safely within rate limits
- Detects if stock touched:
      Upper Circuit → High >= Upper Limit
      Lower Circuit → Low <= Lower Limit
- Sorts Upper first, then Lower
- Sorts by Volume (descending)
- Saves CSV to:
      Upper Lower circuit/MMDDYYYY Upper Lower Stocks.csv
-----------------------------------------------------------------------
"""

import os
import time
import pandas as pd
from datetime import datetime
from kiteconnect import KiteConnect

# ==============================
# USER CONFIG
# ==============================
MODE = "LAST_TRADING_DAY"   # (kept for structure, quote auto-returns last session data)

# ==============================
# IMPORT STOCK LIST
# ==============================
from Nifty5X_margin import stocks
from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

# ==============================
# PREPARE SYMBOLS
# ==============================
instrument_list = [f"NSE:{s.strip()}" for s in stocks]

print(f"Scanning {len(instrument_list)} stocks safely...")

BATCH_SIZE = 250  # Zerodha allows up to 250 per quote call
upper_lower_data = []

# ==============================
# PROCESS FUNCTION
# ==============================
def process_batch(batch):
    results = []
    try:
        quotes = kite.quote(batch)

        for symbol_key, data in quotes.items():
            if not data:
                continue

            last_price = data.get("last_price", 0)
            upper = data.get("upper_circuit_limit", 0)
            lower = data.get("lower_circuit_limit", 0)
            volume = data.get("volume", 0)

            ohlc = data.get("ohlc", {})
            high = ohlc.get("high", 0)
            low = ohlc.get("low", 0)

            # Small tolerance to handle rounding
            epsilon = 0.05

            is_upper = upper > 0 and high >= (upper - epsilon)
            is_lower = lower > 0 and low <= (lower + epsilon) and low != 0

            if is_upper:
                results.append({
                    "Stock": symbol_key.replace("NSE:", ""),
                    "Circuit Type": "Upper Circuit",
                    "LTP": last_price,
                    "High": high,
                    "Upper Limit": upper,
                    "Volume": volume
                })

            elif is_lower:
                results.append({
                    "Stock": symbol_key.replace("NSE:", ""),
                    "Circuit Type": "Lower Circuit",
                    "LTP": last_price,
                    "Low": low,
                    "Lower Limit": lower,
                    "Volume": volume
                })

    except Exception as e:
        print(f"Error processing batch: {e}")

    return results

# ==============================
# EXECUTION (RATE LIMIT SAFE)
# ==============================
batches = [
    instrument_list[i:i + BATCH_SIZE]
    for i in range(0, len(instrument_list), BATCH_SIZE)
]

for batch in batches:
    upper_lower_data.extend(process_batch(batch))
    time.sleep(0.4)  # Stay within ~3 requests per second

# ==============================
# SAVE RESULTS
# ==============================
if upper_lower_data:
    df = pd.DataFrame(upper_lower_data)

    # Sort Upper first, then Lower
    df["Type_Rank"] = df["Circuit Type"].map({
        "Upper Circuit": 0,
        "Lower Circuit": 1
    })

    df = df.sort_values(by=["Type_Rank", "Volume"], ascending=[True, False])
    df.drop(columns=["Type_Rank"], inplace=True)

    # Create folder if not exists
    folder_name = "Upper Lower circuit"
    os.makedirs(folder_name, exist_ok=True)

    today_str = datetime.now().strftime("%m%d%Y")
    file_name = f"{today_str} Upper Lower Stocks.csv"
    file_path = os.path.join(folder_name, file_name)

    df.to_csv(file_path, index=False)

    print(f"\n✅ Success! Found {len(df)} stocks on circuit.")
    print(f"Saved to: {file_path}")

else:
    print("\n❌ No stocks found on circuit.")
