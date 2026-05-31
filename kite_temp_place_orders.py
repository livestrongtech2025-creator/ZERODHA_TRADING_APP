"""
---------------------------------------------------------
Zerodha MIS Intraday Order Placement Utility
---------------------------------------------------------

Features:
1. Two stocks with custom capital
2. Bulk stocks with equal capital allocation
3. MIS Intraday orders only
4. Auto quantity calculation
5. Optional leverage multiplier

Author: Rahul
---------------------------------------------------------
"""

from kiteconnect import KiteConnect
import math
import time

# -------------------------
# CONFIGURATION
# -------------------------
from config import (
    ZERODHA_API_KEY,
    ZERODHA_ACCESS_TOKEN
)

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

# If you want to use leverage (example 5x)
LEVERAGE_MULTIPLIER = 1   # Keep 1 if you already calculated margin externally
# ---------------------------------------------------
# COMMON ORDER FUNCTION (MIS)
# ---------------------------------------------------
def place_mis_order(symbol, capital, transaction_type="BUY"):
    """
    Places MIS market order based on capital allocation
    """

    try:
        instrument = f"NSE:{symbol}"

        # Get LTP
        ltp_data = kite.ltp(instrument)
        ltp = ltp_data[instrument]["last_price"]

        if ltp <= 0:
            print(f"Skipping {symbol} — Invalid LTP")
            return

        # Apply leverage if required
        effective_capital = capital * LEVERAGE_MULTIPLIER

        # Quantity calculation
        quantity = math.floor(effective_capital / ltp)

        if quantity <= 0:
            print(f"Skipping {symbol} — Capital too small")
            return

        # Place MIS order
        order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type=kite.ORDER_TYPE_MARKET,
            product=kite.PRODUCT_MIS,
            validity=kite.VALIDITY_DAY
        )

        print(f"✅ Order Placed: {symbo
