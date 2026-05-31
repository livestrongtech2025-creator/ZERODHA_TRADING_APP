import os
import time
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
from kiteconnect import KiteConnect
from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN
from .Nifty5X_margin import stocks

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

BATCH_SIZE = 200  # kite.ohlc() and kite.quote() both support up to 200-250
IST = pytz.timezone("Asia/Kolkata")
EPSILON = 0.05


def is_market_open():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def last_trading_day():
    d = date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    now = datetime.now(IST)
    if d == date.today() and now.hour < 9:
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d


def check_circuit(symbol, last_price, high, low, upper, lower):
    """Returns a result dict if stock touched circuit, else None."""
    touched_upper = upper > 0 and high > 0 and high >= (upper - EPSILON)
    touched_lower = lower > 0 and low > 0 and low <= (lower + EPSILON)

    if touched_upper:
        currently_on = last_price >= (upper - EPSILON)
        return {
            "Stock": symbol,
            "Circuit Type": "Upper Circuit",
            "Status": "On Circuit" if currently_on else "Touched & Reversed",
            "LTP": last_price,
            "High": high,
            "Upper Limit": upper,
            "Low": low,
            "Lower Limit": "-",
        }
    elif touched_lower:
        currently_on = last_price <= (lower + EPSILON)
        return {
            "Stock": symbol,
            "Circuit Type": "Lower Circuit",
            "Status": "On Circuit" if currently_on else "Touched & Reversed",
            "LTP": last_price,
            "High": high,
            "Upper Limit": "-",
            "Low": low,
            "Lower Limit": lower,
        }
    return None


def run_circuit_scanner():
    try:
        instrument_list = [f"NSE:{s.strip()}" for s in stocks]
        batches = [
            instrument_list[i:i + BATCH_SIZE]
            for i in range(0, len(instrument_list), BATCH_SIZE)
        ]

        market_open = is_market_open()
        trading_date = last_trading_day()
        data_source = (
            "Real-time (Market Open)"
            if market_open
            else f"Historical - {trading_date.strftime('%d %b %Y')} (Market Closed)"
        )
        print(f"Data source: {data_source}")
        print(f"Scanning {len(instrument_list)} stocks in {len(batches)} batches...")

        results = []

        for i, batch in enumerate(batches):
            print(f"  Batch {i+1}/{len(batches)}...", end=" ", flush=True)
            try:
                if market_open:
                    # Real-time: quote() gives high/low/circuit limits all in one call
                    quotes = kite.quote(batch)
                    for symbol_key, data in quotes.items():
                        if not data:
                            continue
                        ohlc = data.get("ohlc", {})
                        entry = check_circuit(
                            symbol=symbol_key.replace("NSE:", ""),
                            last_price=data.get("last_price", 0),
                            high=ohlc.get("high", 0),
                            low=ohlc.get("low", 0),
                            upper=data.get("upper_circuit_limit", 0),
                            lower=data.get("lower_circuit_limit", 0),
                        )
                        if entry:
                            entry["Volume"] = data.get("volume", 0)
                            results.append(entry)

                else:
                    # Market closed: use ohlc() for high/low, quote() for circuit limits
                    # Both are batch calls — no per-stock API calls
                    ohlc_data = kite.ohlc(batch)
                    quotes = kite.quote(batch)

                    for symbol_key in batch:
                        ohlc_entry = ohlc_data.get(symbol_key, {})
                        quote_entry = quotes.get(symbol_key, {})

                        if not ohlc_entry or not quote_entry:
                            continue

                        ohlc = ohlc_entry.get("ohlc", {})
                        high = ohlc.get("high", 0)
                        low = ohlc.get("low", 0)
                        close = ohlc.get("close", 0)
                        volume = quote_entry.get("volume", 0)
                        upper = quote_entry.get("upper_circuit_limit", 0)
                        lower_limit = quote_entry.get("lower_circuit_limit", 0)

                        entry = check_circuit(
                            symbol=symbol_key.replace("NSE:", ""),
                            last_price=close,
                            high=high,
                            low=low,
                            upper=upper,
                            lower=lower_limit,
                        )
                        if entry:
                            entry["Volume"] = volume
                            results.append(entry)

                print(f"done ({len(results)} found so far)")
                time.sleep(0.3)  # gentle rate limiting between batches

            except Exception as e:
                print(f"ERROR: {e}")
                time.sleep(1.0)
                continue

        if not results:
            return {
                "stocks": [],
                "file_path": None,
                "message": f"No stocks found on circuit. ({data_source})"
            }

        df = pd.DataFrame(results)
        df["Type_Rank"] = df["Circuit Type"].map({"Upper Circuit": 0, "Lower Circuit": 1})
        df["Status_Rank"] = df["Status"].map({"On Circuit": 0, "Touched & Reversed": 1})
        df = df.sort_values(
            by=["Type_Rank", "Status_Rank", "Volume"],
            ascending=[True, True, False]
        )
        df.drop(columns=["Type_Rank", "Status_Rank"], inplace=True)

        folder_name = "Upper Lower circuit"
        os.makedirs(folder_name, exist_ok=True)
        today_str = datetime.now().strftime("%m%d%Y")
        file_name = f"{today_str} Upper Lower Stocks.csv"
        file_path = os.path.join(folder_name, file_name)
        df.to_csv(file_path, index=False)

        return {
            "stocks": df.to_dict(orient="records"),
            "file_path": file_path,
            "message": f"Found {len(df)} stocks on circuit. {data_source}"
        }

    except Exception as e:
        return {"stocks": [], "file_path": None, "message": f"Error: {str(e)}"}