# Trading Framework

A modular algorithmic trading framework. The ORB strategy is one plugin running
inside it, not the point of it.

```
Historical Replay ─┐                    ┌─ SimulatedExecutionProvider
                   ├─▶ Runtime Engine ──┤
Live Market Feed ──┘   │                └─ ZerodhaExecutionProvider
                       ▼
        Indicators → Strategy → Risk → OrderRequestBuilder → OrderManager
                       ▼
                   Portfolio → Performance
```

See [docs/architecture.md](docs/architecture.md) for the full design, the layer
boundaries, and the rules each layer must obey.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file (it is gitignored):

```
API_KEY=your_kite_api_key
API_SECRET=your_kite_api_secret
```

You also need an instrument dump at `data/instruments.csv` with at least
`instrument_token` and `tradingsymbol` columns.

## Backtesting

Replays historical candles through the same runtime loop that paper and live
trading use.

```bash
python run_backtest.py RELIANCE --from 2026-05-18 --to 2026-08-07
```

Options: `--exchange`, `--capital`, `--interval`, `--log-level`. History is
fetched through the Zerodha provider, so the same daily login applies.

Fills are simulated at candle close with no slippage, brokerage, or taxes, so
reported PnL is optimistic by construction — see the note the summary prints.

## Paper trading

Simulated fills against live market data. **No orders ever reach a broker.**

```bash
python run_paper.py RELIANCE
```

Options: `--exchange`, `--capital`, `--interval`, `--log-level`.

```bash
python run_paper.py RELIANCE --capital 50000 --interval 5minute
```

Start it before the opening bell; the feed idles until the market opens, trades
the session, squares off, and prints a summary at the close. `Ctrl+C` stops it
cleanly and still prints the summary.

### About the daily login

Kite access tokens expire every day. The framework caches the token in
`data/zerodha_token.json` (gitignored — it is a live credential) and reuses it
for the rest of the day, so no code or config edits are needed to restart.

When the token has actually expired, the script prints a login URL and asks for
the `request_token` from the redirect. **That step is not automatable**: the
token only exists after a human completes Zerodha's own browser login. Expect
one login per trading day.

## Running tests

```bash
python -m pytest
```

## Status

Version 1 architecture is frozen (see the freeze note in the architecture doc).
Backtesting, the runtime engine, the live market feed, and paper trading are
complete. Live order execution is deliberately **not** wired to an entry point.

The ORB strategy itself has three known defects that a backtest surfaces: it
can enter after the square-off time, its position state desynchronises from
the portfolio across a session boundary, and it advances that state on signals
the risk gate later rejects. See `docs/strategy.md`.
