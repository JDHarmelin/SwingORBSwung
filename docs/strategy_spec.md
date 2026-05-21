# Strategy spec — pointer

The full strategy outline lives at `claude_code_trading_engine_outline.md`
in the repo root. That document is the source of truth for setups, factor
weights, contract rules, and the management template.

## Non-negotiable rule (read this first)

**This is an alert / paper-only research tool.** It must never place orders,
move money, or connect to a brokerage for execution. Nothing it produces is
financial advice — treat every output as research only.

## Package layout (Wave 0)

```text
trading_engine/
  core/                 # shared types, interfaces, config
    types.py            # Candle, OHLCVSeries, Signal, SymbolScore, ...
    interfaces.py       # MarketDataProvider, OptionsDataProvider, ...
    config.py           # YAML + env loader
  data/
    mock_provider.py    # in-memory mocks (Wave 0); Polygon adapter lands in Wave 1
  features/             # indicators, RS, compression, trend, sector_rank
  scanners/             # universe_builder, market_regime, stock_ranker
  setups/               # 6 setup detectors (A–F)
  risk/                 # position_sizing, contract_selector, trade_management
  alerts/               # telegram, formatter
  storage/              # models, repository
  services/             # signal_service, scheduler, backfill
  testing/
    synthetic.py        # OHLCV generators + sample option chain, importable
config/
  settings.yaml         # thresholds, factor weights, risk template
  universe.yaml         # starter S&P/Nasdaq names + sector ETF map
tests/
  conftest.py           # exposes fixtures to every wave
  fixtures/             # re-exports the synthetic helpers
docs/
  strategy_spec.md      # this file
```

## What Wave 0 delivers

- Typed models and enums for every cross-module concept (`core/types.py`).
- Protocol interfaces for data, alerts, and persistence (`core/interfaces.py`).
- Config loader for YAML + env-resolved secrets (`core/config.py`).
- Realistic, deterministic test fixtures (synthetic OHLCV shapes, sample
  option chain that includes a deliberately illiquid contract for §7
  rejection tests, sector ETF series, starter universe).
- A mock data adapter that implements every provider Protocol against those
  fixtures, so later waves can develop without any API keys.

## Running the engine (all waves)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in keys for live mode

pytest
# Mock dev (symbols from config/universe.yaml, synthetic OHLCV)
python -m trading_engine scan-once
python -m trading_engine rank
python -m trading_engine run --interval 300

# Live Polygon + Telegram (reads .env automatically)
# Flags can go before OR after the subcommand:
python -m trading_engine scan-once --provider polygon --alerts telegram
python -m trading_engine --provider polygon --alerts telegram run

# Override tickers or force liquidity filter
python -m trading_engine scan-once --symbols NVDA,AMD
python -m trading_engine scan-once --provider polygon --filter-universe
```

Scan/rank/run/backfill default to **`config/universe.yaml`** symbols. With
`--provider polygon`, liquidity filtering via `build_universe()` is on by
default; use `--no-filter-universe` to scan the raw YAML list.

### Environment (`.env` or shell)

| Variable | Purpose |
|----------|---------|
| `POLYGON_API_KEY` | Live OHLCV + options (`--provider polygon`) |
| `TELEGRAM_BOT_TOKEN` | Telegram alerts (`--alerts telegram`) |
| `TELEGRAM_CHAT_ID` | Telegram destination chat |
| `DATABASE_URL` | SQLite default: `sqlite:///./trading_engine.db` |
| `DATA_PROVIDER` | Default CLI provider: `mock` or `polygon` |
| `ALERT_SINK` | Default alert sink: `console` or `telegram` |

Default CLI uses **mock provider + console sink** — no API keys required.
