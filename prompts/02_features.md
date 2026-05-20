# Wave 1 — Features (parallel; owns `trading_engine/features/`)

Build the technical-feature library for the Systematic Momentum Options Engine.
Read `claude_code_trading_engine_outline.md` §4–§6 for how these features feed
ranking and setup detection. **Wave 0 is done and committed** — shared types and
fixtures exist. Do not modify them.

## Constraints
- Only create/edit files in `trading_engine/features/` and tests in
  `tests/features/`. Do not touch `core/`, data, scanners, setups, etc.
- Pure functions over `OHLCVSeries` / `Candle` from `trading_engine.core.types`.
  No data fetching, no I/O, no global state — these must be deterministic so
  signals are replayable (spec's non-negotiable rules).
- Use pandas/numpy. Typed function signatures throughout.

## What to build
1. `indicators.py`: EMA (8/20/50), VWAP (session-aware for intraday), ATR,
   rolling volume averages, prior-day high/low, opening range, gap %, and a
   helper for "above/below VWAP". These back the regime + setup logic.
2. `relative_strength.py`: stock return vs SPY and vs QQQ over multiple lookbacks
   (1d/5d/20d + intraday), returned as a normalized RS score plus raw values
   (spec §5 RelativeStrength, §4 intraday-vs-index).
3. `trend.py`: EMA alignment + slope → a `TrendScore`; classify uptrend /
   downtrend / range (spec §5 TrendScore).
4. `compression.py`: range-contraction / inside-day / tight-close detection,
   wedge/flag/pennant geometry, and breakout-proximity → a `StructureScore`
   (spec §5 StructureScore, §6 Setup D inputs). Expose reusable primitives
   (e.g. `detect_inside_day`, `range_contraction_ratio`, `local_pivots`,
   `trendline_break`) because the setup detectors in Wave 2 will call these.
5. `volume.py`: current/recent volume vs average → `VolumeExpansionScore`
   (spec §5).

Each public function returns a typed result and, where it contributes to a
score, a short list of human-readable reason strings (reason codes are required
by the spec).

## Tests (`tests/features/`)
Use the Wave 0 fixtures (uptrend, pullback-to-8EMA, compression→breakout,
breakdown, chop). Assert: EMA/VWAP/ATR numeric correctness on a known series,
RS positive for the outperformer, compression flags fire on the compression
fixture and not on the trending one, etc.

## Done criteria
`pytest tests/features` passes; `ruff`/`mypy` clean on `features/`. Commit on
your branch. These are the building blocks Wave 2 depends on — keep signatures
clean and documented.
