import pandas as pd

# Load the downloaded instrument list
df = pd.read_csv("data/instruments.csv")

def get_token(symbol):
    result = df[df["tradingsymbol"] == symbol]

    if result.empty:
        return None

    return int(result.iloc[0]["instrument_token"])

# Test
symbol = "RELIANCE"

token = get_token(symbol)

print(f"{symbol} -> {token}")