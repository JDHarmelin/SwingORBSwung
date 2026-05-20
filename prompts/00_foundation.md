# Wave 0 — Foundation (run ALONE, before anything else)

You are building the shared foundation for a **Systematic Momentum Options
Engine**. The full spec is in `claude_code_trading_engine_outline.md` at the repo
root — read it first. This prompt builds ONLY the shared contracts that every
other module depends on. Do not implement strategy logic, data providers,
scanners, or alerts here.

## Critical constraints
- This is an **alert/paper-only research tool**. It must never place orders, move
  money, or connect to a brokerage for execution. Do not add any execution code.
- Nothing produced is financial advice; treat all output as research.
- Python 3.11+. Use standard, well-maintained libraries only.

## Set up the project
1. `git init` the repo (root is the current directory).
2. Create a `pyproject.toml` for an installable package named `trading_engine`
   with dependencies: `pydantic`, `pandas`, `numpy`, `pyyaml`, `httpx`,
   `sqlalchemy`, `python-telegram-bot`, and dev deps `pytest`, `pytest-asyncio`,
   `ruff`, `mypy`. Configure ruff + mypy + pytest.
3. Create the package skeleton with empty `__init__.py` files so the layout in
   the spec's "Project structure" section exists:
   `trading_engine/{core,data,features,scanners,setups,risk,alerts,storage,services}`,
   plus `config/`, `tests/`, `tests/fixtures/`, `docs/`.
4. Add a `.gitignore` (Python, venv, `.env`, db files) and a `.env.example`
   listing the env vars the system will need (data provider key, Telegram token +
   chat id, db url).

## Build `trading_engine/core/types.py`
Define typed models (pydantic `BaseModel` or frozen dataclasses) and enums used
across the whole system. At minimum:
- Enums: `Timeframe` (1m,5m,15m,30m,1d), `Direction` (long/short),
  `RegimeType` (long_bias, short_bias, mixed, no_trade), `SetupType` (the six
  setups A–F from spec §6), `RiskClass` (a_plus, standard, lotto, hedge),
  `SignalStatus` (pending, triggered, stopped, trimmed, closed, expired_risk).
- `Candle` (symbol, timeframe, timestamp, ohlcv) and a lightweight
  `OHLCVSeries` wrapper that can convert to/from a pandas DataFrame.
- `OptionContract` (ticker, underlying, expiry, strike, type, bid, ask, iv,
  delta, gamma, theta, vega, open_interest, volume) and `OptionChain`.
- `MarketRegime`, `SectorScore`, `SymbolScore` (with the factor sub-scores from
  spec §5 and a `reason_codes: list[str]`), `Signal` (matching the `signals`
  table in the DB outline, incl. `target_plan`, `contract`, `rationale`,
  `confidence`, `status`) and `SignalEvent`.
- A `ContractSuggestion` model matching the JSON example in spec §7.
Make every model JSON-serializable (this is required by the spec's "replayable"
rule).

## Build `trading_engine/core/interfaces.py`
Define `typing.Protocol` (or ABCs) — interfaces only, NO implementations:
- `MarketDataProvider`: async methods to fetch OHLCV for a symbol/timeframe/range
  and latest quote; cover equities, ETFs, indices.
- `OptionsDataProvider`: async method to fetch an `OptionChain` snapshot for an
  underlying (bid/ask, IV, greeks, OI, volume).
- `EventsProvider`: earnings date + ex-dividend date for a symbol.
- `AlertSink`: send a formatted alert; idempotent/dedupe-aware signature.
- `Repository`: persist/query candles, regimes, scores, signals, signal_events
  (mirrors the DB outline tables).
These protocols are the seams that let other waves build in parallel.

## Build `trading_engine/core/config.py`
A loader that reads `config/settings.yaml` + `config/universe.yaml` into typed
config objects, with env-var overrides for secrets. Create starter
`config/settings.yaml` (liquidity thresholds, factor weights from spec §5,
risk/trim levels from spec §8, DTE + delta targets from spec §7, regime event
filter) and `config/universe.yaml` (a small starter list of S&P/Nasdaq names +
sector ETF map: XLK, XLE, XLF, XLV, SMH, XLI, ITA, XRT, etc.).

## Build shared test fixtures in `tests/fixtures/`
Other waves test against these, so make them realistic and reusable:
- Synthetic `OHLCVSeries` generators / saved CSVs for: a clean uptrend, a
  pullback-to-8EMA, a compression/flag then breakout, a breakdown, and a choppy
  no-trade tape. Provide both daily and intraday (5m) versions.
- A sample `OptionChain` (multiple strikes/expiries with greeks, plus one
  illiquid contract that should be rejected by §7 rules).
- A sample universe + sample sector ETF series.
Expose them via `pytest` fixtures in `tests/conftest.py` and as importable
helpers so non-test code in later waves can also load samples.

## Build the mock data adapter stub location
Create `trading_engine/data/mock_provider.py` with a `MockMarketDataProvider`,
`MockOptionsDataProvider`, and `MockEventsProvider` that implement the interfaces
by serving the fixtures above. (Wave 1 will add the real Polygon adapter; keep
the mock here so every other wave can run today without API keys.)

## Done criteria
- `pip install -e .` works; `pytest` runs (fixtures + a smoke test importing all
  core modules pass); `ruff` and `mypy` are clean on `core/`.
- Add a short `docs/strategy_spec.md` that points to the outline and records the
  package layout + the alert/paper-only rule.
- Commit everything to `main` with a clear message. Do NOT create the other
  modules' code — only the skeleton dirs/`__init__.py` for them.
