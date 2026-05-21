# SwingORSwung — Systematic Momentum Options ALERT Engine

## NON-NEGOTIABLE (read first)
- This is an ALERT / PAPER-ONLY research tool. NEVER add order execution, money
  movement, or brokerage connectivity (no `submit_order`, `place_order`, broker
  SDKs like `alpaca`/`ib_insync`/`tradier` *trading* endpoints, etc.).
- NEVER frame output as financial advice or as profitable. Every output is
  research only.

## Commands
- Setup:  `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Test:   `.venv/bin/python -m pytest --tb=short -q`  (prefer single tests while iterating)
- Lint:   `ruff check . && ruff format --check .`
- Types:  `mypy trading_engine`  (strict mode — keep it green)
- Run (mock, no keys):  `python -m trading_engine scan-once`
- Run (live):           `python -m trading_engine scan-once --provider polygon --alerts telegram`

## Architecture (3 sentences)
- Decision model is regime → sector → structure; six setup detectors (A–F) live in `setups/`.
- `core/` holds shared types + Protocol interfaces; every module builds against those contracts.
- Data layer is provider-agnostic: `mock` (dev, no keys) | `polygon` (reference live feed);
  Tradier/ThetaData are documented drop-ins.

## Conventions
- Python 3.11, ruff (line-length 100), mypy `--strict`, pydantic models.
- Built in parallel WAVES (see `prompts/`): Wave 0 foundation → Waves 1–2 parallel
  modules with **disjoint file ownership** → Wave 3 orchestration. Do not edit files
  outside the wave/module you are assigned.
- Default CLI = mock provider + console sink. Never commit real keys; use `.env`.

## Gotchas
- `asyncio_mode = auto` in pytest; provider interfaces are async.
- Synthetic fixtures live in `trading_engine/testing/synthetic.py` (importable);
  the sample option chain includes a deliberately illiquid contract for §7 rejection tests.
