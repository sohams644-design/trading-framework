# Architecture

The project follows a package-oriented trading framework layout:

- `config/` contains runtime configuration and environment-backed settings.
- `domain/` contains business objects shared across the framework, including candles, signals, trades, positions, and instruments.
- `models/` contains compatibility exports for domain objects while callers migrate to `domain/` imports.
- `strategies/` contains strategy interfaces and concrete strategy implementations.
- `indicators/` contains broker-independent, incremental indicator calculations and indicator context orchestration.
- `market_data/` contains provider abstractions, interval definitions, instrument lookup, validation, repositories, and historical loading.
- `broker/` contains broker-specific adapters that isolate third-party SDKs from framework code.
- `risk/` contains the risk gate: `RiskContext`, `SafetyChecks`, `TradeLimits`, `PositionSizer`, and the `RiskManager` orchestrator that turns a `Signal` into a `RiskDecision`.
- `execution/` contains the broker-independent execution pipeline: order contracts (`OrderRequest`, `ExecutionResult`, `OrderStatus`), the `ExecutionProvider` interface, `OrderValidator`, `OrderManager`, `OrderRequestBuilder`, and the in-memory `PaperExecutionProvider`/`SimulatedExecutionProvider`.
- `portfolio/` contains financial bookkeeping shared by backtesting, paper trading, and live trading: `Portfolio` (cash, positions, realized PnL) and `TradeLog`.
- `performance/` contains pure statistics over completed trades: win rate, average winner/loser, profit factor, and max drawdown.
- `backtesting/` replays historical candles through every layer above via `Replay`, `BacktestEngine`, and `Results`.
- `state/` contains state machine support for trading workflows (order/session/engine lifecycle) — distinct from `portfolio/`, which owns financial/accounting state, not lifecycle state.
- `utils/` contains compatibility helpers for logging, instruments, and market data.
- `watchdog/` contains health monitoring and emergency controls.

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

The `MarketDataProvider` interface defines historical candles, live quotes, and tick streaming. All provider methods expose framework `list[Candle]` values, so strategy code never depends on broker payloads, pandas data frames, REST responses, CSV files, or database rows. The Zerodha adapter implements this interface and is the only market-data component that imports `KiteConnect`.

Historical data loading is separated from strategy logic. A strategy requests candles through `HistoricalDataLoader.load(symbol, from_date, to_date, interval)`, where `interval` is a typed `Interval` enum value. The loader validates candles before returning them so malformed broker data fails early.

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
- `BacktestEngine` (`backtesting/engine.py`) owns the per-candle loop and contains no rules of its own. For every candle it: detects a new session boundary (reusing `MarketSession.should_reset`, not new logic) and if so resets `IndicatorContext` and the portfolio's daily counters; updates indicators; advances `SimulatedExecutionProvider` to the candle's close; asks the strategy for a signal; for entry/exit signals, snapshots the portfolio into a `RiskContext`, asks `RiskManager` to evaluate, and on approval resolves the order quantity (from the `RiskDecision` for entries, or from the portfolio's actual open position size for exits, since Risk doesn't size exits), builds an `OrderRequest`, submits it through `OrderManager`, and lets `Portfolio` react to the fill.
- `Results` (`backtesting/results.py`) is a thin adapter: it reads a `TradeLog` and calls into `performance/` to build a `BacktestResults` (trade count, win rate, net PnL, average winner/loser, profit factor, max drawdown) — no metric math is duplicated here.

**Why the day-boundary reset matters:** without it, `VWAP`'s cumulative price/volume and `OpeningRange`'s high/low would silently carry over from one trading day into the next, corrupting every subsequent day's breakout and VWAP checks in a multi-day backtest. `BacktestEngine` resetting `IndicatorContext` at each session boundary is what makes multi-day replay results trustworthy.

Nothing in `Portfolio`, `TradeLog`, `Results`, or `OrderRequestBuilder` depends on `Replay` or historical candles directly — swapping `SimulatedExecutionProvider` for `PaperExecutionProvider`/`ZerodhaExecutionProvider`, and `Replay` for a live feed, reuses the rest of this pipeline unchanged for paper and live trading.

## Strategy API evolution

Version 1 strategies use `generate_signal(candle, context)` and return a single domain `Signal`. This keeps the first strategy API simple while the framework is still building core layers.

Before Version 2, the strategy interface can evolve toward `on_candle(context)` returning `list[Signal]`. Returning a collection will support future strategy needs such as emitting an exit and an entry on the same candle, scaling in, scaling out, or generating non-trade alerts without changing downstream consumers again.
