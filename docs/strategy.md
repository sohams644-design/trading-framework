
# Strategy

## Opening Range Breakout (`strategies/orb.py`)

The strategy marks the high and low of the first `opening_range_minutes` of
the session, then enters on the first candle that trades outside that range,
provided two filters agree:

- **VWAP**: a long needs `close > vwap`, a short needs `close < vwap`.
- **Relative volume**: the candle's volume must be at least
  `relative_volume_threshold` times the rolling average.

There is no stop-loss and no profit target. Every position is held to the
square-off time, so `end_of_day_exit` is the only exit reason that occurs in
practice — `exit_on_opposite_breakout` is off by default.

## Known defects

A 58-session backtest across five NSE large caps (5-minute candles) surfaced
three defects. All three are in the strategy, not the runtime.

### 1. Entries are allowed after the square-off time

`_build_exit_signal` returns `None` when the strategy is flat, so the
square-off check never runs on a flat strategy. `_build_entry_signal` has no
square-off guard of its own. The result is that after the 15:15 square-off
closes a position, the strategy will happily open a new one at 15:20 or 15:25.

Roughly a third of all trades in the sample were opened at or after 15:15.

### 2. Position state desynchronises from the portfolio at a session boundary

`_reset_if_new_session` clears `position_state` to `FLAT` on the first candle
of a new day. The `Portfolio` is not reset — and must not be, since it owns
real bookkeeping. If a position is still open at the end of a session (which
defect 1 makes possible, by entering on the final candle of the day), the next
morning the strategy believes it is flat while the portfolio still holds
stock.

### 3. Rejected signals still advance the strategy's position state

`_build_entry_signal` assigns `self.position_state` *before* returning the
signal, so the state changes whether or not the trade is ever executed. When
the risk gate rejects the entry — `POSITION_ALREADY_OPEN`, a breached daily
loss limit, insufficient capital — the strategy is left believing it holds a
position it never opened.

This is the most structural of the three: the strategy assumes its signals are
always filled. Combined with defects 1 and 2 it produces overnight holds, where
a stale position from a previous session is finally closed by an exit signal
belonging to a *different*, never-executed entry.

## Measured edge

Across 336 trades on RELIANCE, TCS, INFY, HDFCBANK, and SBIN (2026-05-18 to
2026-08-07), mean return per trade was **-1.3 bps**, 95% CI `[-7.5, +4.8]` —
statistically indistinguishable from zero. Excluding the defect-1 trades it
was **+2.4 bps**, 95% CI `[-5.8, +10.6]`, also indistinguishable from zero.

NSE intraday equity round-trip costs are roughly 6-12 bps, none of which the
backtest models. The strategy has no demonstrated edge over its cost floor,
and fixing the three defects above is a correctness exercise, not something
that would be expected to create one.

