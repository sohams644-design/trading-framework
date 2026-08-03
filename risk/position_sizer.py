"""Position sizing for approved entry signals."""

from __future__ import annotations


class PositionSizer:
    """Sizes an entry as a fraction of total capital.

    This is capital-allocation sizing, not stop-loss-aware risk sizing: a
    stop-loss-based sizer belongs to a future sprint once strategies carry
    stop-loss data through to the risk gate.
    """

    def calculate_quantity(
        self,
        capital: float,
        entry_price: float,
        capital_allocation_pct: float,
    ) -> int:
        """Return the number of shares affordable within the allocation."""

        if capital <= 0 or entry_price <= 0 or capital_allocation_pct <= 0:
            return 0

        return int((capital * capital_allocation_pct) / entry_price)
