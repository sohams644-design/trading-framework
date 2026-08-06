"""Execution-provider abstraction used by the order manager."""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain.candle import Candle
from execution.execution_result import ExecutionResult
from execution.order_request import OrderRequest


class ExecutionProvider(ABC):
    """Interface for broker-backed order execution adapters."""

    def advance(self, candle: Candle) -> None:
        """Advance the provider's notion of the current market price.

        Default no-op: real broker adapters don't need to be told the
        current price. Only simulated/replay-driven providers (see
        ``SimulatedExecutionProvider``) override this.
        """

        return None

    @abstractmethod
    def place_order(self, order: OrderRequest) -> ExecutionResult:
        """Submit an order and return the resulting execution state."""
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> ExecutionResult:
        """Cancel a previously submitted order."""
        raise NotImplementedError

    @abstractmethod
    def modify_order(self, broker_order_id: str, order: OrderRequest) -> ExecutionResult:
        """Modify a previously submitted order."""
        raise NotImplementedError

    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> ExecutionResult:
        """Return the current execution state of a previously submitted order."""
        raise NotImplementedError
