from models.trade import Trade


class RiskManager:
    def __init__(self, max_risk_per_trade: float):
        self.max_risk_per_trade = max_risk_per_trade

    def calculate_quantity(self, trade: Trade) -> int:

        risk_per_share = abs(trade.entry_price - trade.stop_loss)

        if risk_per_share == 0:
            return 0

        quantity = int(self.max_risk_per_trade / risk_per_share)

        return quantity