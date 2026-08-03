"""Bridges an approved RiskDecision into a broker-independent OrderRequest."""

from __future__ import annotations

from domain.risk_decision import RiskDecision
from domain.signal import Signal, SignalAction
from domain.trade import TradeDirection
from execution.order_request import OrderRequest, OrderType, Product

_SIDE_BY_ACTION: dict[SignalAction, TradeDirection] = {
    SignalAction.BUY: TradeDirection.BUY,
    SignalAction.SELL: TradeDirection.SELL,
    SignalAction.EXIT_LONG: TradeDirection.SELL,
    SignalAction.EXIT_SHORT: TradeDirection.BUY,
}


class OrderRequestBuilder:
    """Translates a Signal + RiskDecision pair into an OrderRequest.

    This is the only place that needs to know how a domain decision maps to
    a broker-independent order shape, so Risk and Execution never need to
    know about each other.
    """

    def __init__(
        self,
        exchange: str,
        order_type: OrderType = OrderType.MARKET,
        product: Product = Product.INTRADAY,
    ) -> None:
        self.exchange = exchange
        self.order_type = order_type
        self.product = product

    def build(
        self,
        signal: Signal,
        decision: RiskDecision,
        quantity: int | None = None,
    ) -> OrderRequest:
        """Build an OrderRequest for an approved entry or exit signal.

        ``quantity`` overrides ``decision.quantity``. This is required for
        exits: Risk approves exits unconditionally with ``quantity=0`` (it
        never sizes a close), so the caller must supply the actual open
        position size to close.
        """

        if not decision.approved:
            raise ValueError("Cannot build an OrderRequest from a rejected RiskDecision.")

        side = _SIDE_BY_ACTION.get(signal.action)
        if side is None:
            raise ValueError(f"Signal action {signal.action} cannot be converted to an order.")

        resolved_quantity = decision.quantity if quantity is None else quantity

        return OrderRequest(
            symbol=signal.symbol,
            exchange=self.exchange,
            side=side,
            quantity=resolved_quantity,
            order_type=self.order_type,
            product=self.product,
            tag=signal.reason,
        )
