"""Framework-level validation for order requests."""

from __future__ import annotations

from execution.exceptions import OrderValidationError
from execution.order_request import OrderRequest, OrderType, Product

_STOP_ORDER_TYPES = frozenset({OrderType.STOP_LOSS, OrderType.STOP_LOSS_MARKET})


class OrderValidator:
    """Validates order requests independent of any broker's rules."""

    def __init__(
        self,
        supported_order_types: frozenset[OrderType] | None = None,
        supported_products: frozenset[Product] | None = None,
    ) -> None:
        self.supported_order_types = supported_order_types or frozenset(OrderType)
        self.supported_products = supported_products or frozenset(Product)

    def validate(self, order: OrderRequest) -> None:
        """Raise OrderValidationError if the order fails framework-level rules."""

        if order.quantity <= 0:
            raise OrderValidationError("Order quantity must be greater than zero.")

        if order.order_type not in self.supported_order_types:
            raise OrderValidationError(f"Unsupported order type: {order.order_type}")

        if order.product not in self.supported_products:
            raise OrderValidationError(f"Unsupported product: {order.product}")

        if order.order_type is OrderType.LIMIT and order.price is None:
            raise OrderValidationError("Limit orders require a price.")

        if order.order_type in _STOP_ORDER_TYPES and order.trigger_price is None:
            raise OrderValidationError("Stop orders require a trigger price.")
