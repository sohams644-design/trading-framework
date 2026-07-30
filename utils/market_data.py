from kiteconnect import KiteConnect
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
import os

load_dotenv()

API_KEY = os.getenv("API_KEY")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# Load instrument database
df = pd.read_csv("data/instruments.csv")


def get_token(symbol):
    symbol = symbol.upper()

    result = df[df["tradingsymbol"] == symbol]

    if result.empty:
        raise Exception(f"{symbol} not found.")

    return int(result.iloc[0]["instrument_token"])


def get_history(symbol, from_date, to_date, interval="5minute"):

    token = get_token(symbol)

    data = kite.historical_data(
        instrument_token=token,
        from_date=from_date,
        to_date=to_date,
        interval=interval
    )

    return pd.DataFrame(data)


if __name__ == "__main__":

    candles = get_history(
        "RELIANCE",
        datetime(2025, 1, 1),
        datetime(2025, 1, 5)
    )

    print(candles.head())