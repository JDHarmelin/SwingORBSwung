# Wave 3 — Orchestration (run ALONE, last)

Wire the Systematic Momentum Options Engine together end-to-end. Read
`claude_code_trading_engine_outline.md` §1–§10, the MVP roadmap, and the
non-negotiable design rules. **Waves 0–2 are all done and committed** — data
adapters, features, scanners, setups, risk/contracts, alerts, and storage all
exist and pass their own tests. Your job is integration only.

## Constraints
- You own `trading_engine/services/`, `trading_engine/app.py`, and
  `tests/integration/`. You may also fix thin wiring/import glue, but if a
  module's behavior is wrong, prefer adjusting your wiring over editing that
  module — flag genuine module bugs in your final summary instead.
- **Alert/paper-only**: the orchestrator scans, scores, detects, persists, and
  alerts. It must never place orders or connect a brokerage for execution.

## What to build
1. `services/signal_service.py`: the core pipeline for one scan tick —
   regime → sector rank → stock rank → run the setup registry on ranked
   candidates only → select contract + attach management plan → dedupe →
   persist signal → dispatch alert. Enforce the design rules: no alert without
   regime context; nothing fires on movement alone; reject illiquid contracts;
   every signal carries reason codes + a human rationale and is replayable.
2. `services/follow_up_service.py`: for open signals, evaluate management
   transitions (from `risk/trade_management`) and emit follow-up alerts +
   `signal_event` rows (entry, trim, breakeven, runner exit, expiry-risk, roll).
3. `services/scheduler.py`: a daily premarket scan and intraday 1m/5m monitoring
   loop over the ranked watchlist only (spec Prompt 6 / MVP Phase 2). Config-
   driven cadence; clean logging.
4. `services/backfill.py`: pull and store historical candles for the universe via
   the data provider + storage repository (for replay/backtest later).
5. `app.py`: a CLI entrypoint with subcommands — `scan-once`, `run` (scheduler),
   `backfill`, `regime`, `rank` — selecting provider (mock|polygon) and alert
   sink (console|telegram) from config/env. Default to **mock provider + console
   sink** so it runs with zero credentials.

## Tests (`tests/integration/`)
A full end-to-end run on the **mock provider + console sink + temp SQLite**:
assert that a scan produces ≥1 persisted signal with a contract + management plan
+ reason codes for the bullish fixture, that follow-up transitions emit events on
a simulated price path, and that no signal is produced when the regime fixture is
`no_trade`.

## Done criteria
`pytest` passes for the whole repo; `ruff`/`mypy` clean. `python -m trading_engine
scan-once` (or the equivalent CLI) runs end-to-end on mock data and prints
formatted alerts to the console. Update `docs/strategy_spec.md` with run
instructions. Commit, then merge to `main`. In your summary, list any module bugs
you had to work around and the exact env vars needed to go live (Polygon +
Telegram).
