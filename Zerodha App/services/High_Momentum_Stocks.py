import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from kiteconnect import KiteConnect, KiteTicker
import pytz
import time
import threading

from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN
from .Nifty5X_margin import stocks

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

TIMEZONE = pytz.timezone("Asia/Kolkata")
LOOKBACK_DAYS = 7

# ==============================
# WEBSOCKET TICKER — Total Bid/Offer Quantities
# ==============================

# Shared dict: { instrument_token: {"total_buy": int, "total_sell": int} }
tick_data = {}
tick_lock = threading.Lock()
_ticker_instance = None
_ticker_started = False
_ticker_lock = threading.Lock()


def _start_ticker(token_list):
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
        ws.subscribe(token_list)
        ws.set_mode(ws.MODE_FULL, token_list)

    def on_error(ws, code, reason):
        print(f"[WebSocket] error [{code}]: {reason}")

    def on_close(ws, code, reason):
        print(f"[WebSocket] closed [{code}]: {reason}")

    ticker.on_ticks   = on_ticks
    ticker.on_connect = on_connect
    ticker.on_error   = on_error
    ticker.on_close   = on_close

    t = threading.Thread(target=ticker.connect, kwargs={"threaded": True}, daemon=True)
    t.start()
    return ticker


def _ensure_ticker(token_map):
    """Initialise the WebSocket ticker once per process lifetime."""
    global _ticker_instance, _ticker_started
    with _ticker_lock:
        if not _ticker_started:
            all_tokens = list(token_map.values())
            _ticker_instance = _start_ticker(all_tokens)
            _ticker_started = True
            # Give the socket a moment to warm up on first call
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
# SCORING
# ==============================

def classify_and_score(df):
    latest = df.iloc[-1]
    score  = 0

    ema_spread   = (latest["ema9"] - latest["ema21"]) / latest["close"] * 100
    rsi          = latest["rsi"]
    volume_boost = latest["volume"] / latest["vol_avg"] if latest["vol_avg"] > 0 else 1

    # EMA contribution (max +/-40)
    score += np.clip(ema_spread * 8, -40, 40)

    # RSI contribution (max +/-30)
    if rsi > 60:
        score += np.clip((rsi - 60) * 1.5, 0, 30)
    elif rsi < 40:
        score -= np.clip((40 - rsi) * 1.5, 0, 30)

    # Volume contribution (max +30)
    if volume_boost > 1:
        score += np.clip((volume_boost - 1) * 15, 0, 30)

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
# MAIN FUNCTION
# ==============================

def run_momentum_scanner():
    try:
        # Preload tokens
        instrument_dump = kite.instruments("NSE")
        instrument_df   = pd.DataFrame(instrument_dump)
        instrument_df   = instrument_df[instrument_df["tradingsymbol"].isin(stocks)]
        token_map       = dict(zip(instrument_df["tradingsymbol"], instrument_df["instrument_token"]))

        if not token_map:
            return {"buyers": [], "sellers": [], "message": "Token map is empty — check symbol list."}

        # Ensure WebSocket ticker is running (starts once, stays alive)
        _ensure_ticker(token_map)

        results = []

        for symbol in stocks:
            if symbol not in token_map:
                continue

            token = token_map[symbol]

            try:
                to_date   = datetime.now(TIMEZONE)
                from_date = to_date - timedelta(days=LOOKBACK_DAYS)

                total_score = 0
                trends      = []

                for tf in ["2minute", "5minute", "15minute"]:
                    try:
                        data = kite.historical_data(token, from_date, to_date, tf)
                        df   = pd.DataFrame(data)

                        if df.empty or len(df) < 30:
                            continue

                        df = compute_indicators(df)
                        score, trend = classify_and_score(df)

                        total_score += score
                        trends.append(trend)

                    except Exception:
                        continue

                # Require at least 2 of 3 timeframes (matches kite_scanner logic)
                if len(trends) >= 2:
                    with tick_lock:
                        tick = tick_data.get(token, {})
                    total_buy  = tick.get("total_buy",  0)
                    total_sell = tick.get("total_sell", 0)
                    bid_offer_ratio = round(total_buy / total_sell, 2) if total_sell > 0 else None

                    # Pad to always have 3 TF entries for template rendering
                    while len(trends) < 3:
                        trends.append("Low Data")

                    results.append({
                        "symbol":          symbol,
                        "score":           round(total_score, 2),
                        "tf_2min":         trends[0],
                        "tf_5min":         trends[1],
                        "tf_15min":        trends[2],
                        "total_bidders":   total_buy,
                        "total_offers":    total_sell,
                        "bid_offer_ratio": bid_offer_ratio,
                    })

            except Exception:
                continue

        if not results:
            return {"buyers": [], "sellers": [], "message": "No results found."}

        sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)

        top_buyers  = sorted_results[:20]
        top_sellers = list(reversed(sorted_results[-20:]))

        return {
            "buyers":  top_buyers,
            "sellers": top_sellers,
            "message": f"Scanned {len(results)} stocks successfully.",
        }

    except Exception as e:
        return {"buyers": [], "sellers": [], "message": f"Error: {str(e)}"}
