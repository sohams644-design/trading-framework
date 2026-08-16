"""Portfolio: financial bookkeeping shared by backtesting, paper, and live trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from domain.position import Position
from domain.signal import Signal
from domain.trade import TradeDirection
from domain.trade_record import TradeRecord
from execution.execution_result import ExecutionResult, OrderStatus
from execution.order_request import OrderRequest
from performance.charges_calculator import ChargesCalculator
from portfolio.trade_log import TradeLog
from risk.risk_context import RiskContext


@dataclass(slots=True)
class _OpenPosition:
    position: Position
    entry_time: datetime
    stop_loss: float | None = None


@dataclass(slots=True)
class Portfolio:
    """Owns cash, open positions, and realized PnL.

    Positions use a signed-quantity convention: a positive quantity is a long
    position, a negative quantity is a short position. This lets one formula
    (``pnl = (exit_price - entry_price) * signed_quantity``) compute correct
    PnL for both directions without a separate branch per side.
    """

    cash: float
    trade_log: TradeLog = field(default_factory=TradeLog)
    realized_pnl: float = 0.0
    daily_realized_loss: float = 0.0
    trades_today: int = 0
    charges_calculator: ChargesCalculator = field(default_factory=ChargesCalculator)
    _open_positions: dict[str, _OpenPosition] = field(default_factory=dict)

    @property
    def positions(self) -> dict[str, Position]:
        """Return currently open positions, keyed by symbol."""

        return {
            symbol: open_position.position
            for symbol, open_position in self._open_positions.items()
        }

    def snapshot(self, market_open: bool = True, trading_enabled: bool = True) -> RiskContext:
        """Build a RiskContext reflecting the portfolio's current state."""

        capital_deployed = sum(
            abs(open_position.position.quantity) * open_position.position.average_price
            for open_position in self._open_positions.values()
        )
        return RiskContext(
            capital=self.cash,
            capital_deployed=capital_deployed,
            daily_realized_loss=self.daily_realized_loss,
            trades_today=self.trades_today,
            open_positions=len(self._open_positions),
            active_symbols=set(self._open_positions.keys()),
            market_open=market_open,
            trading_enabled=trading_enabled,
        )

    def reset_daily_counters(self) -> None:
        """Clear per-day counters at a new session boundary."""

        self.daily_realized_loss = 0.0
        self.trades_today = 0

    def on_fill(
        self, order: OrderRequest, result: ExecutionResult, signal: Signal
    ) -> TradeRecord | None:
        """React to a fill by opening or closing a position.

        Returns the ``TradeRecord`` if this fill closed a position, or None
        if it opened one or was not actionable. Callers that need to know
        whether a trade completed should use the return value rather than
        inspecting the trade log's length.
        """

        if result.status is not OrderStatus.FILLED or result.fill_price is None:
            return None

        if signal.is_entry:
            self._open(order, result, signal)
            return None
        if signal.is_exit:
            return self._close(order, result, signal)
        return None

    def _open(self, order: OrderRequest, result: ExecutionResult, signal: Signal) -> None:
        signed_quantity = (
            order.quantity if order.side is TradeDirection.BUY else -order.quantity
        )
        self.cash -= result.fill_price * signed_quantity
        self._open_positions[order.symbol] = _OpenPosition(
            position=Position(
                symbol=order.symbol,
                quantity=signed_quantity,
                average_price=result.fill_price,
            ),
            entry_time=signal.timestamp,
            stop_loss=signal.stop_loss,
        )
        self.trades_today += 1

    def _close(
        self, order: OrderRequest, result: ExecutionResult, signal: Signal
    ) -> TradeRecord | None:
        open_position = self._open_positions.pop(order.symbol, None)
        if open_position is None:
            return None

        position = open_position.position
        quantity = abs(position.quantity)
        self.cash += result.fill_price * position.quantity
        gross_pnl = (result.fill_price - position.average_price) * position.quantity
        direction = TradeDirection.BUY if position.quantity > 0 else TradeDirection.SELL

        # A long round-trips buy-then-sell; a short round-trips sell-then-buy.
        # STT and stamp duty are leg-specific in India, so which price is the
        # buy leg and which is the sell leg depends on direction.
        if direction is TradeDirection.BUY:
            buy_price, sell_price = position.average_price, result.fill_price
        else:
            buy_price, sell_price = result.fill_price, position.average_price

        charges = self.charges_calculator.calculate_intraday(buy_price, sell_price, quantity)
        net_pnl = gross_pnl - charges.total
        self.cash -= charges.total

        trade = TradeRecord(
            symbol=order.symbol,
            direction=direction,
            entry_price=position.average_price,
            exit_price=result.fill_price,
            quantity=quantity,
            pnl=net_pnl,
            entry_time=open_position.entry_time,
            exit_time=signal.timestamp,
            reason=signal.reason,
            charges=charges.total,
            stop_loss=open_position.stop_loss,
            mae=signal.metadata.get("mae"),
            mfe=signal.metadata.get("mfe"),
        )
        self.trade_log.record(trade)
        self.realized_pnl += net_pnl
        if net_pnl < 0:
            self.daily_realized_loss += -net_pnl
        return trade
