from risk.risk_manager import RiskManager
from domain.trade import Trade, TradeDirection

trade = Trade(
    symbol="RELIANCE",
    direction=TradeDirection.BUY,
    entry_price=100,
    stop_loss=98,
    target=106,
    quantity=0
)

risk_manager = RiskManager(max_risk_per_trade=50)

quantity = risk_manager.calculate_quantity(trade)

print(f"Suggested Quantity: {quantity}")