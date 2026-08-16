"""Position sizing for approved entry signals."""

from __future__ import annotations


class PositionSizer:
    """Sizes an entry either by capital allocation or by per-trade risk."""

    def calculate_quantity(
        self,
        capital: float,
        entry_price: float,
        capital_allocation_pct: float,
    ) -> int:
        """Return the number of shares affordable within the allocation.

        This is capital-allocation sizing: it ignores the stop-loss entirely,
        so two trades with identical entry price but very different stop
        distances get the same size and therefore very different dollar
        risk. Use ``calculate_quantity_by_risk`` whenever a stop-loss is
        available; this method exists as a fallback for signals that don't
        carry one.
        """

        if capital <= 0 or entry_price <= 0 or capital_allocation_pct <= 0:
            return 0

        return int((capital * capital_allocation_pct) / entry_price)

    def calculate_quantity_by_risk(
        self,
        capital: float,
        entry_price: float,
        stop_loss: float,
        risk_per_trade_pct: float,
        max_capital_allocation_pct: float | None = None,
    ) -> int:
        """Return the share count that risks exactly ``risk_per_trade_pct``.

        Quantity is ``(capital * risk_per_trade_pct) / |entry_price -
        stop_loss|`` -- the number of shares whose loss at the stop equals
        the configured risk budget. A tight stop therefore produces a larger
        position and a wide stop a smaller one, so every trade risks the
        same rupee amount regardless of how far away its stop happens to
        sit. ``max_capital_allocation_pct``, when given, caps the position
        so a very tight stop can't demand more capital than is sensible to
        deploy in one name.
        """

        if capital <= 0 or entry_price <= 0 or risk_per_trade_pct <= 0:
            return 0

        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share <= 0:
            return 0

        risk_budget = capital * risk_per_trade_pct
        quantity = int(risk_budget / risk_per_share)

        if max_capital_allocation_pct is not None:
            capital_capped_quantity = self.calculate_quantity(
                capital, entry_price, max_capital_allocation_pct
            )
            quantity = min(quantity, capital_capped_quantity)

        return max(quantity, 0)
