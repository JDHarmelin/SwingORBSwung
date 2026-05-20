# Wave 1 — Alerts (parallel; owns `trading_engine/alerts/`)

Build the alerting layer for the Systematic Momentum Options Engine. Read
`claude_code_trading_engine_outline.md` §9 (Alerting) and §10 (Position
follow-up). **Wave 0 is done and committed** — shared types and the `AlertSink`
interface exist. Do not modify them.

## Constraints
- Only create/edit files in `trading_engine/alerts/` and tests in
  `tests/alerts/`. Do not touch `core/` or other modules.
- Implement the `AlertSink` protocol from `trading_engine.core.interfaces`.
  Consume `Signal` / `SignalEvent` / `ContractSuggestion` from
  `trading_engine.core.types`.
- Alert/paper-only tool: alerts are informational research output, never trade
  instructions. Do not add anything that places orders.

## What to build
1. `formatter.py`: render a `Signal` into the exact Telegram message shape in
   spec §9 — SETUP, TICKER, BIAS, WHY (from reason codes), ENTRY (trigger),
   STOP (invalidation), CONTRACT (from the suggestion), TARGETS (trim/runner
   plan from §8), CONFIDENCE, timestamp. Also render the follow-up event
   messages from §10 (entry triggered, stop hit, trim 1, moved to breakeven,
   runner exit, expiry-risk warning, roll candidate). Keep formatting in pure,
   testable functions separate from network code.
2. `telegram.py`: a `TelegramAlertSink(AlertSink)` using `python-telegram-bot`.
   Read `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` from env. Retry with backoff,
   structured logging.
3. `dedupe.py`: suppress duplicate alerts for the same signal/state within a
   configurable window (spec §9 "deduplicate repeated alerts"); the orchestrator
   will reuse this. Make it injectable/testable (no real clock dependency).
4. A `ConsoleAlertSink` for local/dev runs without Telegram creds.

## Tests (`tests/alerts/`)
- Snapshot-test the formatter output for a sample `Signal` and for each follow-up
  event type (build inputs from Wave 0 fixtures / sample contract).
- Test dedupe: same signal+state suppressed, new state passes, window expiry
  works.
- Test the Telegram sink with a mocked HTTP/transport — no real network or token.

## Done criteria
`pytest tests/alerts` passes offline; `ruff`/`mypy` clean on `alerts/`. Commit on
your branch. End with the env vars needed for live Telegram.
