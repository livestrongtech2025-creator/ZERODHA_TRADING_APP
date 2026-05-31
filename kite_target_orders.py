from kiteconnect import KiteConnect

from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

# -------------------------
# CONFIG
# -------------------------

TARGET1_PERCENT = 0.02
TARGET2_PERCENT = 0.04
EXIT_SPLIT = 0.5
PRICE_TOLERANCE = 0.05

# -------------------------
# CONNECT
# -------------------------

positions = kite.positions()["net"]
orders = kite.orders()

# Helper: check if similar open order exists
def target_exists(symbol, txn_type, qty, price):
    for order in orders:
        if (
            order["tradingsymbol"] == symbol
            and order["transaction_type"] == txn_type
            and order["status"] in ["OPEN", "TRIGGER PENDING"]
            and order["order_type"] == "LIMIT"
            and order["quantity"] == qty
            and abs(order["price"] - price) <= PRICE_TOLERANCE
        ):
            return True
    return False

# -------------------------
# MAIN LOGIC
# -------------------------

for pos in positions:

    quantity = pos["quantity"]

    if quantity == 0 or pos["product"] != "MIS":
        continue

    symbol = pos["tradingsymbol"]
    exchange = pos["exchange"]
    avg_price = pos["average_price"]
    total_qty = abs(quantity)

    qty1 = int(total_qty * EXIT_SPLIT)
    qty2 = total_qty - qty1

    # BUY position
    if quantity > 0:
        txn_type = "SELL"
        target1 = round(avg_price * (1 + TARGET1_PERCENT), 2)
        target2 = round(avg_price * (1 + TARGET2_PERCENT), 2)

    # SELL position
    else:
        txn_type = "BUY"
        target1 = round(avg_price * (1 - TARGET1_PERCENT), 2)
        target2 = round(avg_price * (1 - TARGET2_PERCENT), 2)

    try:

        # Target 1
        if qty1 > 0 and not target_exists(symbol, txn_type, qty1, target1):
            kite.place_order(
                variety="regular",
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=txn_type,
                quantity=qty1,
                product="MIS",
                order_type="LIMIT",
                price=target1,
                validity="DAY"
            )
            print(f"✅ Target1 placed {symbol} → {qty1} @ {target1}")
        else:
            print(f"⚠️ Target1 already exists for {symbol}")

        # Target 2
        if qty2 > 0 and not target_exists(symbol, txn_type, qty2, target2):
            kite.place_order(
                variety="regular",
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=txn_type,
                quantity=qty2,
                product="MIS",
                order_type="LIMIT",
                price=target2,
                validity="DAY"
            )
            print(f"✅ Target2 placed {symbol} → {qty2} @ {target2}")
        else:
            print(f"⚠️ Target2 already exists for {symbol}")

    except Exception as e:
        print(f"❌ Error for {symbol}: {e}")

print("🚀 Duplicate-safe target processing complete.")
