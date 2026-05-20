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

Subsequent waves (1+) build real adapters, scanners, setup detectors, the
risk engine, and the Telegram alert service on top of these contracts.
