from kiteconnect import KiteConnect
from config import ZERODHA_API_KEY, ZERODHA_ACCESS_TOKEN

kite = KiteConnect(api_key=ZERODHA_API_KEY)
kite.set_access_token(ZERODHA_ACCESS_TOKEN)

orders = kite.orders()

for order in orders:
    
    status = order["status"]
    variety = order["variety"]
    order_id = order["order_id"]
    symbol = order["tradingsymbol"]

    if status in ["OPEN", "TRIGGER PENDING", "AMO REQ RECEIVED"]:
        try:
            kite.cancel_order(  
                variety=variety,
                order_id=order_id
            )
            print(f"✅ Cancelled: {symbol} | {order_id} | {status}")
        except Exception as e:
            print(f"❌ Error cancelling {symbol} | {order_id}:", e)

print("🚀 All OPEN + AMO orders processed.")