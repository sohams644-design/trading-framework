from datetime import datetime
from models.candle import Candle

candle = Candle(
    timestamp=datetime.now(),
    open=100,
    high=108,
    low=98,
    close=105,
    volume=15000
)

print(candle)

print("Bullish :", candle.is_bullish)
print("Bearish :", candle.is_bearish)
print("Range   :", candle.range)
print("Body    :", candle.body_size)