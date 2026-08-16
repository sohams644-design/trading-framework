"""Fills MARKET orders against a replayed or live price feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import count

from domain.candle import Candle
from domain.trade import TradeDirection
from execution.exceptions import ExecutionProviderError, OrderNotFoundError
from execution.execution_result import ExecutionResult, OrderStatus
from execution.order_request import OrderRequest, OrderType
from execution.provider import ExecutionProvider


@dataclass(slots=True)
class _SimulatedOrder:
    request: OrderRequest
    status: OrderStatus
    fill_price: float | None


class SimulatedExecutionProvider(ExecutionProvider):
    """Simulates execution by filling MARKET orders at the current price.

    Unlike ``PaperExecutionProvider`` (which never fills orders and exists to
    test order-lifecycle plumbing), this provider exists to simulate real
    fills against historical or live prices, for backtesting and, later,
    paper trading against a live feed. It is not a broker adapter: it
    represents simulated execution, not a specific broker. A real limit/stop
    order lifecycle, latency, and partial fills are still out of scope for
    this version.

    Every ``MARKET`` order fills at a reference price plus slippage.
    ``order.price``, when the caller supplies one, is used as that
    reference instead of the last-seen candle close -- this is how a
    strategy's own detected stop-loss/target trigger level (rather than
    whatever the candle happened to close at) becomes the fill basis, which
    is what makes intrabar stop and target exits realistic in a bar-based
    backtest. ``slippage_bps`` is applied adversely to every fill: worse for
    buys, worse for sells, modeling spread and market impact.
    """

    def __init__(self, slippage_bps: float = 5.0) -> None:
        self.slippage_bps = slippage_bps
        self._current_price: float | None = None
        self._current_timestamp: datetime | None = None
        self._orders: dict[str, _SimulatedOrder] = {}
        self._id_sequence = count(1)

    def advance(self, candle: Candle) -> None:
        """Advance the simulated market to a new candle's close price.

        Overrides the ``ExecutionProvider`` no-op default: this provider
        fills against whatever price it was last advanced to.
        """

        self._current_price = candle.close
        self._current_timestamp = candle.timestamp

    def place_order(self, order: OrderRequest) -> ExecutionResult:
        """Fill a MARKET order immediately at the current simulated price."""

        if order.order_type is not OrderType.MARKET:
            raise ExecutionProviderError(
                "SimulatedExecutionProvider only fills MARKET orders."
            )
        if self._current_price is None or self._current_timestamp is None:
            raise ExecutionProviderError(
                "advance() must be called with a candle before placing orders."
            )

        reference_price = order.price if order.price is not None else self._current_price
        fill_price = self._apply_slippage(reference_price, order.side)

        broker_order_id = self._next_order_id()
        self._orders[broker_order_id] = _SimulatedOrder(
            request=order, status=OrderStatus.FILLED, fill_price=fill_price
        )
        return ExecutionResult(
            success=True,
            status=OrderStatus.FILLED,
            timestamp=self._current_timestamp,
            broker_order_id=broker_order_id,
            fill_price=fill_price,
        )

    def _apply_slippage(self, price: float, side: TradeDirection) -> float:
        slippage = price * (self.slippage_bps / 10_000)
        return price + slippage if side is TradeDirection.BUY else price - slippage

    def cancel_order(self, broker_order_id: str) -> ExecutionResult:
        """Mark a stored order as cancelled.

        Since fills are immediate, this only applies defensively; nothing in
        this version leaves an order pending long enough to cancel.
        """

        simulated_order = self._get_order(broker_order_id)
        simulated_order.status = OrderStatus.CANCELLED
        return ExecutionResult(
            success=True,
            status=OrderStatus.CANCELLED,
            timestamp=self._current_timestamp or datetime.now(),
            broker_order_id=broker_order_id,
        )

    def modify_order(self, broker_order_id: str, order: OrderRequest) -> ExecutionResult:
        """Reject modification of an already-filled simulated order."""

        raise ExecutionProviderError(
            "SimulatedExecutionProvider does not support modifying filled orders."
        )

    def get_order_status(self, broker_order_id: str) -> ExecutionResult:
        """Return the last known status of a simulated order."""

        simulated_order = self._get_order(broker_order_id)
        return ExecutionResult(
            success=True,
            status=simulated_order.status,
            timestamp=self._current_timestamp or datetime.now(),
            broker_order_id=broker_order_id,
            fill_price=simulated_order.fill_price,
        )

    def _next_order_id(self) -> str:
        return f"SIM-{next(self._id_sequence):06d}"

    def _get_order(self, broker_order_id: str) -> _SimulatedOrder:
        try:
            return self._orders[broker_order_id]
        except KeyError as error:
            raise OrderNotFoundError(
                f"Unknown simulated order id: {broker_order_id}"
            ) from error
