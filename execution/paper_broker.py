"""In-memory execution provider used for testing and paper trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import count

from execution.exceptions import OrderNotFoundError
from execution.execution_result import ExecutionResult, OrderStatus
from execution.order_request import OrderRequest
from execution.provider import ExecutionProvider


@dataclass(slots=True)
class _PaperOrder:
    request: OrderRequest
    status: OrderStatus


class PaperExecutionProvider(ExecutionProvider):
    """Deterministic in-memory stand-in for a real broker.

    Accepts orders and tracks their state without simulating fills,
    pricing, or market behaviour.
    """

    def __init__(self) -> None:
        self._orders: dict[str, _PaperOrder] = {}
        self._id_sequence = count(1)

    def place_order(self, order: OrderRequest) -> ExecutionResult:
        """Accept an order and assign it a deterministic fake order id."""

        broker_order_id = self._next_order_id()
        self._orders[broker_order_id] = _PaperOrder(order, OrderStatus.SUBMITTED)
        return ExecutionResult(
            success=True,
            status=OrderStatus.SUBMITTED,
            timestamp=datetime.now(),
            broker_order_id=broker_order_id,
        )

    def cancel_order(self, broker_order_id: str) -> ExecutionResult:
        """Mark a stored order as cancelled."""

        paper_order = self._get_order(broker_order_id)
        paper_order.status = OrderStatus.CANCELLED
        return ExecutionResult(
            success=True,
            status=OrderStatus.CANCELLED,
            timestamp=datetime.now(),
            broker_order_id=broker_order_id,
        )

    def modify_order(self, broker_order_id: str, order: OrderRequest) -> ExecutionResult:
        """Replace the stored request for an order, keeping its current status."""

        paper_order = self._get_order(broker_order_id)
        paper_order.request = order
        return ExecutionResult(
            success=True,
            status=paper_order.status,
            timestamp=datetime.now(),
            broker_order_id=broker_order_id,
        )

    def get_order_status(self, broker_order_id: str) -> ExecutionResult:
        """Return the last known status of a stored order."""

        paper_order = self._get_order(broker_order_id)
        return ExecutionResult(
            success=True,
            status=paper_order.status,
            timestamp=datetime.now(),
            broker_order_id=broker_order_id,
        )

    def _next_order_id(self) -> str:
        return f"PAPER-{next(self._id_sequence):06d}"

    def _get_order(self, broker_order_id: str) -> _PaperOrder:
        try:
            return self._orders[broker_order_id]
        except KeyError as error:
            raise OrderNotFoundError(
                f"Unknown paper order id: {broker_order_id}"
            ) from error
