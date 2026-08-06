# Architecture

The project follows a package-oriented trading framework layout:

- `config/` contains runtime configuration and environment-backed settings.
- `domain/` contains business objects shared across the framework, including candles, signals, trades, positions, and instruments.
- `models/` contains compatibility exports for domain objects while callers migrate to `domain/` imports.
- `strategies/` contains strategy interfaces and concrete strategy implementations.
- `indicators/` contains broker-independent, incremental indicator calculations and indicator context orchestration.
- `market_data/` contains provider abstractions, interval definitions, instrument lookup, validation, repositories, historical loading, and the live feed (`LiveMarketFeed`, `TickAggregator`).
- `broker/` contains broker-specific adapters that isolate third-party SDKs from framework code.
- `risk/` contains the risk gate: `RiskContext`, `SafetyChecks`, `TradeLimits`, `PositionSizer`, and the `RiskManager` orchestrator that turns a `Signal` into a `RiskDecision`.
- `execution/` contains the broker-independent execution pipeline: order contracts (`OrderRequest`, `ExecutionResult`, `OrderStatus`), the `ExecutionProvider` interface, `OrderValidator`, `OrderManager`, `OrderRequestBuilder`, and the in-memory `PaperExecutionProvider`/`SimulatedExecutionProvider`.
- `portfolio/` contains financial bookkeeping shared by backtesting, paper trading, and live trading: `Portfolio` (cash, positions, realized PnL) and `TradeLog`.
- `performance/` contains pure statistics over completed trades: win rate, average winner/loser, profit factor, and max drawdown.
- `runtime/` contains the orchestration layer: `RuntimeEngine`, `RuntimeConfig`, lightweight `RuntimeEvent`s, and the `PaperTradingRunner` composition. It coordinates existing components and holds no trading logic of its own.
- `backtesting/` replays historical candles through the runtime loop via `Replay`, `BacktestEngine`, and `Results`.
- `state/` contains engine lifecycle state (`RuntimeState`, `RuntimeStatus`) — distinct from `portfolio/`, which owns financial/accounting state, not lifecycle state.
- `utils/` contains compatibility helpers for logging, instruments, and market data.
- `watchdog/` contains health monitoring and emergency controls.

## Version 1 architecture freeze

As of Sprint 8 the Version 1 architecture is frozen. The package list above is final: no new top-level packages, no moving files, no renaming layers, and no new architectural concepts unless they solve a genuinely new problem.

Future work should consist of adding implementations, integrations, providers, and improved algorithms inside the existing layers — not reorganizing the project. Every new feature should first answer: *does this belong inside an existing layer, or am I accidentally creating a new architecture?*

## Domain layer

`Candle`, `Signal`, `Trade`, `Position`, and `Instrument` are domain objects. They live in `domain/` because they represent trading business concepts rather than market-data transport concerns.

The legacy `models/` package remains as a compatibility shim for existing imports, but new framework code should import business objects from `domain/` directly.

## Market data and indicator flow

Strategies should depend on framework services and indicators rather than broker SDKs or inline calculations:

```text
MarketDataProvider
    ↓
HistoricalDataLoader
    ↓
IndicatorContext
    ↓
Indicators
    ↓
Strategy
    ↓
Signal
    ↓
Risk
    ↓
Order Manager
    ↓
Execution Provider
    ↓
Broker Adapter
```

A future service layer can be inserted without changing strategies:

```text
Strategy
    ↓
MarketDataService
    ↓
HistoricalDataLoader
    ↓
MarketDataProvider
    ↓
Broker Adapter
```

The `MarketDataProvider` interface defines historical candles, live quotes, and tick streaming. All provider methods expose framework `list[Candle]` values, so strategy code never depends on broker payloads, pandas data frames, REST responses, CSV files, or database rows. The Zerodha adapter implements this interface and is the only market-data component that imports `KiteConnect` and `KiteTicker`.

Historical data loading is separated from strategy logic. A strategy requests candles through `HistoricalDataLoader.load(symbol, from_date, to_date, interval)`, where `interval` is a typed `Interval` enum value. The loader validates candles before returning them so malformed broker data fails early.

## Live market feed

`LiveMarketFeed` (`market_data/live_feed.py`) is the live counterpart to `Replay`. Both are simply `Iterable[Candle]`, so `RuntimeEngine` cannot tell them apart — that interchangeability is the entire point of the layer.

```text
KiteTicker  ──[SDK thread]──▶  ZerodhaMarketDataProvider.stream_ticks()
                                            │
                              [drain thread]│  private to LiveMarketFeed
                                            ▼
                                     private queue
                                            │
                              [runtime thread] timed get
                                            ▼
                                     TickAggregator
                                            ▼
                                   completed Candle ──▶ RuntimeEngine
```

### The provider contract means exactly one thing

`MarketDataProvider.stream_ticks(symbols) -> Iterator[list[Candle]]` yields ticks. It has no heartbeat value, no sentinel, no empty-batch convention, and no timeout parameter. Every broker adapter, present and future, implements that one meaning and hides its own threading model behind it.

Ticks are represented as degenerate candles (`open == high == low == close == last price`), following the convention `get_live_quote` already established. **A tick candle's `volume` is the broker's cumulative day volume, not bar volume.** That overload is a known wart of reusing `Candle` for ticks; introducing a proper `Tick` domain object is a documented Version 2 candidate, deferred here because it would change a frozen interface.

### Why LiveMarketFeed owns a thread

A broker tick stream is push-based and blocking; the runtime is pull-based and must wake periodically to close an elapsed candle. Once a consumer enters `for ticks in provider.stream_ticks(...)` it cannot run any code until the provider yields — that is a property of Python generators, not a design choice. So `LiveMarketFeed` runs the provider on a private daemon thread that drains ticks onto a private queue, and the runtime thread performs a timed `get` on that queue.

The queue, the thread, the sentinel that terminates it, and all synchronization are private to `LiveMarketFeed`. Nothing outside the class can observe them, and `RuntimeEngine`, Strategy, Risk, and Portfolio all remain single-threaded. Both threads stay inside `market_data/`.

Without this, the final candle of a session would never be emitted, and a quiet symbol's candle would stall until its next tick arrived.

### Tick aggregation

`TickAggregator` (`market_data/tick_aggregator.py`) turns ticks into bars and is entirely broker-independent, holding no connection state.

Bucket starts are floored to the interval **anchored on `session.market_open`**, not the clock hour, so 15-minute buckets are 09:15/09:30/09:45 and align with how `OpeningRange` already reasons about the session. Emitted candles are timestamped with the bucket start, making live candles interchangeable with historical ones.

Within a bucket: **open** is the first tick's price, **high**/**low** are running extremes, **close** is the latest price, and **volume** is `latest_cumulative - baseline_cumulative`. The baseline is the *previous* bucket's final cumulative figure, so no traded volume is lost between bars; the first bucket after connecting measures from its own first tick instead, which undercounts that bar by a single tick rather than treating a mid-session connect as if the whole day traded in one bar. A cumulative figure that moves backwards means the broker reset it, and the baseline resets with it.

**This volume delta is a correctness requirement, not an optimisation.** Passing cumulative volume through unconverted would make `RelativeVolume` compare day-cumulative figures against a rolling average of day-cumulative figures, silently rendering every ORB entry filter meaningless with no error raised.

`has_open_bucket` makes flush-at-close an explicit check rather than a `None` test at each call site. Ticks belonging to an already-emitted bucket are dropped with a warning rather than retroactively mutating history.

### Session, reconnect, and failure

Ticks outside `session.is_market_open(...)` are dropped, so pre-open and post-close noise never reaches indicators. **Day-boundary resets are not handled here** — `RuntimeEngine` already owns them via `MarketSession.should_reset`, and duplicating that would reintroduce exactly the drift Sprint 8 removed. There is no holiday calendar; on a holiday the feed simply receives no ticks and idles.

Termination means the session has **ended**, not merely that the clock is outside session hours: a feed started before the opening bell idles and waits rather than exiting, since a paper or live session is realistically launched before the market opens.

On disconnect the feed reconnects with exponential backoff and **retains the open bucket**, so a brief outage mid-candle resumes the same bar instead of discarding partial data. Only once `max_reconnect_attempts` is exhausted does it flush the open candle and raise — which lands in `RuntimeEngine._handle_feed_failure`, recording an abnormal end. Reaching market close instead ends iteration cleanly, so `error_count` stays meaningful. Malformed ticks are dropped with a warning; one bad tick never kills a session.

Logging covers connection established, **first candle received** (a connection is not necessarily delivering market data yet), reconnect attempts, reconnect exhaustion, candles emitted (DEBUG), and market close.

### Import-cycle note

`LiveFeedConfig` needs `Interval` from `market_data`, while `market_data.live_feed` needs `LiveFeedConfig` from `config`. Neither is re-exported from its package `__init__`, since doing so makes `import config` and `import market_data` mutually recursive. Import them from their modules directly:

```python
from config.live_feed import LiveFeedConfig
from market_data.live_feed import LiveMarketFeed
```

## Indicator layer

Indicators sit between market data and strategies. `IndicatorContext` owns registered indicators, updates every indicator when a new candle arrives, and exposes indicator instances to strategies.

Every indicator follows the same lifecycle: `update(candle)`, `reset()`, and `ready`. Indicators update incrementally and should not recalculate full historical datasets on every candle.

Indicators depend only on `domain` objects. They never import broker SDKs, pandas, repositories, providers, execution code, or strategy code. Indicators only calculate state; strategies decide what to do with that state.

The default indicator engine includes VWAP, Opening Range, and Relative Volume. These indicators expose calculated values and state only; they do not generate trading signals or place trades.

## Instrument metadata

Instrument metadata flows from a repository into `InstrumentManager`. The default repository is CSV-backed today, while `InstrumentManager` only depends on the repository abstraction and keeps in-memory maps for fast symbol and instrument-token lookup.

## ORB strategy

`ORBStrategy` is the first concrete strategy built on this architecture. It consumes the latest `Candle`, an `IndicatorContext`, and `ORBStrategyConfig`; it does not calculate VWAP, opening ranges, relative volume, or sessions itself.

The ORB strategy flow is:

```text
Market Data
    ↓
Indicators
    ↓
ORB Strategy
    ↓
Signal
    ↓
Risk
    ↓
Order Manager
    ↓
Execution Provider
    ↓
Broker Adapter
```

The strategy's sole responsibility is converting indicator state into domain `Signal` objects. It never places orders, imports broker SDKs, imports pandas, manages portfolio capital, or performs risk sizing.

## Risk layer

Risk sits between Strategy and Order Manager and is the framework's gatekeeper for money:

```text
Signal
    ↓
RiskContext
    ↓
SafetyChecks
    ↓
TradeLimits
    ↓
PositionSizer
    ↓
RiskDecision
    ↓
OrderRequest (future)
    ↓
Execution
```

- `RiskDecision` (`domain/risk_decision.py`) is the only outcome the risk gate produces: `approved`, `quantity`, an optional `RejectReason`, and an optional human-readable `message`. There is no separate approved/rejected type; `approved=True`/`False` distinguishes them.
- `RejectReason` (`domain/risk_decision.py`) is a structured enum — `DAILY_LOSS_LIMIT`, `MAX_TRADES`, `INVALID_SIGNAL`, `INSUFFICIENT_CAPITAL`, `POSITION_LIMIT`, `POSITION_ALREADY_OPEN`, `MARKET_CLOSED`, `SAFETY_CHECK_FAILED` — so rejections drive logic without magic strings; `message` carries the human-readable detail for logs.
- `RiskConfig` (`config/risk.py`) holds static, configurable thresholds: `max_trades_per_day`, `max_concurrent_positions`, `daily_loss_limit`, `max_capital_exposure`, `capital_allocation_pct`, `allowed_symbols`. `capital_allocation_pct` sizes a trade as a fraction of total capital — a capital-allocation limit, not a stop-loss-aware risk-per-trade limit, since strategies do not yet carry stop-loss data into the risk gate.
- `RiskContext` (`risk/risk_context.py`) is the mutable, per-day counterpart to `RiskConfig`: current `capital`, `capital_deployed`, `daily_realized_loss`, `trades_today`, `open_positions`, `active_symbols`, `market_open`, and `trading_enabled`. It lives in `risk/` rather than `state/` because it is risk-specific bookkeeping, not the broader order/session/engine state machine `state/` is reserved for.
- `SafetyChecks` (`risk/safety_checks.py`) gates entries on session and symbol conditions: market open, trading enabled, symbol allow-list, and whether the symbol already has an active position (`POSITION_ALREADY_OPEN`).
- `TradeLimits` (`risk/trade_limits.py`) gates entries on portfolio-wide exposure: trades per day, concurrent positions, daily realized loss, and total capital deployed.
- `PositionSizer` (`risk/position_sizer.py`) computes `quantity = int(capital * capital_allocation_pct / entry_price)`, returning `0` for non-positive inputs. It performs no stop-loss, ATR, Kelly, or volatility-based sizing.
- `RiskManager` (`risk/risk_manager.py`) is the orchestrator and contains no rules itself: it approves exit signals (`EXIT_LONG`/`EXIT_SHORT`) unconditionally via `RiskDecision.approved_exit()` — Risk never blocks or sizes an exit, since blocking a close could trap a losing position — then for entry signals runs `SafetyChecks`, then `TradeLimits`, then `PositionSizer`, short-circuiting on the first rejection.

Risk never imports Zerodha, `ExecutionProvider`, `OrderManager`, or `KiteConnect`; it only knows domain objects, configuration, and its own rules. Converting an approved `RiskDecision` into an `OrderRequest` is `OrderRequestBuilder`'s job (see the Execution layer below), not Risk's.

## Execution layer

Execution sits below Risk in the framework flow and turns approved order requests into broker acknowledgements:

```text
Signal
    ↓
Risk
    ↓
Order Manager
    ↓
Execution Provider
    ↓
Broker Adapter
```

- `OrderRequest` (`execution/order_request.py`) is an immutable, broker-independent description of an order: symbol, exchange, `side` (reuses `domain.trade.TradeDirection`), quantity, `OrderType`, `Product`, and optional price/trigger price/tag. It carries no broker-specific fields.
- `ExecutionResult` (`execution/execution_result.py`) is the immutable outcome of any execution-provider operation: `success`, `status` (`OrderStatus`), `timestamp`, and optional `broker_order_id`/`message`/`fill_price`. It never carries broker SDK objects. **TODO (v2):** as fill data grows (filled quantity, partial fills, average price), extract fills into their own `ExecutionFill` object instead of continuing to expand this one.
- `OrderStatus` (`execution/execution_result.py`) is a broker-independent lifecycle enum: `NEW`, `VALIDATED`, `SUBMITTED`, `PENDING`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`, `UNKNOWN`. `UNKNOWN` exists so a broker adapter can surface a status it has never seen before (e.g. a new Kite status added later) without silently mislabeling it as `PENDING`; adapters log a warning whenever they fall back to it.
- `OrderValidator` (`execution/order_validator.py`) applies framework-level rules only: quantity must be positive, limit orders require a price, stop orders require a trigger price, and the order type/product must be in the (configurable) supported set. It knows nothing about any specific broker's rules.
- `OrderRequestBuilder` (`execution/order_request_builder.py`) is the only place that translates a `Signal` + `RiskDecision` into an `OrderRequest`, keeping Risk and Execution from needing to know about each other. It maps `SignalAction` to `TradeDirection` (`BUY`/`SELL` open; `EXIT_LONG`/`EXIT_SHORT` close in the opposite direction) and accepts an optional `quantity` override, required for exits since Risk approves exits with `quantity=0` (it never sizes a close).
- `ExecutionProvider` (`execution/provider.py`) is the abstract interface every execution adapter implements: `place_order`, `cancel_order`, `modify_order`, `get_order_status`. It consumes and returns only framework domain objects, never broker SDK types.
- `OrderManager` (`execution/order_manager.py`) orchestrates a validator and a provider: it validates an `OrderRequest`, returns a locally built `REJECTED` `ExecutionResult` if validation fails (without calling the provider), and otherwise delegates to the `ExecutionProvider`. It has no knowledge of Zerodha or any other broker.
- `PaperExecutionProvider` (`execution/paper_broker.py`) is a deterministic, in-memory `ExecutionProvider` used for testing order-lifecycle plumbing. It accepts orders and assigns incrementing fake order IDs, but simulates no fills, pricing, or market behaviour.
- `SimulatedExecutionProvider` (`execution/simulated_execution_provider.py`) fills MARKET orders immediately at whatever price it was last `advance()`-d to (a replayed candle's close, or eventually a live tick). It represents simulated *execution*, not a specific broker — unlike `PaperExecutionProvider`, it exists to produce realistic fills for backtesting and, later, paper trading against live prices. Limit/stop fill simulation, slippage, latency, and partial fills are out of scope for this version.
- `ZerodhaExecutionProvider` (`broker/zerodha_execution_provider.py`) is the concrete broker adapter. It is the only execution-side module that imports `KiteConnect`: it maps `OrderRequest` fields onto Kite's `place_order`/`cancel_order`/`modify_order`/`order_history` calls and maps Kite's order-status vocabulary back onto `OrderStatus`. It contains no retry logic, no websocket order updates, and no live-trading decision logic.

Execution never calculates indicators, never performs risk management or position sizing, and never knows strategy logic. Strategies never import `execution`, never construct broker orders, and never know `OrderManager` exists.

## Portfolio layer

`Portfolio` (`portfolio/portfolio.py`) owns financial bookkeeping — cash, open positions, and realized PnL — and is shared unchanged by backtesting, paper trading, and live trading. It is not a backtesting concept and does not live under `backtesting/`.

Positions use a **signed-quantity convention**: a positive quantity is a long position, a negative quantity is a short position. This lets one formula, `pnl = (exit_price - entry_price) * signed_quantity`, compute correct PnL for both directions without a separate branch per side. Open positions are reused `domain.Position` objects, keyed by symbol; a small private wrapper adds the `entry_time` needed to build a `TradeRecord`, without adding backtest-only fields to the shared domain type.

- `Portfolio.snapshot()` builds a `RiskContext` from the portfolio's current state (cash, capital deployed, open positions, daily counters), so `RiskManager` never needs to know how a portfolio is implemented.
- `Portfolio.on_fill(order, result, signal)` reacts to a `FILLED` `ExecutionResult`: opens a position for an entry signal, or closes one for an exit signal, recording a `TradeRecord` (`domain/trade_record.py`) and updating realized PnL and the daily loss counter.
- `Portfolio.reset_daily_counters()` clears `daily_realized_loss` and `trades_today` at a new session boundary.
- `TradeLog` (`portfolio/trade_log.py`) is an append-only log of `TradeRecord`s in close order.
- `TradeRecord` is a domain object, not a backtesting one: paper trading and live trading will produce the same shape of completed-trade record.

## Performance layer

`performance/` computes pure statistics over a list of `TradeRecord`s; it owns no data of its own — `Portfolio`/`TradeLog` own the data, `performance/` only reads it. This keeps trade-statistics math in one place regardless of who is asking (backtesting today; live dashboards or paper-trading reports later).

- `performance/expectancy.py`: `win_rate`, `average_winner`, `average_loser`, `profit_factor` (gross profit ÷ gross loss; `inf` if there are wins and no losses, `0.0` with no data).
- `performance/drawdown.py`: `max_drawdown`, the largest peak-to-trough drop in cumulative realized PnL across trades in close order. This tracks realized PnL only, not a mark-to-market equity curve.

## Backtesting layer

Backtesting replays historical candles through every layer above, unchanged:

```text
Historical Candles
    ↓
Replay
    ↓
IndicatorContext
    ↓
Strategy
    ↓
Risk
    ↓
OrderRequestBuilder
    ↓
Order Manager (SimulatedExecutionProvider)
    ↓
Portfolio
    ↓
Trade Log
    ↓
Results
```

- `Replay` (`backtesting/replay.py`) is deliberately dumb: it yields historical candles one at a time, in order. No indicators, no strategy, no fills — nothing that a live tick feed wouldn't also need to support later.
- `BacktestEngine` (`backtesting/engine.py`) is a thin wrapper over `RuntimeEngine`. It supplies backtest-appropriate configuration (`continue_on_error=False`) and a `Replay` feed; the per-candle pipeline itself lives in `runtime/` so backtesting and live running can never drift apart.
- `Results` (`backtesting/results.py`) is a thin adapter: it reads a `TradeLog` and calls into `performance/` to build a `BacktestResults` (trade count, win rate, net PnL, average winner/loser, profit factor, max drawdown) — no metric math is duplicated here.

**Why the day-boundary reset matters:** without it, `VWAP`'s cumulative price/volume and `OpeningRange`'s high/low would silently carry over from one trading day into the next, corrupting every subsequent day's breakout and VWAP checks in a multi-day backtest. `RuntimeEngine` resetting `IndicatorContext` at each session boundary is what makes multi-day replay results trustworthy.

Nothing in `Portfolio`, `TradeLog`, `Results`, or `OrderRequestBuilder` depends on `Replay` or historical candles directly — swapping `SimulatedExecutionProvider` for `PaperExecutionProvider`/`ZerodhaExecutionProvider`, and `Replay` for a live feed, reuses the rest of this pipeline unchanged for paper and live trading.

## Runtime layer

The runtime is the orchestration layer that continuously feeds candles into everything above. It is deliberately boring: **if it ever starts containing trading rules, the design is wrong.** It never calculates indicators, generates signals, evaluates risk, places broker orders directly, calculates PnL, or knows any strategy's rules — every component it coordinates already exists and is injected.

```text
Feed (Iterable[Candle])
    ↓
RuntimeEngine ── owns ──> RuntimeState
    ↓
IndicatorContext → Strategy → Risk → OrderRequestBuilder → OrderManager → Portfolio
```

- `RuntimeEngine` (`runtime/engine.py`) owns the loop and lifecycle: `run(feed)`, `process_candle(candle)`, `pause()`, `resume()`, `stop()`.
- `RuntimeConfig` (`runtime/config.py`) is immutable configuration: the `MarketSession` and `continue_on_error`. It deliberately does **not** carry symbol/exchange/order-type/product (those already live on the injected `OrderRequestBuilder`) nor any per-execution metadata.
- `RuntimeState`/`RuntimeStatus` (`state/runtime_state.py`) carry per-execution metadata: `runtime_id`, status (`NOT_STARTED`/`RUNNING`/`PAUSED`/`STOPPED`), `last_processed_candle`, `current_session_date`, `candles_processed`, `error_count`, `started_at`/`stopped_at`. `runtime_id` lives here rather than in `RuntimeConfig` because it describes one running instance, not immutable configuration.

### The feed is just an iterable

There is no `MarketFeed` class and no `Scheduler`. A feed is any `Iterable[Candle]`: `Replay` for history (finite, iterates immediately), or a future live feed wrapping `MarketDataProvider.stream_ticks` (whose iterator blocks until a real tick arrives). Pacing is the feed's concern; from the engine's perspective `for candle in feed` looks identical either way. Inventing a class for something the stdlib already expresses would add indirection without adding capability.

### One candle, end to end

1. Record the candle on `RuntimeState` and emit `CANDLE_RECEIVED`.
2. If `MarketSession.should_reset` reports a new session, reset `IndicatorContext` and `Portfolio.reset_daily_counters()`, then emit `SESSION_ROLLED`.
3. Update `IndicatorContext`; call `ExecutionProvider.advance(candle)`.
4. If paused, stop here — a paused engine still observes candles and keeps indicators warm, but takes no action.
5. Ask the strategy for a `Signal`. Non-entry/non-exit signals end the candle.
6. Snapshot the portfolio into a `RiskContext` and ask `RiskManager` to evaluate. A rejection emits `TRADE_REJECTED` (with its `RejectReason`) and ends the candle.
7. Resolve quantity: from the `RiskDecision` for entries, or from the portfolio's actual open position size for exits (Risk approves exits without sizing them).
8. Build the `OrderRequest`, submit it through `OrderManager`, and let `Portfolio` react to the fill. `Portfolio.on_fill` returns a `TradeRecord` when a position actually closed, which is what drives `TRADE_CLOSED`.

### `ExecutionProvider.advance()`

`ExecutionProvider.advance(candle)` is a default no-op on the base class. `SimulatedExecutionProvider` overrides it to track the current fill price; `PaperExecutionProvider` and `ZerodhaExecutionProvider` inherit the no-op, because a real broker does not need to be told the current price. This keeps the runtime free of `hasattr` checks or provider-type special cases — the contract is explicit rather than a hidden protocol.

### Error handling

Each pipeline stage (strategy, risk, execution) is wrapped separately, so one kind of failure is never mistaken for another. On a stage error the engine logs with the stage name and candle, emits `ERROR_OCCURRED`, increments `error_count`, and skips the rest of that candle. Whether it then continues depends on `continue_on_error`, which separates two genuinely different operating modes: a live engine should survive a recoverable error and keep running (`True`), while a backtest should fail loudly rather than silently skip a bad candle and report misleading results (`False`). A failure raised by the feed itself is caught around the loop, logged, and stops the engine — reconnect/retry logic belongs to a live feed's own implementation, not the engine.

### Runtime events

`RuntimeEvent` (`runtime/events.py`) is an enum of notable points — runtime started/stopped/paused/resumed, candle received, session rolled, signal generated, trade rejected, order submitted/filled, trade closed, error occurred. `RuntimeEngine` accepts one optional `on_event` callback (`Callable[[RuntimeEvent, dict], None]`).

This is intentionally **not** an event framework: no bus, no registry, no dispatcher, no listener base class. It exists so future consumers (dashboard, notifications, watchdog, metrics) have an obvious place to listen without the engine knowing who cares. A callback that raises is logged and swallowed — a broken listener must never break a running engine.

### Logging

Standard-library `logging.getLogger(__name__)`, matching `broker/zerodha_execution_provider.py`. Every line is prefixed with `runtime_id` so concurrent or sequential runs stay traceable. Candle receipt logs at DEBUG (too frequent for INFO on a live feed); signals, risk decisions, orders, trades, and lifecycle transitions log at INFO; stage failures log at ERROR with traceback.

### Future compatibility

Paper trading and live Zerodha are provider swaps (`SimulatedExecutionProvider` / `ZerodhaExecutionProvider`) plus a feed swap — no engine changes. A dashboard reads `Portfolio`, `TradeLog`, `RuntimeState`, and `performance/`, all already plain inspectable objects. A watchdog observes `RuntimeState` (e.g. a stale `last_processed_candle` during market hours) and can call `stop()`. Notifications hook the event callback. Multiple strategies or symbols run as one `RuntimeEngine` instance each; a shared-capital multi-strategy allocator is a genuinely new concept deferred to Version 2 rather than pre-solved here.

## Paper trading

Paper trading is **not another engine**. It is a composition of components that already exist:

```text
LiveMarketFeed  →  RuntimeEngine  →  Strategy → Risk → OrderRequestBuilder → OrderManager
                                                                                  │
                                                                    SimulatedExecutionProvider
                                                                                  │
                                                                              Portfolio → TradeLog
```

It lives in `runtime/paper_trading.py` rather than its own package, because it introduces no new concept — the same reasoning that makes `BacktestEngine` a thin wrapper rather than a parallel engine. Nothing upstream of `OrderManager` knows which execution provider is in use.

- `PaperTradingRunner` (`runtime/paper_trading.py`) assembles a `LiveMarketFeed`, a `RuntimeEngine`, a `SimulatedExecutionProvider`, and a `Portfolio`, then exposes `run()`, `stop()`, and read-only `portfolio`/`trade_log`/`state`. It holds no positions, computes no PnL, evaluates no risk, and knows no strategy rules.
- `PaperTradingConfig` (`config/paper_trading.py`) carries what no component config owns — `symbol`, `exchange`, `starting_capital` — and aggregates `LiveFeedConfig` and `RiskConfig`. Like `LiveFeedConfig`, it is **not** re-exported from `config/__init__.py`, for the same import-cycle reason.

Two things justify the runner existing at all rather than inline wiring. The **same** `SimulatedExecutionProvider` instance must reach both the `OrderManager` and the `RuntimeEngine`; passing two would leave one armed with prices via `advance()` and the other placing orders, raising `ExecutionProviderError` on the first trade. And `stop()` shuts down the engine and the feed together, instead of relying on generator finalisation to tear down the feed's background thread.

There is deliberately **no `start()`**: a non-blocking start would mean another thread, and the only threading in this framework exists because the broker SDK is callback-driven. `run()` blocks; `stop()` is safe to call from a signal handler because it only sets an event.

**Performance is not recomputed here.** The runner exposes `trade_log`, and the caller runs the existing `performance/` functions over it — exactly as backtesting does. `backtesting.Results` is deliberately not imported, since `backtesting/` already depends on `runtime/` and the reverse edge would close an import cycle. That `Results` is generic enough to belong in `performance/` is a known Version 1 imperfection, left in place because the architecture freeze forbids moving files.

One session is one strategy, one symbol, one trading day. `Portfolio` is in-memory, so capital and trade history reset on each run; scheduling across days, multiple symbols, and multi-strategy allocation are Version 2 concerns.

### Paper trading versus live trading

Becoming live trading means changing one line — swapping `SimulatedExecutionProvider` for `ZerodhaExecutionProvider`, whose inherited no-op `advance()` makes the swap safe. Three differences remain genuinely open for Version 2, and are worth naming rather than glossing over:

- **Fills stop being instantaneous.** A real order can be pending, partially filled, rejected, or cancelled. `Portfolio.on_fill` correctly ignores non-`FILLED` results, which means live position state needs order-status reconciliation that paper trading never exercises.
- **Access tokens expire daily.** `settings.access_token` is read once at import.
- **No slippage or latency is modelled**, so paper results are optimistic by construction. Fills occur at the close of the candle that produced the signal — the same simplification backtesting makes, deliberately, so paper and backtest results agree.

## Strategy API evolution

Version 1 strategies use `generate_signal(candle, context)` and return a single domain `Signal`. This keeps the first strategy API simple while the framework is still building core layers.

Before Version 2, the strategy interface can evolve toward `on_candle(context)` returning `list[Signal]`. Returning a collection will support future strategy needs such as emitting an exit and an entry on the same candle, scaling in, scaling out, or generating non-trade alerts without changing downstream consumers again.
