"""Orchestrates order validation and submission through an execution provider."""

from __future__ import annotations

from datetime import datetime

from execution.exceptions import OrderValidationError
from execution.execution_result import ExecutionResult, OrderStatus
from execution.order_request import OrderRequest
from execution.order_validator import OrderValidator
from execution.provider import ExecutionProvider


class OrderManager:
    """Validates order requests and delegates execution to a provider."""

    def __init__(
        self,
        provider: ExecutionProvider,
        validator: OrderValidator | None = None,
    ) -> None:
        self.provider = provider
        self.validator = validator or OrderValidator()

    def submit_order(self, order: OrderRequest) -> ExecutionResult:
        """Validate and submit an order request, rejecting it locally if invalid."""

        try:
            self.validator.validate(order)
        except OrderValidationError as error:
            return self._rejected(error)

        return self.provider.place_order(order)

    def cancel_order(self, broker_order_id: str) -> ExecutionResult:
        """Cancel a previously submitted order via the provider."""

        return self.provider.cancel_order(broker_order_id)

    def modify_order(self, broker_order_id: str, order: OrderRequest) -> ExecutionResult:
        """Modify a previously submitted order via the provider."""

        return self.provider.modify_order(broker_order_id, order)

    def get_order_status(self, broker_order_id: str) -> ExecutionResult:
        """Return the current status of a previously submitted order."""

        return self.provider.get_order_status(broker_order_id)

    @staticmethod
    def _rejected(error: OrderValidationError) -> ExecutionResult:
        return ExecutionResult(
            success=False,
            status=OrderStatus.REJECTED,
            timestamp=datetime.now(),
            message=str(error),
        )
