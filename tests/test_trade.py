from domain.trade import Trade, TradeDirection

trade = Trade(
    symbol="RELIANCE",
    direction=TradeDirection.BUY,
    entry_price=1465.20,
    stop_loss=1460.00,
    target=1475.60,
    quantity=10
)

print(trade)