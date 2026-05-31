from kiteconnect import KiteConnect
import math
import time
from config import (
    ZERODHA_API_KEY,
    ZERODHA_ACCESS_TOKEN
)

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)
# ------------------------------
# CAPITAL CONFIGURATION
# ------------------------------

TOTAL_CAPITAL = 600000 * 5
TOTAL_STOCKS = 2
capital_per_stock = TOTAL_CAPITAL / TOTAL_STOCKS
product_type = "MIS"   # Change to "MIS" when needed

# ------------------------------
# STOCK ARRAYS
# ------------------------------

# 🔴 Stocks to SELL at MIS Market
sell_stocks = [
        "ATGL","ELECTCAST"
]
# sell_stocks = [
#   "bluejet"
# ]
# 🟢 Stocks to BUY at MIS Market
# buy_stocks = [
#   "LINDEINDIA","CENTURYPLY","BAJFINANCE","AEGISLOG","KEI","NTPC","CREDITACC","ZENTEC","PTCIL","GODREJIND","NLCINDIA","PVRINOX","AEGISVOPAK","KPRMILL","APLAPOLLO","IDFCFIRSTB","ASTRAL","DOMS","AAVAS"
# ]
buy_stocks = [
#   "GVPIL"
 ]
# ======================================
# INITIALIZE KITE
# ======================================

# ======================================
# FUNCTION TO PLACE MARKET ORDER
# ======================================

def place_market_order(symbol, transaction_type):
    try:
        # 1️⃣ Fetch LTP
        ltp_data = kite.ltp(f"NSE:{symbol}")
        ltp = ltp_data[f"NSE:{symbol}"]["last_price"]

        # 2️⃣ Calculate Quantity
        quantity = math.floor(capital_per_stock / ltp)

        if quantity <= 0:
            print(f"Skipping {symbol} — capital too small for LTP {ltp}")
            return

        # 3️⃣ Place MARKET Order
        order_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            product=kite.PRODUCT_CNC if product_type == "CNC" else kite.PRODUCT_MIS,
            order_type=kite.ORDER_TYPE_MARKET
        )

        print(f"{transaction_type} Order placed for {symbol}")
        print(f"LTP: {ltp} | Qty: {quantity} | Approx Value: {quantity * ltp}")
        print(f"Order ID: {order_id}")
        print("---------------------------------------------------")

        time.sleep(0.3)

    except Exception as e:
        print(f"Error placing order for {symbol}: {e}")


# ======================================
# EXECUTE SELL ORDERS
# ======================================

print("🔴 Placing SELL Orders...\n")

for symbol in sell_stocks:
    place_market_order(symbol, kite.TRANSACTION_TYPE_SELL)


# ======================================
# EXECUTE BUY ORDERS
# ======================================

print("🟢 Placing BUY Orders...\n")

for symbol in buy_stocks:
    place_market_order(symbol, kite.TRANSACTION_TYPE_BUY)
