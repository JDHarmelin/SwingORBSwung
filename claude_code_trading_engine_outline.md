# Claude Code Outline: Systematic Momentum Options Engine

This outline turns the discretionary strategy in the trade log into a build-ready spec for Claude Code. The strategy repeatedly emphasizes breakout and retest entries, relative strength and weakness versus the market, sector leadership, 8 EMA continuation, wedge and flag breaks, market-index context, and trim-to-breakeven management.[file:1]

## Objective

Build a live engine that:
- Scans the market for long and short candidates.
- Filters candidates by market regime, sector strength, and technical structure.
- Detects specific setups in real time.
- Sends Telegram alerts with ticker, direction, trigger, stop, targets, contract suggestion, and reason.
- Tracks open alerts and pushes follow-up management alerts.

## Core strategy abstraction

The trade log implies a three-layer decision model rather than random ticker selection:[file:1]

1. Market regime first — many notes reference SPY, QQQ, gap fills, weakness/strength relative to market, and index-driven intraday direction.[file:1]
2. Sector/theme second — the log repeatedly calls out defense, retail, semis, healthcare, energy, China, real estate, BTC sympathy, and utilities as reasons for selection.[file:1]
3. Stock structure third — entries come from breakouts, retests, wedges, flags, compression, inside days, and EMA continuation.[file:1]

## System modules

### 1. Data layer

Build adapters for:
- Equity OHLCV: 1m, 5m, 15m, 30m, daily.
- Index OHLCV: SPY, QQQ, IWM, VIX, sector ETFs.
- Options chain snapshots: bid/ask, IV, delta, gamma, OI, volume.
- Corporate events: earnings date, ex-dividend date.
- Optional: unusual options flow and news/catalyst feeds.

### 2. Universe builder

Maintain a tradable universe with:
- S&P 500 and Nasdaq 100 core names.
- High-beta momentum names.
- Sector/theme leaders.
- Optional watchlist overrides.

Minimum liquidity rules:
- Stock price above configurable threshold.
- Average daily dollar volume above threshold.
- Options open interest and spread quality above threshold.

### 3. Market regime engine

Determine whether the environment is:
- Long-bias.
- Short-bias.
- Mixed / tactical only.
- No-trade / event risk.

Inputs:
- SPY and QQQ above/below VWAP intraday.
- Daily trend versus 8 EMA, 20 EMA, 50 EMA.
- Breadth measures.
- Sector participation.
- Event filter for CPI, FOMC, mega-cap earnings.

Suggested outputs:
```json
{
  "timestamp": "2026-05-20T12:45:00-04:00",
  "regime": "long_bias",
  "confidence": 0.78,
  "notes": ["QQQ above VWAP", "SMH leading", "breadth positive"]
}
```

### 4. Sector and theme ranking engine

Rank sectors and themes using:
- Relative performance vs SPY over 1d, 5d, 20d.
- Intraday performance vs SPY/QQQ.
- Breadth within sector.
- Volume expansion.
- Trend quality.

This mirrors trade notes like “defense sector strong,” “retail strength,” “energy breakout play,” and “BTC new ATHs, played as sympathy.”[file:1]

### 5. Stock ranking engine

Generate long and short candidate lists using a composite score.

Suggested factor model:
```text
Composite Score =
0.30 * RelativeStrength
+ 0.20 * SectorStrength
+ 0.20 * StructureScore
+ 0.15 * TrendScore
+ 0.10 * VolumeExpansionScore
+ 0.05 * CatalystScore
```

Definitions:
- RelativeStrength: stock return vs SPY/QQQ over multiple lookbacks.
- SectorStrength: sector ETF strength and internal breadth.
- StructureScore: compression, inside-day setup, clean range, breakout proximity.
- TrendScore: EMA alignment and slope.
- VolumeExpansionScore: current or recent volume vs average.
- CatalystScore: earnings, news, or flow.

Outputs:
- Top 20 long candidates.
- Top 20 short candidates.
- Reason codes for each ranking.

### 6. Setup detection engine

Create modular setup detectors instead of one giant strategy.

#### Setup A: Breakout continuation
Conditions:
- Stock in top ranked long bucket.
- Price breaks prior day high, weekly pivot, or defined resistance.
- Volume above threshold.
- Relative strength positive.

#### Setup B: Breakout retest
Conditions:
- Prior breakout level identified.
- Price retests and holds above level.
- Reclaim candle closes back above trigger.
- Market regime not hostile.

This fits repeated notes like “breakout retest play,” “retest of breakout,” and “previous breakout level retest.”[file:1]

#### Setup C: 8 EMA continuation
Conditions:
- Strong uptrend on daily or intraday timeframe.
- Pullback to 8 EMA or 20 EMA.
- Hold and reclaim of microstructure.
- Momentum resumes with volume.

This fits notes such as “inside day nestled into the 8ema,” “over extension from 8 EMA,” and “EMA curl and breakout.”[file:1]

#### Setup D: Compression / wedge / flag break
Conditions:
- Range contraction.
- Higher lows or tight closes.
- Break of trendline or local highs/lows.
- Expansion candle with confirming volume.

This fits notes like “flag breakout,” “wedge breakout,” “large compression,” and “pennant breakout.”[file:1]

#### Setup E: Relative weakness breakdown
Conditions:
- Stock underperforming market and sector.
- Loss of key support or pivot.
- Failed reclaim or supply retest.
- Put setup only if regime allows shorts.

This fits notes such as “weakness relative to market,” “bearish breakdown,” and “under important pivot.”[file:1]

#### Setup F: Index tactical setup
Conditions:
- SPY/QQQ/SPX specific levels.
- ORB, reclaim, gap-fill, low sweep, high sweep.
- Used for day-trade alerts only.

This reflects many log entries tied to SPY, QQQ, SPX reclaim and gap-fill plays.[file:1]

### 7. Contract selection engine

For each valid stock signal, generate an options suggestion.

Rules:
- Swing trades: 14 to 45 DTE preferred.
- Day trades: same week or next week only if liquidity is strong.
- Delta target: 0.30 to 0.45 for standard alerts.
- Lotto alerts: explicitly flagged, smaller size, higher risk.
- Reject spreads wider than configured threshold.
- Reject low OI / low volume contracts.

Example output:
```json
{
  "ticker": "NVDA",
  "direction": "long_call",
  "expiry": "2026-06-19",
  "strike": 132,
  "delta": 0.39,
  "bid_ask_spread_pct": 4.8,
  "classification": "standard_swing"
}
```

### 8. Risk engine

Convert the discretionary management style into fixed rules. The log repeatedly mentions trimming into strength, moving stop to breakeven, and letting runners continue.[file:1]

Base management template:
- Initial stop based on structure, not arbitrary premium decay alone.
- Trim 1: +25% to +35% option gain.
- Move stop to breakeven after first trim.
- Trim 2: +50% to +75% option gain.
- Runner: trail below 8 EMA, prior candle low, or VWAP depending on setup.
- Forced exit before major binary event unless flagged as catalyst trade.

Risk classification:
- A+ setup.
- Standard setup.
- Lotto setup.
- Hedge setup.

### 9. Alerting engine

Send Telegram alerts only when a setup passes all filters.

Required alert fields:
- Ticker.
- Direction.
- Setup type.
- Why selected.
- Trigger price.
- Invalidation / stop.
- Suggested contract.
- Target management plan.
- Confidence score.
- Timestamp.

Suggested Telegram format:
```text
SETUP: Breakout Retest
TICKER: NVDA
BIAS: Long
WHY: SMH leading, NVDA RS vs QQQ positive, prior breakout retest holding
ENTRY: Above 132.40
STOP: Below 130.95
CONTRACT: 2026-06-19 135C, ~0.38 delta
TARGETS: Trim 1 +30%, trim 2 +60%, runner trail 8 EMA
CONFIDENCE: 81/100
```

### 10. Position follow-up engine

After an alert fires, continue monitoring and send:
- Entry triggered.
- Stop hit.
- First trim reached.
- Stop moved to breakeven.
- Runner exit.
- Expiry risk warning.
- Roll candidate alert.

This matches the repeated use of rollovers and active management in the log.[file:1]

## Database outline

Suggested tables:

### `candles`
- symbol
- timeframe
- timestamp
- open
- high
- low
- close
- volume

### `market_regime`
- timestamp
- regime
- confidence
- notes_json

### `sector_scores`
- timestamp
- sector
- rs_1d
- rs_5d
- rs_20d
- breadth_score
- composite_score

### `symbol_scores`
- timestamp
- symbol
- direction_bucket
- rs_score
- sector_score
- structure_score
- trend_score
- volume_score
- catalyst_score
- composite_score
- reason_codes_json

### `signals`
- signal_id
- timestamp
- symbol
- setup_type
- direction
- trigger_price
- stop_price
- target_plan_json
- contract_json
- rationale_text
- confidence
- status

### `signal_events`
- signal_id
- event_timestamp
- event_type
- event_payload_json

## Project structure for Claude Code

```text
trading-engine/
  config/
    settings.yaml
    universe.yaml
  src/
    data/
      market_data.py
      options_data.py
      events.py
    features/
      indicators.py
      relative_strength.py
      compression.py
      trend.py
      sector_rank.py
    scanners/
      universe_builder.py
      market_regime.py
      stock_ranker.py
    setups/
      breakout_continuation.py
      breakout_retest.py
      ema_continuation.py
      compression_break.py
      relative_weakness.py
      index_tactical.py
    risk/
      position_sizing.py
      contract_selector.py
      trade_management.py
    alerts/
      telegram.py
      formatter.py
    storage/
      models.py
      repository.py
    services/
      signal_service.py
      scheduler.py
      backfill.py
    app.py
  tests/
  docs/
    strategy_spec.md
```

## Claude Code implementation prompts

### Prompt 1: Build the data foundation
```text
Build a Python market data layer for a systematic momentum options engine.
Requirements:
- Modular adapters for equities, ETFs, indices, and options chains.
- Standardized schema for OHLCV and options snapshots.
- Async-friendly design.
- Clear interfaces so data providers can be swapped later.
- Include unit tests.
```

### Prompt 2: Build the ranking engine
```text
Build a stock and sector ranking engine in Python.
Requirements:
- Compute relative strength vs SPY and QQQ over multiple windows.
- Compute sector strength and breadth.
- Compute composite symbol score.
- Return top long and short candidates with reason codes.
- Use pandas and clean typed functions.
- Include test fixtures and example output.
```

### Prompt 3: Build setup modules
```text
Implement setup detectors as modular Python classes.
Required setups:
- Breakout continuation
- Breakout retest
- 8 EMA continuation
- Compression/wedge/flag break
- Relative weakness breakdown
- Index tactical breakout/reclaim
Each setup must expose:
- detect(context) -> list[Signal]
- explanation string
- trigger, stop, target template
Include unit tests with synthetic candles.
```

### Prompt 4: Build options selector and risk engine
```text
Create a contract selection and risk engine for options alerts.
Requirements:
- Suggest expiry, strike, and delta target.
- Reject illiquid chains.
- Classify signals as standard, lotto, or hedge.
- Implement trim-to-breakeven management rules.
- Output structured JSON ready for Telegram formatting.
```

### Prompt 5: Build Telegram alert service
```text
Build a Telegram bot service for a trading signal engine.
Requirements:
- Format messages with setup, ticker, why, entry, stop, targets, contract, confidence.
- Deduplicate repeated alerts.
- Support trigger alerts and follow-up management alerts.
- Read credentials from environment variables.
- Include retry logic and logging.
```

### Prompt 6: Build orchestration
```text
Build the orchestration layer for the trading engine.
Requirements:
- Daily premarket scan.
- Intraday 1m/5m monitoring on ranked candidates only.
- Signal persistence to database.
- Telegram dispatch.
- Simple CLI entrypoint and scheduler.
- Clean logs and config-driven behavior.
```

## MVP roadmap

### Phase 1
- Daily market regime.
- Sector ranker.
- Top 20 long/short watchlist.
- No Telegram yet.

### Phase 2
- Real-time signal detection on top watchlist.
- Telegram alerts.
- Basic contract suggestion.

### Phase 3
- Trade management alerts.
- Roll suggestions.
- Dashboard.

### Phase 4
- Backtesting and replay engine.
- Strategy stats by setup type.
- Machine-learning assisted ranking if needed.

## Non-negotiable design rules

- Never alert without market-regime context.
- Never alert a stock just because it is “moving”; it must also pass sector and structure filters.
- Never suggest contracts with bad liquidity.
- Keep setup modules separate and testable.
- Every signal must include a machine-readable reason code list and a human-readable explanation.
- Every signal must be replayable later from stored candles and metadata.

## What success looks like

A successful engine should produce a daily shortlist of names that are already aligned with the same logic seen repeatedly in the trade log: strong or weak sectors, relative strength or weakness versus the market, clean technical structure, and disciplined management after entry.[file:1]

The final product is not “an auto trader.” It is a live discretionary assistant that narrows the market to high-quality candidates, explains why they matter, and gives a clear execution plan through Telegram alerts.[file:1]
