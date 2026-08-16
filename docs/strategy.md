<<<<<<< Updated upstream
# Strategy: ORB Redesign

This document is a structural review of `ORBStrategy` (Opening Range Breakout) as it stood after the 15:15 re-entry fix and the stop-loss/profit-target/logging additions, plus the redesign implemented on top of it. It answers the ten review questions, lists every flaw found, describes the new design, and explains every code change. All 263 tests in `tests/` pass under Python 3.11.

**What this document is not:** a backtest report. Every claim below is grounded in reading the actual code (file:line references throughout) and in the backtest statistics you reported (17 trades, July 2026, RELIANCE). No new backtest was run against real market data as part of this review — there's no historical OHLC data in this repo and no working Zerodha session in the environment that did this work. Section 11 says explicitly what would need to happen before any of this is validated against real returns.

## 1–10: Quantitative review

### 1. Is the ORB logic itself correct?

Mechanically, yes, for a plain breakout-of-range check: `OpeningRange` correctly tracks the 15-minute high/low and recomputes `breakout_above`/`breakout_below` fresh on every post-range candle (`indicators/opening_range.py:61-65`) — this is a plain assignment, not a sticky OR, so it reflects only the *most recent* candle's high/low against the range, not "has ever broken out."

But "correct" mechanics were sitting on three structural gaps that produced the symptoms in your report:

- No entry-time cutoff (fixed in the 15:15 session, but originally the strategy would enter at any time up to square-off).
- No confirmation beyond a single tick above/below the level — a one-candle wick breaking the range and immediately reverting counted as a valid signal.
- Stop distance was fixed to the opening-range width, which has no relationship to the instrument's actual volatility that day. A calm day's range produces an unrealistically tight stop; a volatile day's range produces an oversized one.

### 2. Is using the candle close for both signal generation and execution introducing look-ahead bias or delayed entries?

Two different things were going on, and they cut in opposite directions:

- **No look-ahead in the strict sense.** The strategy only ever reads `candle.high/low/close` of the candle it's currently processing, and `IndicatorContext.update(candle)` runs before `strategy.generate_signal(candle, ...)` (`runtime/engine.py:92-98`) — so by the time a decision is made, that candle has fully closed and its indicators reflect it. Nothing from a future candle leaks in.
- **A real fill-price optimism, though.** The old code generated a signal using candle N's close and then filled at that *same* close (`strategies/orb.py`, `SimulatedExecutionProvider.place_order` using `self._current_price` unconditionally). In live trading you cannot act on a candle's close until the candle has actually closed and your order reaches the exchange — by which point price has moved. Backtesting as if your order fills instantly at the exact print that generated the signal is optimistic. This was compounded for exits: stop-loss and profit-target were *detected* using `candle.low/high` (correctly, intrabar) but *filled* at `candle.close` regardless — so a stop at ₹1300 hit inside a candle that closed at ₹1295 would report an exit at ₹1295, not ₹1300. This is exactly the distortion flagged before implementing stops, and it's fixed in this redesign (§13).

### 3. Is the stop-loss placement using the opening range high/low mathematically sound?

No single fixed relationship between a 15-minute range's width and appropriate risk exists — the range is just "however far price moved in 15 minutes today," which has no volatility normalization. Two consequences, both visible in your numbers:

- On a day with a wide opening range, the stop is unnecessarily far, so a losing trade costs more than it should.
- On a day with a narrow opening range, the stop is unrealistically close and gets clipped by ordinary noise (this is consistent with the low win rate — 41.2% — despite a nominal 2:1 reward:risk, which should produce a higher win rate if losers were being sized sensibly relative to normal price noise).

The redesign replaces this with a stop that's the *tighter* of the opening-range edge and an ATR-based distance (§12), so the range can inform the stop without being the sole determinant of risk.

### 4. Is the profit target calculation correct?

The R:R arithmetic itself (`target = entry + risk * risk_reward_ratio`) was correct. The problem was upstream: because risk was defined by the (often too-wide) opening range, the target computed from that risk was proportionally far away too — for a stock like RELIANCE, a 2R target off a wide range can be tens of rupees away, which an intraday move often can't reach before square-off. Your report of **0 target exits across 17 trades** is the direct symptom: not a bug in the R:R math, but a target that was structurally too far from a stop that was structurally too wide.

### 5. Should an ORB strategy allow entries throughout the entire trading session?

No. An ORB's premise is that the *early* breakout of the initial range captures a specific move; a "breakout" flagged at 2:05 PM or 3:05 PM (your reported entry times) is not that move — it's the strategy discovering, hours later, that price is now somewhere else, and mislabeling that discovery as a fresh signal. Two structural reasons this was happening, not just "no clock check":

- The obvious one: no entry-time cutoff existed at all (only a square-off *exit* cutoff).
- The less obvious one, and arguably the bigger contributor: `RelativeVolume`'s default lookback is 20 bars (`indicators/relative_volume.py:14`), which on 5-minute candles is 100 minutes. RVOL literally cannot be *ready* until ~11:00 AM regardless of the threshold — so even with an entry-window fix, the original RVOL configuration alone would push every entry into the late morning at the earliest. This is fixed by tightening RVOL's lookback for this use case (§16), not just by adding a window.

### 6. Is the market-close exit destroying the strategy's expectancy?

It's a *symptom*, not the disease. **End-of-day exits: 15 of 17 (88%)** means almost every trade was closed by a fixed-time rule rather than by the strategy's own thesis (stop or target) resolving. Given §5's finding, most entries were happening so late that there was little session time left for a 2R target — computed from an oversized stop — to have any real chance of being reached before 15:15. Fixing entry timing and stop sizing (§5, §3) should mechanically reduce reliance on the clock to close trades; it isn't something to "fix" by changing the clock rule itself.

### 7. Is using 5-minute candles appropriate?

Reasonable for RELIANCE specifically (liquid, tight spreads), but it interacts badly with the other gaps above: a 15-minute opening range is only 3 candles, and a naive breakout-of-3-candles check on 5-minute bars is noisy — a single wick above/below the range is common and not evidence of a real move. This is why breakout confirmation (§12) matters more at this granularity than it would on, say, 15-minute bars.

### 8. Is the VWAP filter implemented correctly?

Yes, mechanically: `VWAP` is a correct incremental cumulative volume-weighted average (`indicators/vwap.py`), reset daily (intraday VWAP, not multi-day), and the strategy correctly required `close` on the entry candle to be on the favorable side of it. No bug found here.

### 9. Is the Relative Volume filter sufficiently selective?

The filter logic itself (ratio ≥ threshold) is fine, but as covered in §5, the *lookback* was the real problem: 20 bars / 100 minutes on 5-minute data means RVOL isn't just "insufficiently selective" — it structurally cannot participate in an ORB entry window at all with any reasonable window size, which is a design mismatch, not a threshold-tuning problem.

### 10. Is the strategy suffering from survivorship bias, execution bias, or unrealistic fill assumptions?

- **Survivorship bias:** not assessable from a single-symbol RELIANCE backtest — this only shows up when backtesting a *universe* of stocks selected using today's index membership or today's liquidity, which silently excludes names that were delisted, merged, or became illiquid during the test period. This becomes relevant the moment this strategy is extended beyond one hand-picked liquid large-cap (see §11 and the roadmap's "test 50-100 stocks" item — that step is exactly where survivorship bias becomes a live risk, if the stock list is drawn from today's index rather than each date's actual membership).
- **Execution bias / unrealistic fills — yes, three confirmed issues, all fixed in this redesign:**
  1. Zero slippage — `SimulatedExecutionProvider` filled every order at the exact reference price with no spread/impact modeling (docstring literally said "slippage... out of scope for this version").
  2. Stop/target fills at candle close instead of the actual trigger price (§2).
  3. **Brokerage/STT/exchange/SEBI/GST/stamp duty were computed by `ChargesCalculator` but never actually subtracted from PnL** — `Portfolio._close()` computed `pnl = (fill_price - entry_price) * quantity` with no charges applied anywhere (`portfolio/portfolio.py`, old version). The calculator existed and was correct; it just wasn't wired to anything. Every trade in your 17-trade backtest was reported gross, not net, of transaction costs — with a net PnL of ₹19.60 on 17 trades, this is not a rounding-error-sized gap.

## 11. Every flaw found (ranked by impact on your reported results)

1. **Transaction costs never applied to PnL** — `ChargesCalculator` built but not called from `Portfolio._close()`. At ₹19.60 net PnL over 17 trades, real per-round-trip charges (a few tens of paise to a few rupees each, scaling with turnover) could plausibly flip this backtest from marginally profitable to a loser once actually deducted.
2. **RVOL lookback (20 bars / 100 min) structurally incompatible with an ORB entry window** — the dominant cause of your 12:05 PM–3:05 PM entry times, not just "no time cutoff."
3. **No entry-time cutoff at all** — compounds #2; even after RVOL clears, nothing stopped a "breakout" being flagged at any point in the session.
4. **Stop-loss sized from the opening range alone, no volatility normalization** — inconsistent per-trade risk, and the direct cause of the 0/17 target-exit rate (§4).
5. **No breakout confirmation** — a single-candle wick above/below the range counted as a signal on noisy 5-minute bars.
6. **Zero slippage modeling.**
7. **Stop/target detected intrabar but filled at candle close** — a real, quantifiable distortion on every stop/target exit (was already flagged before implementing stops; now fixed).
8. **Position sizing ignored the stop-loss entirely** — `PositionSizer.calculate_quantity` sized as a fixed % of capital regardless of stop distance, so two trades with identical entry price but very different risk-per-share got the same share count and therefore very different dollar risk.
9. **`Signal.buy()`/`Signal.sell()` declared `stop_loss`/`target` fields but never set them** — the strategy computed its own stop/target internally but never told the risk layer or the trade record about them, which is also why #8 was possible (risk sizing had no stop to size against) and why no MAE/MFE/R-multiple could ever be computed.
10. **No brokerage/STT/GST/stamp-duty in the executed PnL path** (same root cause as #1, listed separately because it's the literal answer to your charges question).
11. **`use_stop_loss`/`use_profit_target` config flags existed but were dead code** — declared on `ORBStrategyConfig`, never read anywhere, so they silently did nothing regardless of how they were set.
12. **No trailing stop / no way for a winner to run past a fixed target** — once price moved favorably, there was no mechanism to lock in gains beyond the initial fixed target, capping upside on trades that had real follow-through.
13. **No performance metrics beyond win rate / avg winner / avg loser / profit factor / max drawdown** — no Sharpe, Sortino, Calmar, expectancy, R-multiple, MAE/MFE, consecutive win/loss streaks, exposure %, or trade duration, so you had no way to see *why* the target never triggered or *how* concentrated the risk was without instrumenting it yourself (which is what led to this review).
14. **`tests/test_charges.py` and `tests/test_charges_calculator.py` were identical, non-test scratch scripts** — `print()` statements with no `assert`, so `ChargesCalculator` had zero real regression coverage despite computing money that (per #1) wasn't even reaching PnL. Minor, but worth knowing: pytest silently executes these as import side effects during collection; they don't fail, they just don't test anything.

## 12–20. The redesign

### 12. Entry model: window + ATR-confirmed breakout + one trade/day

`ORBStrategyConfig` (`config/orb.py`) gains:

```python
entry_window_minutes: int = 45          # only trade in the first 45 min after the range
atr_period: int = 7                     # intraday ATR (resets daily, like every other indicator here)
breakout_confirmation_atr_multiplier: float = 0.15
stop_atr_multiplier: float = 1.5
trailing_activation_r: float = 1.0
trailing_atr_multiplier: float = 1.0
```

`MarketSession.is_within_entry_window()` (`indicators/session.py`) gates entries to the window after the range completes — the strategy already had the equivalent square-off gate for exits; this is the same idea applied to entries, addressing §5's clock-based half of the problem.

`_long_entry`/`_short_entry` (`strategies/orb.py`) now require the close to clear the opening-range level by `breakout_confirmation_atr_multiplier * ATR`, not just by any amount — filtering out the single-wick noise identified in §7/#5.

### 13. Stop placement: tighter of ATR and range, filled at the real trigger price

`_set_trade_levels` computes both an ATR-based stop (`entry ∓ stop_atr_multiplier * ATR`) and the original range-based stop, and takes whichever is *closer to entry* — so a wide opening range can no longer force an oversized loss, and a narrow one can no longer force an unrealistically tight stop below normal noise (§3, #4).

`_stop_loss_exit`/`_profit_target_exit` now pass the actual stop/target price as the exit signal's price, and `_exit_current_position` uses it instead of `candle.close` (§2, #7). `OrderRequestBuilder.build()` now passes `signal.price` into `OrderRequest.price`, and `SimulatedExecutionProvider.place_order()` uses `order.price` as the fill reference when supplied, falling back to the last-seen candle close otherwise (`execution/order_request_builder.py`, `execution/simulated_execution_provider.py`).

### 14. Trailing stop

`_track_excursions_and_trail_stop` runs every candle a position is open. Once favorable movement reaches `trailing_activation_r * initial_risk`, the stop trails `trailing_atr_multiplier * ATR` behind the trade's running high/low-water mark, ratcheting only in the trade's favor — it can tighten but never loosen (#12). The fixed profit target stays in place alongside it; a trade exits at whichever is hit first.

### 15. Risk-based position sizing

`PositionSizer.calculate_quantity_by_risk()` (`risk/position_sizer.py`) sizes a position from `(capital * risk_per_trade_pct) / |entry - stop|` — every trade risks the same rupee amount regardless of stop distance, capped by a capital-allocation ceiling (`max_capital_allocation_pct`) so a very tight stop can't demand an oversized position. `RiskManager.evaluate()` (`risk/risk_manager.py`) uses this whenever a signal carries a `stop_loss`, falling back to the old fixed-capital-% sizing otherwise. This required `Signal.buy()`/`Signal.sell()` (`domain/signal.py`) to actually accept and set `stop_loss`/`target` — previously declared, never wired (#9).

### 16. RVOL lookback tightened for ORB use

`IndicatorContext.with_defaults()` now constructs `RelativeVolume(lookback_period=6)` (30 minutes) and `ATR(period=7)` instead of the old `RelativeVolume()` default of 20 bars / 100 minutes (§5, §9, #2). This is a real behavior change to the shared default context, not a parameter tweak buried in the strategy — flagged here explicitly since it affects any other consumer of `IndicatorContext.with_defaults()`.

### 17. Slippage

`SimulatedExecutionProvider(slippage_bps=5.0)` now applies configurable slippage adverse to fill direction (buys fill slightly worse, sells fill slightly worse) on every fill (#6). 5bps is a starting assumption for a liquid large-cap like RELIANCE, not a calibrated number — worth revisiting against real spread data before trusting absolute PnL figures.

### 18. Transaction costs wired into realized PnL

`Portfolio._close()` now calls `ChargesCalculator.calculate_intraday()` on every closed trade, correctly mapping which leg is the buy and which is the sell based on trade direction (a long round-trips buy-then-sell; a short round-trips sell-then-buy, and STT/stamp-duty are leg-specific), subtracts the total from realized PnL, and deducts it from cash (#1, #10). `TradeRecord` gains a `charges` field so gross vs. net is inspectable per trade, not just in aggregate.

One thing this does **not** fix, because it isn't a bug: `ChargesCalculator.calculate_intraday()` hardcodes `brokerage = 0.0`. If your actual Zerodha plan isn't a zero-brokerage-on-intraday-equity plan, that number needs updating to match your real cost structure — I didn't touch the charges formulas themselves, only wired the existing (already-written) calculator into the PnL path.

### 19. `use_stop_loss` / `use_profit_target` actually do something now

`_build_exit_signal` gates the stop and target checks behind these flags (#11) — previously declared and ignored, now load-bearing.

### 20. New performance metrics

`performance/sharpe.py` (Sharpe, Sortino, Calmar — all computed from **daily-aggregated** PnL, not per-trade, since per-trade volatility over/under-counts relative to actual trading-day variance), `expectancy()` added to `performance/expectancy.py`, and `performance/performance.py` (average R-multiple, consecutive win/loss streaks, average trade duration, exposure %). `TradeRecord` gains `stop_loss`, `mae`, `mfe` fields — MAE/MFE are tracked candle-by-candle in the strategy (which already sees every candle while a position is open) and threaded through via `Signal.metadata`, which already existed for exactly this kind of extensibility. `BacktestResults`/`Results.calculate()` (`backtesting/results.py`) surface all of it.

**A caveat that matters more than the formulas:** Sharpe/Sortino/Calmar are annualized from daily observations, and a one-month backtest has on the order of 20 trading days. That's a genuinely small sample for a ratio that multiplies by `sqrt(252)`. Don't read a single month's Sharpe as a stable estimate of anything — it will be noisy by construction, not because the calculation is wrong.

## 21. Every reason this strategy would still fail in live trading

Even with the redesign above, none of this has been validated against real fills, and several gaps are structural, not implementation bugs:

1. **No real backtest has been run.** Everything above is a code-level fix; none of it has been measured against actual July 2026 RELIANCE data (or any real data) in this session — there's no historical OHLC in the repo and no live Zerodha session available here. Until that happens, "the redesign is better" is a structural argument, not a measured one. This is explicitly why item #12 on your roadmap ("suggest only changes supported by backtesting evidence") isn't fully satisfiable yet — see the note at the top of this document.
2. **Single-symbol, single-month sample.** 17 trades (or however many the redesign produces) on one stock in one month cannot distinguish a real edge from noise. The roadmap's "test 50-100 stocks" step is not optional polish — it's the minimum needed before any of these numbers mean something.
3. **Slippage (5bps) and brokerage (₹0) are assumptions, not calibrated values.** Real intraday slippage on RELIANCE around news/volatile opens can exceed 5bps; if your actual Zerodha plan charges brokerage, the charges calculator needs that value filled in.
4. **No margin/leverage modeling, no circuit-limit handling, no partial fills.** `SimulatedExecutionProvider` fills the full requested quantity unconditionally; real intraday orders can be partially filled, rejected for margin, or blocked by a circuit filter, none of which is modeled.
5. **No latency modeling.** A live order takes real network/broker time to reach the exchange after a signal fires; the backtest still assumes the fill happens at the decision candle.
6. **Intraday-only ATR is a deliberate simplification, not the textbook ATR.** It resets every session (consistent with VWAP/RVOL/OpeningRange here), so on day 1 of any session it has to reseed from scratch — the classic multi-day ATR would give a more stable volatility estimate at the open, at the cost of needing to persist state across sessions, which this framework's architecture doesn't currently do for any indicator.
7. **Corporate actions aren't handled anywhere in this pipeline** — a split, bonus, or dividend on the backtest date would silently corrupt the opening range, VWAP, and every price-based comparison for that session.
8. **No regime awareness.** An ORB strategy's edge is regime-dependent (works better in trending/volatile conditions, worse in chop); nothing here detects or adapts to that, so a redesign that improves the mechanics doesn't address whether ORB is the right strategy for a given day at all.
9. **Extending beyond RELIANCE reintroduces survivorship bias risk** (§10) unless the stock universe for any given backtest date is reconstructed as it actually was on that date, not filtered by today's index membership or today's liquidity.

## What I'd suggest doing next, and why I'm not suggesting more than this

Per your explicit instruction, I'm not proposing parameter re-tuning (the ATR multipliers, R:R ratio, entry window minutes, etc. above are reasonable starting points, not backtested-optimal values) and I'm not claiming the redesign has been shown to improve returns — only that it removes the four concrete, code-verified sources of bias/inconsistency in §11. The next real step is #21.1: get real historical data into this repo (either your Zerodha credentials + a working historical-data fetch, or a CSV you already have) and Python 3.10+ set up in whatever environment will run it, then re-run the July 2026 RELIANCE backtest with the new code and compare the actual numbers — trade count, win rate, profit factor, and the new metrics (especially average R-multiple and MAE, which will show directly whether the tighter stop is cutting winners short or the trailing stop is doing its job) — against your original 17-trade report. Only that comparison, not this document, can tell you whether the redesign actually helped.
=======
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
>>>>>>> Stashed changes
