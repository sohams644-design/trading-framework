from kiteconnect import KiteConnect
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()

API_KEY = os.getenv("API_KEY")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# Reliance instrument token
instrument_token = 738561

from_date = datetime(2025, 1, 1)
to_date = datetime(2025, 1, 31)

data = kite.historical_data(
    instrument_token=instrument_token,
    from_date=from_date,
    to_date=to_date,
    interval="5minute"
)

print(f"Downloaded {len(data)} candles")

for candle in data[:5]:
    print(candle)