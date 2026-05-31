"""
reversal_scanner.py
--------------------
Scans stocks from active_500.py for intraday reversal candidates.

Logic:
  - PLUS stocks (today up vs prev close): look for signs they'll reverse DOWN
      Signals: total_offer_qty > total_bid_qty, RSI > 55, price > VWAP,
               EMA9 weakening vs EMA21, bearish candle, volume spike

  - MINUS stocks (today down vs prev close): look for signs they'll reverse UP
      Signals: total_bid_qty > total_offer_qty, RSI < 45, price < VWAP,
               EMA9 strengthening vs EMA21, bullish candle, volume spike

Output: Top 15 from each group, sorted by reversal conviction score.
        Followed by NSE watchlist string for Chrome plugin.

Usage:
    python reversal_scanner.py
"""

import time
from datetime import datetime, date
from kiteconnect import KiteConnect

from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN
from active_500 import stocks

# ==============================
# INIT
# ==============================

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

# ==============================
# CONFIG
# ==============================

TOP_N            = 15
CANDLE_INTERVAL  = "5minute"
CANDLE_COUNT     = 50
BATCH_SIZE       = 50
API_DELAY        = 0.35        # seconds between batch calls
MIN_SCORE        = 10          # very lenient — just needs at least 1-2 signals

# ==============================
# HELPERS
# ==============================

def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calc_ema(closes, period):
    if len(closes) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = [sum(closes[:period]) / period]
    for price in closes[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def calc_vwap(candles):
    cum_tp_vol = 0
    cum_vol = 0
    for c in candles:
        tp = (c["high"] + c["low"] + c["close"]) / 3
        cum_tp_vol += tp * c["volume"]
        cum_vol += c["volume"]
    if cum_vol == 0:
        return None
    return cum_tp_vol / cum_vol


def avg_volume(candles, exclude_last=1):
    vols = [c["volume"] for c in candles[:-exclude_last]]
    return sum(vols) / len(vols) if vols else 0


def bid_offer_ratio(total_bid, total_offer):
    if total_offer == 0:
        return float("inf")
    return round(total_bid / total_offer, 3)


# ==============================
# BATCH QUOTE FETCH
# ==============================

def fetch_quotes(instrument_tokens):
    all_quotes = {}
    for batch in chunk(instrument_tokens, BATCH_SIZE):
        try:
            q = kite.quote(batch)
            all_quotes.update(q)
        except Exception as e:
            print(f"  [WARN] Quote batch failed: {e}")
        time.sleep(API_DELAY)
    return all_quotes


# ==============================
# CANDLE FETCH
# ==============================

def fetch_candles(instrument_token):
    try:
        today = date.today()
        candles = kite.historical_data(
            instrument_token=instrument_token,
            from_date=today,
            to_date=today,
            interval=CANDLE_INTERVAL
        )
        return candles[-CANDLE_COUNT:] if len(candles) >= CANDLE_COUNT else candles
    except Exception as e:
        return []


# ==============================
# SCORE EACH STOCK
# ==============================

def score_stock(symbol, quote, candles):
    ltp        = quote.get("last_price", 0)
    prev_close = quote.get("ohlc", {}).get("close", 0)
    depth      = quote.get("depth", {})

    if prev_close == 0 or ltp == 0:
        return None

    pct_change = ((ltp - prev_close) / prev_close) * 100

    # --- Depth ---
    bids   = depth.get("buy", [])
    offers = depth.get("sell", [])
    total_bid_qty   = sum(b.get("quantity", 0) for b in bids)
    total_offer_qty = sum(o.get("quantity", 0) for o in offers)
    ratio           = bid_offer_ratio(total_bid_qty, total_offer_qty)

    is_plus  = pct_change >= 0
    is_minus = pct_change < 0

    score = 0

    # --- Candle-based signals (optional — scored but not required) ---
    rsi            = None
    vwap           = None
    ema9_now       = None
    ema21_now      = None
    vol_spike      = False
    bearish_candle = False
    bullish_candle = False

    if len(candles) >= 10:
        closes  = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]

        rsi  = calc_rsi(closes)
        vwap = calc_vwap(candles)

        ema9  = calc_ema(closes, 9)
        ema21 = calc_ema(closes, 21)

        if len(ema9) >= 2 and len(ema21) >= 2:
            ema9_now  = ema9[-1]
            ema21_now = ema21[-1]

        avg_vol  = avg_volume(candles, exclude_last=1)
        curr_vol = volumes[-1]
        vol_spike = (curr_vol > avg_vol * 1.4) if avg_vol > 0 else False

        last_candle    = candles[-1]
        bearish_candle = last_candle["close"] < last_candle["open"]
        bullish_candle = last_candle["close"] > last_candle["open"]

    # =====================
    # SCORING — LENIENT
    # Each signal independently adds points.
    # Primary bid/offer weighted highest but NOT strictly required.
    # =====================

    if is_plus:
        # Looking for reversal DOWN

        if total_offer_qty > total_bid_qty:
            score += 30
        elif total_offer_qty > total_bid_qty * 0.8:
            score += 10

        if rsi is not None:
            if rsi > 70:
                score += 20
            elif rsi > 60:
                score += 12
            elif rsi > 55:
                score += 6

        if vwap and ltp > vwap:
            score += 8

        if ema9_now is not None and ema21_now is not None:
            if ema9_now < ema21_now:
                score += 8
            elif ema9_now < ema21_now * 1.002:
                score += 4

        if vol_spike and bearish_candle:
            score += 10
        elif vol_spike:
            score += 4
        elif bearish_candle:
            score += 4

    elif is_minus:
        # Looking for reversal UP

        if total_bid_qty > total_offer_qty:
            score += 30
        elif total_bid_qty > total_offer_qty * 0.8:
            score += 10

        if rsi is not None:
            if rsi < 30:
                score += 20
            elif rsi < 40:
                score += 12
            elif rsi < 45:
                score += 6

        if vwap and ltp < vwap:
            score += 8

        if ema9_now is not None and ema21_now is not None:
            if ema9_now > ema21_now:
                score += 8
            elif ema9_now > ema21_now * 0.998:
                score += 4

        if vol_spike and bullish_candle:
            score += 10
        elif vol_spike:
            score += 4
        elif bullish_candle:
            score += 4

    return {
        "symbol":          symbol,
        "ltp":             round(ltp, 2),
        "total_bid_qty":   total_bid_qty,
        "total_offer_qty": total_offer_qty,
        "ratio":           ratio,
        "score":           score,
        "is_plus":         is_plus,
        "is_minus":        is_minus,
    }


# ==============================
# DISPLAY
# ==============================

def print_table(title, rows, reversal_dir):
    arrow = "▼ EXPECTED TO FALL" if reversal_dir == "down" else "▲ EXPECTED TO RISE"
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  {title}  |  {arrow}")
    print(sep)
    print(
        f"{'#':<4} {'Symbol':<16} {'LTP':>9} "
        f"{'Total Bidders':>14} {'Total Offers':>13} {'B/O Ratio':>10} {'Score':>6}"
    )
    print("-" * 72)
    for i, r in enumerate(rows, 1):
        print(
            f"{i:<4} {r['symbol']:<16} {r['ltp']:>9.2f} "
            f"{r['total_bid_qty']:>14,} {r['total_offer_qty']:>13,} "
            f"{r['ratio']:>10.3f} {r['score']:>6}"
        )
    print(sep)


def print_watchlist(label, rows):
    """Print comma-separated NSE:SYMBOL list for Chrome plugin."""
    watchlist = ", ".join(f"NSE:{r['symbol']}" for r in rows)
    print(f"\n── {label} ──")
    print(watchlist)


# ==============================
# MAIN
# ==============================

def main():
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  REVERSAL SCANNER  |  {datetime.now().strftime('%d-%b-%Y  %H:%M:%S')}")
    print(f"  Universe: {len(stocks)} stocks")
    print(sep)

    instrument_keys = [f"NSE:{s}" for s in stocks]

    print("\nFetching live quotes ...")
    quotes = fetch_quotes(instrument_keys)
    print(f"  Quotes received: {len(quotes)}\n")

    plus_candidates  = []
    minus_candidates = []

    total = len(stocks)
    for idx, symbol in enumerate(stocks, 1):
        key   = f"NSE:{symbol}"
        quote = quotes.get(key)
        if not quote:
            continue

        instrument_token = quote.get("instrument_token")
        if not instrument_token:
            continue

        if idx % 50 == 0 or idx == total:
            print(f"  Analysing candles ... {idx}/{total}")

        candles = fetch_candles(instrument_token)
        time.sleep(API_DELAY)

        result = score_stock(symbol, quote, candles)
        if result is None:
            continue

        if result["score"] < MIN_SCORE:
            continue

        if result["is_plus"]:
            plus_candidates.append(result)
        elif result["is_minus"]:
            minus_candidates.append(result)

    plus_candidates.sort(key=lambda x: x["score"], reverse=True)
    minus_candidates.sort(key=lambda x: x["score"], reverse=True)

    top_plus  = plus_candidates[:TOP_N]
    top_minus = minus_candidates[:TOP_N]

    # ---- Tables ----
    print_table(f"UP TODAY — LIKELY TO REVERSE DOWN  (Top {TOP_N})", top_plus,  "down")
    print_table(f"DOWN TODAY — LIKELY TO REVERSE UP  (Top {TOP_N})", top_minus, "up")

    # ---- Chrome Plugin Watchlists ----
    print(f"\n{sep}")
    print("  CHROME PLUGIN WATCHLISTS")
    print(sep)
    print_watchlist(f"Reversal Down — Up stocks expected to fall ({len(top_plus)})", top_plus)
    print_watchlist(f"Reversal Up   — Down stocks expected to rise ({len(top_minus)})", top_minus)
    print(f"\n{sep}")
    print(f"  Scan complete  |  {datetime.now().strftime('%H:%M:%S')}")
    print(sep + "\n")


if __name__ == "__main__":
    main()