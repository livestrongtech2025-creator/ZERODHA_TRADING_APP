import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from kiteconnect import KiteConnect, KiteTicker
import pytz
import time
import threading

from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN
from active_500 import stocks

# ==============================
# INIT
# ==============================

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

TIMEZONE = pytz.timezone("Asia/Kolkata")
LOOKBACK_DAYS = 7
SCAN_INTERVAL_SECONDS = 180  # 3 minutes

# ==============================
# WEBSOCKET TICKER — Total Bid/Offer Quantities
# ==============================

# Shared dict: { instrument_token: {"total_buy": int, "total_sell": int} }
tick_data = {}
tick_lock = threading.Lock()

def start_ticker(token_list):
    """Start KiteTicker in background thread to stream total_buy/sell quantities."""

    ticker = KiteTicker(ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN)

    def on_ticks(ws, ticks):
        with tick_lock:
            for tick in ticks:
                token = tick.get("instrument_token")
                tick_data[token] = {
                    "total_buy":  tick.get("total_buy_quantity", 0),
                    "total_sell": tick.get("total_sell_quantity", 0),
                }

    def on_connect(ws, response):
        # Subscribe in FULL mode to get total_buy/sell quantities
        ws.subscribe(token_list)
        ws.set_mode(ws.MODE_FULL, token_list)
        print(f"✅ WebSocket connected. Subscribed to {len(token_list)} tokens in FULL mode.")

    def on_error(ws, code, reason):
        print(f"⚠️  WebSocket error [{code}]: {reason}")

    def on_close(ws, code, reason):
        print(f"⚠️  WebSocket closed [{code}]: {reason}")

    ticker.on_ticks   = on_ticks
    ticker.on_connect = on_connect
    ticker.on_error   = on_error
    ticker.on_close   = on_close

    # Run in a daemon thread so it doesn't block the main loop
    t = threading.Thread(target=ticker.connect, kwargs={"threaded": True}, daemon=True)
    t.start()
    return ticker

# ==============================
# PRELOAD INSTRUMENT TOKENS
# ==============================

print("Loading instrument tokens...")
instrument_dump = kite.instruments("NSE")
instrument_df = pd.DataFrame(instrument_dump)
instrument_df = instrument_df[instrument_df["tradingsymbol"].isin(stocks)]
token_map = dict(zip(instrument_df["tradingsymbol"], instrument_df["instrument_token"]))

print(f"✅ Matched {len(token_map)} of {len(stocks)} stocks in instrument dump")

if len(token_map) == 0:
    print("❌ Token map is empty! Check that your stock symbols match NSE tradingsymbols exactly.")
    exit()

missing = [s for s in stocks if s not in token_map]
if missing:
    print(f"⚠️  {len(missing)} symbols not found in NSE dump: {missing[:10]}{'...' if len(missing) > 10 else ''}")

# Start WebSocket ticker with all matched tokens
all_tokens = list(token_map.values())
print(f"\nStarting WebSocket ticker for {len(all_tokens)} tokens...")
ticker_instance = start_ticker(all_tokens)

# Give WebSocket a moment to connect and start receiving ticks
print("Waiting 5s for WebSocket to warm up...")
time.sleep(5)

# ==============================
# INDICATORS
# ==============================

def compute_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = -delta.clip(upper=0).rolling(period).mean()
    rs    = gain / loss
    return 100 - (100 / (1 + rs))

def compute_indicators(df):
    df["ema9"]    = df["close"].ewm(span=9).mean()
    df["ema21"]   = df["close"].ewm(span=21).mean()
    df["rsi"]     = compute_rsi(df["close"])
    df["vol_avg"] = df["volume"].rolling(20).mean()
    return df

# ==============================
# TREND CLASSIFICATION (100 POINT SCALE)
# ==============================

def classify_and_score(df):
    latest = df.iloc[-1]
    score  = 0

    ema_spread   = (latest["ema9"] - latest["ema21"]) / latest["close"] * 100
    rsi          = latest["rsi"]
    volume_boost = latest["volume"] / latest["vol_avg"] if latest["vol_avg"] > 0 else 1

    # EMA contribution (max 40)
    score += np.clip(ema_spread * 8, -40, 40)

    # RSI contribution (max 30)
    if rsi > 60:
        score += np.clip((rsi - 60) * 1.5, 0, 30)
    elif rsi < 40:
        score -= np.clip((40 - rsi) * 1.5, 0, 30)

    # Volume contribution (max 30)
    if volume_boost > 1:
        score += np.clip((volume_boost - 1) * 15, 0, 30)

    # Categorization
    if score >= 60:
        trend = "STRONG_BULL"
    elif score >= 20:
        trend = "BULL"
    elif score <= -60:
        trend = "STRONG_BEAR"
    elif score <= -20:
        trend = "BEAR"
    else:
        trend = "SIDEWAYS"

    return round(score, 2), trend

# ==============================
# SINGLE SCAN RUN
# ==============================

def run_scan():
    scan_time = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*80}")
    print(f"🕐 SCAN STARTED AT: {scan_time}")
    print(f"{'='*80}")

    results = []
    skipped_no_token         = 0
    skipped_insufficient_data = 0
    skipped_api_error        = 0

    print(f"Scanning {len(token_map)} stocks across Multi-Timeframe...")

    for symbol in stocks:

        if symbol not in token_map:
            skipped_no_token += 1
            continue

        token = token_map[symbol]

        try:
            to_date   = datetime.now(TIMEZONE)
            from_date = to_date - timedelta(days=LOOKBACK_DAYS)

            total_score = 0
            trends      = []
            tf_scores   = {}

            for tf in ["2minute", "5minute", "15minute"]:
                try:
                    data = kite.historical_data(token, from_date, to_date, tf)
                    df   = pd.DataFrame(data)

                    if df.empty:
                        print(f"  ⚠️  {symbol} [{tf}]: Empty data returned")
                        continue

                    if len(df) < 30:
                        print(f"  ⚠️  {symbol} [{tf}]: Only {len(df)} candles (need 30+), skipping TF")
                        continue

                    df    = compute_indicators(df)
                    score, trend = classify_and_score(df)

                    total_score += score
                    trends.append(trend)
                    tf_scores[tf] = score

                except Exception as tf_err:
                    print(f"  ❌ {symbol} [{tf}]: TF error - {tf_err}")
                    continue

            if len(trends) >= 2:
                # Fetch total bid/offer from WebSocket tick data
                with tick_lock:
                    tick = tick_data.get(token, {})
                total_buy  = tick.get("total_buy",  0)
                total_sell = tick.get("total_sell", 0)

                bid_offer_ratio = round(total_buy / total_sell, 2) if total_sell > 0 else float("inf")

                results.append({
                    "timestamp":      scan_time,
                    "symbol":         symbol,
                    "score":          round(total_score, 2),
                    "trends":         trends,
                    "tf_scores":      tf_scores,
                    "total_bidders":  total_buy,
                    "total_offers":   total_sell,
                    "bid_offer_ratio": bid_offer_ratio,
                })
            else:
                skipped_insufficient_data += 1
                print(f"  ⛔ {symbol}: Only {len(trends)}/3 timeframes valid, skipping")

        except Exception as e:
            skipped_api_error += 1
            print(f"  ❌ {symbol}: API error - {e}")
            continue

    # ==============================
    # SUMMARY STATS
    # ==============================

    print(f"\n{'='*60}")
    print(f"📊 SCAN SUMMARY  [{scan_time}]")
    print(f"{'='*60}")
    print(f"Total stocks in list   : {len(stocks)}")
    print(f"Matched to NSE tokens  : {len(token_map)}")
    print(f"Successfully scanned   : {len(results)}")
    print(f"Skipped (no token)     : {skipped_no_token}")
    print(f"Skipped (low data)     : {skipped_insufficient_data}")
    print(f"Skipped (API errors)   : {skipped_api_error}")

    if len(results) == 0:
        print("\n❌ No results found. Check error messages above.")
        return

    # ==============================
    # RANKING & OUTPUT
    # ==============================

    sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
    top_buy  = sorted_results[:20]
    top_sell = list(reversed(sorted_results[-20:]))

    header = (
        f"\n{'TIMESTAMP':<22} {'SYMBOL':<20} {'SCORE':>7}  "
        f"{'TOTAL BIDDERS':>14}  {'TOTAL OFFERS':>13}  {'BID/OFFERS':>10}  TF TRENDS"
    )
    divider = "-" * 110

    print(f"\n{'='*110}")
    print(f"🔥 TOP 20 BUY CANDIDATES  [{scan_time}]")
    print(f"{'='*110}")
    print(header)
    print(divider)
    for r in top_buy:
        ratio_str = f"{r['bid_offer_ratio']:.2f}" if r["bid_offer_ratio"] != float("inf") else "∞"
        print(
            f"{r['timestamp']:<22} {r['symbol']:<20} {r['score']:>7}  "
            f"{r['total_bidders']:>14,}  {r['total_offers']:>13,}  {ratio_str:>10}  {r['trends']}"
        )

    print(f"\n{'='*110}")
    print(f"🔻 TOP 20 SELL CANDIDATES  [{scan_time}]")
    print(f"{'='*110}")
    print(header)
    print(divider)
    for r in top_sell:
        ratio_str = f"{r['bid_offer_ratio']:.2f}" if r["bid_offer_ratio"] != float("inf") else "∞"
        print(
            f"{r['timestamp']:<22} {r['symbol']:<20} {r['score']:>7}  "
            f"{r['total_bidders']:>14,}  {r['total_offers']:>13,}  {ratio_str:>10}  {r['trends']}"
        )

    # ==============================
    # KITE WATCHLIST FORMAT OUTPUT
    # ==============================

    buy_symbols  = [f"NSE:{r['symbol']}" for r in top_buy]
    sell_symbols = [f"NSE:{r['symbol']}" for r in top_sell]

    print(f"📋 KITE WATCHLIST FORMAT (Top 20 Buy + Top 20 Sell)")
    
    print(f"🔥 BUY  : {', '.join(buy_symbols)}")
    print(f"🔻 SELL : {', '.join(sell_symbols)}")
    
    print(f"\n✅ Next scan in {SCAN_INTERVAL_SECONDS // 60} minutes...\n")

# ==============================
# CONTINUOUS LOOP — Every 3 Minutes
# ==============================

if __name__ == "__main__":
    print("\n🚀 Multi-TF Scanner started. Press Ctrl+C to stop.\n")
    while True:
        try:
            run_scan()
            time.sleep(SCAN_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            print("\n🛑 Scanner stopped by user.")
            break
        except Exception as e:
            print(f"\n❌ Unexpected error in main loop: {e}")
            print(f"   Retrying in {SCAN_INTERVAL_SECONDS // 60} minutes...\n")
            time.sleep(SCAN_INTERVAL_SECONDS)