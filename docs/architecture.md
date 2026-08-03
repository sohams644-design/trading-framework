# Architecture

The project follows a package-oriented trading framework layout:

- `config/` contains runtime configuration and environment-backed settings.
- `domain/` contains business objects shared across the framework, including candles, signals, trades, positions, and instruments.
- `models/` contains compatibility exports for domain objects while callers migrate to `domain/` imports.
- `strategies/` contains strategy interfaces and concrete strategy implementations.
- `indicators/` contains broker-independent, incremental indicator calculations and indicator context orchestration.
- `market_data/` contains provider abstractions, interval definitions, instrument lookup, validation, repositories, and historical loading.
- `broker/` contains broker-specific adapters that isolate third-party SDKs from framework code.
- `risk/` contains risk management and position sizing components.
- `execution/` contains the broker-independent execution pipeline: order contracts (`OrderRequest`, `ExecutionResult`, `OrderStatus`), the `ExecutionProvider` interface, `OrderValidator`, `OrderManager`, and the in-memory `PaperExecutionProvider`.
- `backtesting/` contains simulation and metrics components.
- `performance/` contains reporting and performance analytics.
- `state/` contains state machine support for trading workflows.
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
Risk (future)
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
Risk (future)
    ↓
Order Manager
    ↓
Execution Provider
    ↓
Broker Adapter
```

The strategy's sole responsibility is converting indicator state into domain `Signal` objects. It never places orders, imports broker SDKs, imports pandas, manages portfolio capital, or performs risk sizing.

## Execution layer

Execution sits below Risk in the framework flow and turns approved order requests into broker acknowledgements:

```text
Signal
    ↓
Risk (future)
    ↓
Order Manager
    ↓
Execution Provider
    ↓
Broker Adapter
```

This sprint builds the contract and orchestration only; Risk is not implemented yet, so callers construct `OrderRequest` objects directly until Sprint 6 inserts a `RiskManager` ahead of `OrderManager`.

- `OrderRequest` (`execution/order_request.py`) is an immutable, broker-independent description of an order: symbol, exchange, `side` (reuses `domain.trade.TradeDirection`), quantity, `OrderType`, `Product`, and optional price/trigger price/tag. It carries no broker-specific fields.
- `ExecutionResult` (`execution/execution_result.py`) is the immutable outcome of any execution-provider operation: `success`, `status` (`OrderStatus`), `timestamp`, and optional `broker_order_id`/`message`. It never carries broker SDK objects.
- `OrderStatus` (`execution/execution_result.py`) is a broker-independent lifecycle enum: `NEW`, `VALIDATED`, `SUBMITTED`, `PENDING`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`, `UNKNOWN`. `UNKNOWN` exists so a broker adapter can surface a status it has never seen before (e.g. a new Kite status added later) without silently mislabeling it as `PENDING`; adapters log a warning whenever they fall back to it.
- `OrderValidator` (`execution/order_validator.py`) applies framework-level rules only: quantity must be positive, limit orders require a price, stop orders require a trigger price, and the order type/product must be in the (configurable) supported set. It knows nothing about any specific broker's rules.
- `ExecutionProvider` (`execution/provider.py`) is the abstract interface every broker adapter implements: `place_order`, `cancel_order`, `modify_order`, `get_order_status`. It consumes and returns only framework domain objects, never broker SDK types.
- `OrderManager` (`execution/order_manager.py`) orchestrates a validator and a provider: it validates an `OrderRequest`, returns a locally built `REJECTED` `ExecutionResult` if validation fails (without calling the provider), and otherwise delegates to the `ExecutionProvider`. It has no knowledge of Zerodha or any other broker.
- `PaperExecutionProvider` (`execution/paper_broker.py`) is a deterministic, in-memory `ExecutionProvider` used for testing and paper trading. It accepts orders, assigns incrementing fake order IDs, and tracks order state without simulating fills, pricing, or market behaviour.
- `ZerodhaExecutionProvider` (`broker/zerodha_execution_provider.py`) is the concrete broker adapter. It is the only execution-side module that imports `KiteConnect`: it maps `OrderRequest` fields onto Kite's `place_order`/`cancel_order`/`modify_order`/`order_history` calls and maps Kite's order-status vocabulary back onto `OrderStatus`. It contains no retry logic, no websocket order updates, and no live-trading decision logic.

Execution never calculates indicators, never performs risk management or position sizing, and never knows strategy logic. Strategies never import `execution`, never construct broker orders, and never know `OrderManager` exists.

## Strategy API evolution

Version 1 strategies use `generate_signal(candle, context)` and return a single domain `Signal`. This keeps the first strategy API simple while the framework is still building core layers.

Before Version 2, the strategy interface can evolve toward `on_candle(context)` returning `list[Signal]`. Returning a collection will support future strategy needs such as emitting an exit and an entry on the same candle, scaling in, scaling out, or generating non-trade alerts without changing downstream consumers again.
