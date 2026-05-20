# Wave 2 — Risk + contract selection (parallel; owns `trading_engine/risk/`)

Build the contract-selection and risk/management engine for the Systematic
Momentum Options Engine. Read `claude_code_trading_engine_outline.md` §7
(Contract selection) and §8 (Risk engine). **Waves 0 and 1 are done and
committed** — shared types/interfaces and the data adapters (incl. mock options
provider) exist. Do not modify them.

## Constraints
- Only create/edit files in `trading_engine/risk/` and tests in `tests/risk/`.
  Do not touch `core/`, `data/`, `setups/`, etc.
- Consume an `OptionChain` via the `OptionsDataProvider` **interface** (tests use
  the mock chain fixture). Read DTE/delta/spread/risk params from config (Wave 0).
- **Alert/paper-only**: this engine sizes and *suggests*; it never sends orders.
  "Position sizing" produces a suggested risk allocation only.

## What to build
1. `contract_selector.py`: given a `Signal` + an `OptionChain`, pick a contract
   per spec §7 — swing 14–45 DTE / day-trade same-or-next week, target delta
   0.30–0.45 (standard), reject spreads wider than the configured threshold,
   reject low OI/volume. Return a `ContractSuggestion` (matching the §7 JSON:
   ticker, direction, expiry, strike, delta, bid_ask_spread_pct,
   classification). Flag lotto vs standard vs hedge.
2. `trade_management.py`: turn the discretionary style in §8 into a fixed,
   data-driven plan attached to each signal — structure-based initial stop,
   Trim 1 at +25–35%, move stop to breakeven after Trim 1, Trim 2 at +50–75%,
   runner trailing rule (8 EMA / prior candle low / VWAP by setup), and forced
   exit before a binary event unless flagged catalyst. Expose a function that,
   given a live signal + current candles/quote, emits the next management
   `SignalEvent` (trim reached, stop hit, move-to-BE, runner exit, expiry-risk,
   roll candidate) — consumed later by the orchestrator + alerts.
3. `risk_class.py`: classify a signal as A+ / standard / lotto / hedge from setup
   quality + confidence + liquidity (spec §8).
4. `position_sizing.py`: suggested allocation given account-risk config and the
   structural stop distance. Suggestion only.

## Tests (`tests/risk/`)
Use the Wave 0 sample option chain (which includes an illiquid contract). Assert:
the illiquid/wide-spread contract is rejected; a 0.30–0.45 delta strike is chosen
for a standard swing; DTE windows respected; trim/breakeven/runner transitions
fire at the right thresholds on a simulated price path; lotto correctly flagged.

## Done criteria
`pytest tests/risk` passes offline; `ruff`/`mypy` clean on `risk/`. Commit on
your branch.
