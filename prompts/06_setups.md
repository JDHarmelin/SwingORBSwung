# Wave 2 — Setup detectors (parallel; owns `trading_engine/setups/`)

Build the modular setup-detection engine for the Systematic Momentum Options
Engine. Read `claude_code_trading_engine_outline.md` §6 (all six setups) closely.
**Waves 0 and 1 are done and committed** — shared types/interfaces, data adapters
(incl. mock), and the `features/` library exist. Do not modify them.

## Constraints
- Only create/edit files in `trading_engine/setups/` and tests in
  `tests/setups/`. Do not touch `core/`, `features/`, `scanners/`, etc.
- Build on `features/` primitives (EMA/VWAP/ATR, RS, compression, pivots,
  trendline break). Do NOT re-implement indicators here.
- Detectors are pure given their input context → replayable. No data fetching
  inside detectors; they receive candles + scores via a context object.

## What to build
Define a common base in `base.py`:
- A `SetupContext` dataclass (candles by timeframe, latest `MarketRegime`, the
  symbol's `SymbolScore`, sector context, option-chain handle for later contract
  selection).
- A `Setup` interface with `detect(context) -> list[Signal]`, an `explanation`
  string, and a trigger/stop/target template. Each emitted `Signal` must carry
  `trigger_price`, `stop_price`, a target plan stub (per §8), `setup_type`,
  `direction`, reason codes, and a human-readable rationale.

Then one file per setup, each implementing `Setup` exactly per spec §6:
- `breakout_continuation.py` (Setup A)
- `breakout_retest.py` (Setup B)
- `ema_continuation.py` (Setup C — 8/20 EMA pullback + reclaim)
- `compression_break.py` (Setup D — wedge/flag/pennant break + volume expansion)
- `relative_weakness.py` (Setup E — short/put, only when regime allows shorts)
- `index_tactical.py` (Setup F — SPY/QQQ/SPX ORB, reclaim, gap-fill, sweeps;
  day-trade only)

Add a `registry.py` exposing all detectors as a list the orchestrator can
iterate. Respect the spec's non-negotiables: a setup must not fire without
regime context, and not on price movement alone (it must already be in the
ranked bucket / pass structure).

## Tests (`tests/setups/`)
Use synthetic candles (extend Wave 0 fixtures or build per-setup fixtures): each
detector fires on its matching pattern and stays silent on the others. Verify
Setup E does not fire when regime is `long_bias`/`no_trade`, and trigger/stop
levels are computed from structure (not arbitrary).

## Done criteria
`pytest tests/setups` passes offline; `ruff`/`mypy` clean on `setups/`. Commit on
your branch.
