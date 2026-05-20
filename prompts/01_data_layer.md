# Wave 1 — Data layer (parallel; owns `trading_engine/data/`)

Build the real market-data adapters for the Systematic Momentum Options Engine.
Read `claude_code_trading_engine_outline.md` §1 (Data layer) and §2 (Universe
builder) for context. **Wave 0 is already done and committed** — the shared
types, interfaces, config loader, and fixtures exist. Do not modify them.

## Constraints
- You may ONLY create/edit files inside `trading_engine/data/` and add tests
  inside `tests/data/`. Do not touch `core/`, other modules, or shared fixtures.
- Implement the `MarketDataProvider`, `OptionsDataProvider`, and `EventsProvider`
  protocols from `trading_engine.core.interfaces`. Import types from
  `trading_engine.core.types`. A `mock_provider.py` already exists from Wave 0 —
  do not duplicate it; build the real adapters alongside it.
- Alert/paper-only project: this is read-only market data. Never add order or
  account-mutation calls.

## What to build
1. **Polygon adapter** (`polygon_provider.py`): implement all three interfaces
   against Polygon.io REST (aggregates for OHLCV at every `Timeframe`, option
   chain snapshot with bid/ask/IV/greeks/OI/volume, and corporate events for
   earnings/ex-div). Async via `httpx`. Read the API key from env
   (`POLYGON_API_KEY`). Normalize all responses into the shared `Candle` /
   `OptionChain` / event models — callers must not see Polygon-specific shapes.
2. **Provider factory** (`factory.py`): select the provider from config/env
   (`mock` | `polygon`), so the rest of the system depends only on the
   interface. Document how to add Tradier/ThetaData later (interface is the same).
3. **Resilience**: rate-limit handling, retry with backoff, timeouts, and a thin
   on-disk cache for OHLCV pulls so backfills don't re-hit the API. Clear logging.
4. **Universe builder** (`universe.py`): load the universe from
   `config/universe.yaml`, apply the liquidity rules from spec §2 (min price, min
   avg dollar volume, options OI/spread quality) using the data provider, and
   return the tradable universe + sector→ETF map. Support watchlist overrides.

## Tests (`tests/data/`)
- Use the **mock provider + Wave 0 fixtures** for logic tests (no network).
- For the Polygon adapter, test the response-normalization layer against saved
  sample JSON payloads (record a couple of representative payloads as test
  assets) — do NOT make live network calls in tests.
- Test universe filtering: names below thresholds are excluded; overrides work.

## Done criteria
`pytest tests/data` passes offline; `ruff`/`mypy` clean on `data/`. Commit on
your branch. End with a one-paragraph note on which env vars must be set to use
the live Polygon feed.
