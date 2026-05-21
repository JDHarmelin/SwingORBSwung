# Wave 1 — Storage (parallel; owns `trading_engine/storage/`)

Build the persistence layer for the Systematic Momentum Options Engine. Read the
"Database outline" section of `claude_code_trading_engine_outline.md`. **Wave 0
is done and committed** — shared types and the `Repository` interface exist. Do
not modify them.

## Wave 0 reference (already on `main`)
- Shared models + enums: `trading_engine.core.types`
- `Repository` Protocol to implement: `trading_engine.core.interfaces`
- Config loader (for `DATABASE_URL` etc.): `trading_engine.core.config`
- Sample data for round-trip tests: `trading_engine.testing.synthetic` / `tests/conftest.py`

## Constraints
- Only create/edit files in `trading_engine/storage/` and tests in
  `tests/storage/`. Do not touch `core/` or other modules.
- Implement the `Repository` protocol from `trading_engine.core.interfaces`.
  Persist and reconstruct the shared models from `trading_engine.core.types`
  losslessly — the spec requires every signal be **replayable** from stored
  candles + metadata.

## What to build
1. `models.py`: SQLAlchemy models for every table in the DB outline — `candles`,
   `market_regime`, `sector_scores`, `symbol_scores`, `signals`,
   `signal_events`. Use the exact columns listed; JSON columns for the
   `*_json` fields. Add sensible indexes (symbol+timeframe+timestamp on candles;
   symbol+timestamp on scores; status on signals).
2. `repository.py`: a `SqlRepository(Repository)` implementing upsert/query for
   candles (bulk insert for backfills), regimes, sector/symbol scores, signals
   (create + status transitions), and signal_events (append-only). Provide query
   helpers the orchestrator will need: latest regime, top-N scored symbols for a
   timestamp, open signals, events for a signal.
3. `db.py`: engine/session setup driven by config (`DATABASE_URL`, default to a
   local SQLite file for dev), plus schema creation / lightweight migration.
4. A round-trip serializer so `core.types` ↔ ORM conversion lives here, not
   leaking SQLAlchemy into the rest of the app.

## Tests (`tests/storage/`)
Use an in-memory / temp SQLite db. Round-trip every model type (write then read,
assert equality). Test signal status transitions and signal_event append.
Construct inputs from Wave 0 fixtures where helpful. No external services.

## Done criteria
`pytest tests/storage` passes; `ruff`/`mypy` clean on `storage/`. Commit on your
branch.
