# Wave 2 — Scanners (parallel; owns `trading_engine/scanners/`)

Build the regime + ranking scanners for the Systematic Momentum Options Engine.
Read `claude_code_trading_engine_outline.md` §3 (Market regime), §4 (Sector
ranking), §5 (Stock ranking). **Waves 0 and 1 are done and committed** — shared
types/interfaces, the data adapters (incl. mock provider), and the `features/`
library all exist. Do not modify them.

## Constraints
- Only create/edit files in `trading_engine/scanners/` and tests in
  `tests/scanners/`. Do not touch `core/`, `data/`, `features/`, etc.
- Depend on the `MarketDataProvider`/`OptionsDataProvider` **interfaces** (inject
  a provider; tests use the mock) and import feature functions from
  `trading_engine.features.*`. Read weights/thresholds from config (Wave 0).
- Deterministic given the same candles (replayability rule).

## What to build
1. `market_regime.py`: compute the `MarketRegime` per spec §3 — SPY/QQQ vs VWAP,
   daily trend vs 8/20/50 EMA, breadth, sector participation, and the event
   filter (CPI/FOMC/mega-cap earnings via `EventsProvider`). Output the JSON
   shape in §3 (regime, confidence 0–1, reason notes). Classify long_bias /
   short_bias / mixed / no_trade.
2. `sector_rank.py`: rank sectors/themes per spec §4 — RS vs SPY over 1d/5d/20d,
   intraday vs SPY/QQQ, intra-sector breadth, volume expansion, trend quality →
   `SectorScore` with reason codes. Use the sector→ETF map from config.
3. `stock_ranker.py`: compute the composite `SymbolScore` using the exact factor
   weights from spec §5 (RS .30, Sector .20, Structure .20, Trend .15, Volume
   .10, Catalyst .05), pulling sub-scores from `features/` and `sector_rank`.
   Return top-20 long and top-20 short buckets, each entry carrying its
   sub-scores and reason codes.

## Tests (`tests/scanners/`)
Drive everything through the **mock provider + Wave 0 fixtures**. Assert: regime
flips correctly between the trending and choppy fixtures and goes `no_trade`
under the event filter; the leading sector ETF ranks above a lagging one; the
clear outperformer lands in the top long bucket and the breakdown name in the top
short bucket; composite weights sum and apply correctly.

## Done criteria
`pytest tests/scanners` passes offline; `ruff`/`mypy` clean on `scanners/`.
Commit on your branch. These outputs feed setup detection and orchestration.
