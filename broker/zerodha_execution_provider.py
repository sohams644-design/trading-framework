"""Zerodha execution-provider adapter."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from config import settings
from execution.exceptions import ExecutionProviderError
from execution.execution_result import ExecutionResult, OrderStatus
from execution.order_request import OrderRequest
from execution.provider import ExecutionProvider

logger = logging.getLogger(__name__)

_KITE_STATUS_TO_ORDER_STATUS: dict[str, OrderStatus] = {
    "COMPLETE": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "OPEN": OrderStatus.PENDING,
    "TRIGGER PENDING": OrderStatus.PENDING,
    "PUT ORDER REQ RECEIVED": OrderStatus.PENDING,
    "VALIDATION PENDING": OrderStatus.PENDING,
    "OPEN PENDING": OrderStatus.PENDING,
    "MODIFY VALIDATION PENDING": OrderStatus.PENDING,
    "MODIFY PENDING": OrderStatus.PENDING,
    "CANCEL PENDING": OrderStatus.PENDING,
}


class ZerodhaExecutionProvider(ExecutionProvider):
    """Execution adapter that isolates Kite Connect order calls from the framework."""

    VARIETY = "regular"

    def __init__(self, kite_client: Any | None = None) -> None:
        self.kite = kite_client or self._build_kite_client()

    def place_order(self, order: OrderRequest) -> ExecutionResult:
        """Submit an order to Zerodha and return the framework execution result."""

        try:
            broker_order_id = self.kite.place_order(
                variety=self.VARIETY,
                exchange=order.exchange,
                tradingsymbol=order.symbol,
                transaction_type=order.side.value,
                quantity=order.quantity,
                product=order.product.value,
                order_type=order.order_type.value,
                price=order.price,
                trigger_price=order.trigger_price,
                tag=order.tag,
            )
        except Exception as error:
            raise ExecutionProviderError(f"Zerodha place_order failed: {error}") from error

        return ExecutionResult(
            success=True,
            status=OrderStatus.SUBMITTED,
            timestamp=datetime.now(),
            broker_order_id=str(broker_order_id),
        )

    def cancel_order(self, broker_order_id: str) -> ExecutionResult:
        """Cancel a previously submitted Zerodha order."""

        try:
            result_id = self.kite.cancel_order(variety=self.VARIETY, order_id=broker_order_id)
        except Exception as error:
            raise ExecutionProviderError(f"Zerodha cancel_order failed: {error}") from error

        return ExecutionResult(
            success=True,
            status=OrderStatus.CANCELLED,
            timestamp=datetime.now(),
            broker_order_id=str(result_id),
        )

    def modify_order(self, broker_order_id: str, order: OrderRequest) -> ExecutionResult:
        """Modify a previously submitted Zerodha order."""

        try:
            result_id = self.kite.modify_order(
                variety=self.VARIETY,
                order_id=broker_order_id,
                quantity=order.quantity,
                price=order.price,
                order_type=order.order_type.value,
                trigger_price=order.trigger_price,
            )
        except Exception as error:
            raise ExecutionProviderError(f"Zerodha modify_order failed: {error}") from error

        return ExecutionResult(
            success=True,
            status=OrderStatus.PENDING,
            timestamp=datetime.now(),
            broker_order_id=str(result_id),
        )

    def get_order_status(self, broker_order_id: str) -> ExecutionResult:
        """Fetch the current status of a previously submitted Zerodha order."""

        try:
            history = self.kite.order_history(order_id=broker_order_id)
        except Exception as error:
            raise ExecutionProviderError(
                f"Zerodha get_order_status failed: {error}"
            ) from error

        latest = history[-1]
        kite_status = latest["status"]
        status = _KITE_STATUS_TO_ORDER_STATUS.get(kite_status)
        if status is None:
            logger.warning("Unmapped Zerodha order status: %s", kite_status)
            status = OrderStatus.UNKNOWN

        return ExecutionResult(
            success=True,
            status=status,
            timestamp=datetime.now(),
            broker_order_id=broker_order_id,
            message=latest.get("status_message"),
        )

    @staticmethod
    def _build_kite_client() -> Any:
        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=settings.api_key)
        if settings.access_token:
            kite.set_access_token(settings.access_token)
        return kite
