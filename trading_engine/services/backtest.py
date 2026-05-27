"""Lightweight backtest / replay harness.

Walks historical daily OHLCV bar-by-bar, runs the production
scanner→setup→signal pipeline at each ``as_of``, coalesces the resulting
candidates with the same logic the alert path uses, and records forward
outcomes (MFE/MAE, time-to-T1/stop, R-multiples at +1/+3/+5 bars) per
*coalesced* signal — exactly one row per alert, not per raw signal.

Reuse, not reinvention:
- The full ``SignalService.run_pipeline`` is invoked, so detectors, ranker,
  regime engine, and risk profile attachment all behave identically to live.
- Coalescing uses ``alerts.formatter.coalesce_signals`` — the same call the
  ``confirm_and_alert`` path makes.
- Outcomes use the existing R-multiple semantics from
  ``services.paper_tracker`` (entry, stop, RR), extended with the
  excursions/horizon metrics calibration needs.

The harness is intentionally additive: it does not touch the signal service,
alert formatter, or contract selector code paths.
"""

from __future__ import annotations

import csv
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from trading_engine.alerts.formatter import coalesce_signals
from trading_engine.alerts.sinks import InMemoryAlertSink
from trading_engine.core.config import Settings, Universe
from trading_engine.core.interfaces import (
    EventsProvider,
    MarketDataProvider,
    OptionsDataProvider,
)
from trading_engine.core.types import (
    Candle,
    Direction,
    OHLCVSeries,
    Signal,
    Timeframe,
)
from trading_engine.data.mock_provider import (
    MockEventsProvider,
    MockMarketDataProvider,
    MockOptionsDataProvider,
)
from trading_engine.services.signal_service import SignalService
from trading_engine.storage import InMemoryRepository

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class BacktestOutcome:
    """One row per coalesced alert."""

    symbol: str
    bar_ts: datetime
    primary_setup: str
    direction: str
    confidence: float
    confidence_components: dict[str, float]
    risk_profile: dict[str, float | str]
    entry: float
    stop: float
    target: float
    mfe: float  # max favorable excursion in price units
    mae: float  # max adverse excursion in price units
    hit_t1_at: int | None  # bar index (1-based) when target hit, else None
    hit_stop_at: int | None
    r_at_h1: float
    r_at_h3: float
    r_at_h5: float
    bars_observed: int
    outcome: str  # 'win' | 'loss' | 'open'
    companions: list[str] = field(default_factory=list)


@dataclass
class BacktestSummary:
    run_id: str
    total_signals: int
    wins: int
    losses: int
    opens: int
    win_rate: float
    avg_r: float
    by_setup: dict[str, dict[str, float]]
    by_confidence_decile: dict[str, dict[str, float]]


# ---------------------------------------------------------------------------
# Windowing provider
# ---------------------------------------------------------------------------


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class _WindowedMarketDataProvider:
    """Wraps an inner provider, but for any symbol with a full historical
    series in ``history`` returns only bars with ``timestamp <= cutoff``.

    The cutoff is mutated between bars by the Backtester (rebound rather than
    re-instantiated so the same SignalService can be reused across days).
    """

    def __init__(
        self,
        inner: MarketDataProvider,
        history: dict[str, OHLCVSeries],
    ) -> None:
        self._inner = inner
        self._history = history
        self.cutoff: datetime = datetime.now(tz=UTC)

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> OHLCVSeries:
        series = self._history.get(symbol)
        if series is None or timeframe is not Timeframe.D1:
            # Fall back to the inner (mock) provider for intraday + unknown.
            return await self._inner.get_ohlcv(symbol, timeframe, start, end)
        s, e = _aware(start), _aware(min(end, self.cutoff))
        candles = [c for c in series.candles if s <= _aware(c.timestamp) <= e]
        return OHLCVSeries(symbol=symbol, timeframe=timeframe, candles=candles)

    async def get_latest_quote(self, symbol: str) -> Candle:
        series = self._history.get(symbol)
        if series is None:
            return await self._inner.get_latest_quote(symbol)
        candles = [c for c in series.candles if _aware(c.timestamp) <= self.cutoff]
        return candles[-1] if candles else series.candles[0]


# ---------------------------------------------------------------------------
# Forward outcome simulation
# ---------------------------------------------------------------------------


def _forward_bars(
    series: OHLCVSeries, after: datetime, horizon: int
) -> list[Candle]:
    return [c for c in series.candles if _aware(c.timestamp) > _aware(after)][:horizon]


def _simulate_forward(
    signal: Signal,
    forward: list[Candle],
    *,
    rr: float,
) -> dict[str, Any]:
    """Compute MFE/MAE, time-to-T1/stop, R at +1/+3/+5 bars.

    Conservative within-bar ordering: stop checked before target. Entry is
    assumed to be filled on the *first* forward bar (this is a momentum signal
    fired at a level break; we account for trigger crossing implicitly by
    starting from the bar after the signal timestamp).
    """
    is_long = signal.direction is Direction.LONG
    entry = float(signal.trigger_price)
    stop = float(signal.stop_price)
    risk = abs(entry - stop)
    target = entry + rr * risk if is_long else entry - rr * risk

    mfe = 0.0
    mae = 0.0
    hit_t1_at: int | None = None
    hit_stop_at: int | None = None
    r_by_bar: dict[int, float] = {}
    outcome = "open"

    for idx, c in enumerate(forward, start=1):
        if risk > 0:
            if is_long:
                fav = (c.high - entry)
                adv = (entry - c.low)
            else:
                fav = (entry - c.low)
                adv = (c.high - entry)
            if fav > mfe:
                mfe = fav
            if adv > mae:
                mae = adv

            if hit_stop_at is None and hit_t1_at is None:
                hit_stop = (c.low <= stop) if is_long else (c.high >= stop)
                hit_tgt = (c.high >= target) if is_long else (c.low <= target)
                # Conservative ordering: stop first within the bar.
                if hit_stop:
                    hit_stop_at = idx
                    outcome = "loss"
                elif hit_tgt:
                    hit_t1_at = idx
                    outcome = "win"

            # Mark-to-market R using the bar close.
            close_move = (c.close - entry) if is_long else (entry - c.close)
            r_by_bar[idx] = (close_move / risk) if risk > 0 else 0.0

        if hit_t1_at is not None or hit_stop_at is not None:
            # Lock in terminal R at the resolving bar for downstream horizons.
            for h in (1, 3, 5):
                if h >= idx and h not in r_by_bar:
                    r_by_bar[h] = rr if outcome == "win" else -1.0
            break

    def r_at(h: int) -> float:
        if h in r_by_bar:
            return round(r_by_bar[h], 4)
        if not r_by_bar:
            return 0.0
        # If horizon exceeded the data we have, use the last available bar.
        last = max(k for k in r_by_bar if k <= h) if any(k <= h for k in r_by_bar) else 0
        return round(r_by_bar.get(last, 0.0), 4) if last else 0.0

    return {
        "mfe": round(mfe, 4),
        "mae": round(mae, 4),
        "target": round(target, 4),
        "hit_t1_at": hit_t1_at,
        "hit_stop_at": hit_stop_at,
        "r_at_h1": r_at(1),
        "r_at_h3": r_at(3),
        "r_at_h5": r_at(5),
        "bars_observed": len(forward),
        "outcome": outcome,
    }


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------


class Backtester:
    """Drive the production pipeline bar-by-bar over historical daily data."""

    def __init__(
        self,
        *,
        settings: Settings,
        universe: Universe,
        history: dict[str, OHLCVSeries],
        options_data: OptionsDataProvider | None = None,
        events: EventsProvider | None = None,
        inner_market: MarketDataProvider | None = None,
        horizon_bars: int = 5,
    ) -> None:
        self.settings = settings
        self.universe = universe
        self.history = history
        self.horizon_bars = horizon_bars
        self.options_data = options_data or MockOptionsDataProvider()
        self.events = events or MockEventsProvider()
        self._inner_market = inner_market or MockMarketDataProvider()
        self._windowed = _WindowedMarketDataProvider(self._inner_market, history)
        self._repo = InMemoryRepository()
        self._sink = InMemoryAlertSink()
        self._service = SignalService(
            settings=settings,
            universe=universe,
            market_data=self._windowed,
            options_data=self.options_data,
            events=self.events,
            repo=self._repo,
            alerts=self._sink,
        )

    # ------------------------------------------------------------------
    def _trading_days(
        self, symbols: list[str], start: date, end: date
    ) -> list[datetime]:
        """Union of all bar timestamps in [start, end] across requested symbols."""
        seen: dict[datetime, None] = {}
        for sym in symbols:
            series = self.history.get(sym)
            if not series:
                continue
            for c in series.candles:
                ts = _aware(c.timestamp)
                if start <= ts.date() <= end:
                    seen.setdefault(ts, None)
        return sorted(seen.keys())

    async def run(
        self,
        *,
        symbols: list[str],
        start: date,
        end: date,
    ) -> list[BacktestOutcome]:
        days = self._trading_days(symbols, start, end)
        if not days:
            log.warning("backtest: no bars in range %s..%s for %s", start, end, symbols)
            return []

        outcomes: list[BacktestOutcome] = []
        emitted_ids: set[str] = set()

        for as_of in days:
            self._windowed.cutoff = as_of
            try:
                result = await self._service.run_pipeline(as_of)
            except ValueError as exc:
                # Common case: cached history doesn't reach back far enough
                # for EMA(50) etc. Skip this bar and continue — don't poison
                # the whole run because one date lacks lookback.
                log.debug("backtest: skipping %s (%s)", as_of.isoformat(), exc)
                continue
            if not result.candidates:
                continue

            # Only consider candidates emitted *this bar* (by timestamp) so we
            # don't double-count carry-over PENDINGs from earlier days.
            fresh = [c for c in result.candidates if _aware(c.timestamp) == as_of]
            for primary, companions in coalesce_signals(fresh):
                if primary.signal_id in emitted_ids:
                    continue
                emitted_ids.add(primary.signal_id)

                series = self.history.get(primary.symbol)
                if series is None:
                    continue
                forward = _forward_bars(series, as_of, self.horizon_bars)
                if not forward:
                    continue

                sim = _simulate_forward(
                    primary, forward, rr=self.settings.execution.paper_rr
                )
                outcomes.append(
                    BacktestOutcome(
                        symbol=primary.symbol,
                        bar_ts=as_of,
                        primary_setup=primary.setup_type.value,
                        direction=primary.direction.value,
                        confidence=primary.confidence,
                        confidence_components=dict(primary.confidence_components),
                        risk_profile=dict(primary.risk_profile),
                        entry=float(primary.trigger_price),
                        stop=float(primary.stop_price),
                        target=sim["target"],
                        mfe=sim["mfe"],
                        mae=sim["mae"],
                        hit_t1_at=sim["hit_t1_at"],
                        hit_stop_at=sim["hit_stop_at"],
                        r_at_h1=sim["r_at_h1"],
                        r_at_h3=sim["r_at_h3"],
                        r_at_h5=sim["r_at_h5"],
                        bars_observed=sim["bars_observed"],
                        outcome=sim["outcome"],
                        companions=[c.setup_type.value for c in companions],
                    )
                )
        return outcomes


# ---------------------------------------------------------------------------
# CSV + summary
# ---------------------------------------------------------------------------


_CSV_FIELDS = [
    "symbol",
    "bar_ts",
    "primary_setup",
    "direction",
    "confidence",
    "confidence_components",
    "risk_profile",
    "entry",
    "stop",
    "target",
    "mfe",
    "mae",
    "hit_t1_at",
    "hit_stop_at",
    "r_at_h1",
    "r_at_h3",
    "r_at_h5",
    "bars_observed",
    "outcome",
    "companions",
]


def write_csv(outcomes: list[BacktestOutcome], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        w.writeheader()
        for o in outcomes:
            w.writerow(
                {
                    "symbol": o.symbol,
                    "bar_ts": o.bar_ts.isoformat(),
                    "primary_setup": o.primary_setup,
                    "direction": o.direction,
                    "confidence": o.confidence,
                    "confidence_components": _kv(o.confidence_components),
                    "risk_profile": _kv(o.risk_profile),
                    "entry": o.entry,
                    "stop": o.stop,
                    "target": o.target,
                    "mfe": o.mfe,
                    "mae": o.mae,
                    "hit_t1_at": o.hit_t1_at if o.hit_t1_at is not None else "",
                    "hit_stop_at": o.hit_stop_at if o.hit_stop_at is not None else "",
                    "r_at_h1": o.r_at_h1,
                    "r_at_h3": o.r_at_h3,
                    "r_at_h5": o.r_at_h5,
                    "bars_observed": o.bars_observed,
                    "outcome": o.outcome,
                    "companions": "|".join(o.companions),
                }
            )
    return path


def _kv(d: dict[str, Any]) -> str:
    return ";".join(f"{k}={v}" for k, v in d.items())


def summarize(outcomes: list[BacktestOutcome]) -> BacktestSummary:
    wins = sum(1 for o in outcomes if o.outcome == "win")
    losses = sum(1 for o in outcomes if o.outcome == "loss")
    opens = sum(1 for o in outcomes if o.outcome == "open")
    total = len(outcomes)
    resolved = wins + losses
    win_rate = (wins / resolved) if resolved else 0.0
    # Use r_at_h5 as the "final" R for averaging — terminal R if resolved,
    # mark-to-market otherwise.
    avg_r = (sum(o.r_at_h5 for o in outcomes) / total) if total else 0.0

    by_setup: dict[str, dict[str, float]] = {}
    for o in outcomes:
        b = by_setup.setdefault(
            o.primary_setup, {"n": 0, "wins": 0, "losses": 0, "avg_r": 0.0}
        )
        b["n"] += 1
        if o.outcome == "win":
            b["wins"] += 1
        elif o.outcome == "loss":
            b["losses"] += 1
        b["avg_r"] += o.r_at_h5
    for b in by_setup.values():
        n = b["n"]
        b["win_rate"] = (b["wins"] / (b["wins"] + b["losses"])) if (b["wins"] + b["losses"]) else 0.0
        b["avg_r"] = b["avg_r"] / n if n else 0.0

    # Confidence deciles: 10 buckets, 0.0..1.0
    by_decile: dict[str, dict[str, float]] = {}
    for o in outcomes:
        idx = min(9, max(0, int(o.confidence * 10)))
        key = f"d{idx}"  # d0 = [0.0,0.1), d9 = [0.9,1.0]
        b = by_decile.setdefault(key, {"n": 0, "wins": 0, "losses": 0, "avg_r": 0.0})
        b["n"] += 1
        if o.outcome == "win":
            b["wins"] += 1
        elif o.outcome == "loss":
            b["losses"] += 1
        b["avg_r"] += o.r_at_h5
    for b in by_decile.values():
        n = b["n"]
        b["win_rate"] = (b["wins"] / (b["wins"] + b["losses"])) if (b["wins"] + b["losses"]) else 0.0
        b["avg_r"] = b["avg_r"] / n if n else 0.0

    return BacktestSummary(
        run_id=uuid.uuid4().hex[:8],
        total_signals=total,
        wins=wins,
        losses=losses,
        opens=opens,
        win_rate=round(win_rate, 4),
        avg_r=round(avg_r, 4),
        by_setup={k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in by_setup.items()},
        by_confidence_decile={k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in sorted(by_decile.items())},
    )


def format_summary(summary: BacktestSummary) -> str:
    lines = [
        f"=== Backtest run {summary.run_id} ===",
        f"Total signals: {summary.total_signals}  "
        f"wins={summary.wins}  losses={summary.losses}  open={summary.opens}",
        f"Win rate (resolved): {summary.win_rate * 100:.1f}%   Avg R (h5): {summary.avg_r:+.3f}",
        "",
        "By setup:",
    ]
    for setup, m in summary.by_setup.items():
        lines.append(
            f"  {setup:<28} n={int(m['n']):>3}  win_rate={m['win_rate'] * 100:5.1f}%  "
            f"avg_r={m['avg_r']:+.3f}"
        )
    lines.append("")
    lines.append("By confidence decile:")
    for dk, m in summary.by_confidence_decile.items():
        lines.append(
            f"  {dk}  n={int(m['n']):>3}  win_rate={m['win_rate'] * 100:5.1f}%  "
            f"avg_r={m['avg_r']:+.3f}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cache loading helpers
# ---------------------------------------------------------------------------


def load_history_from_cache(
    symbols: list[str], cache_dir: Path | None = None
) -> dict[str, OHLCVSeries]:
    """Best-effort loader for the .cache/ohlcv/ JSON dumps.

    The cache is keyed by hashed filenames, so we pick the *largest* daily
    file per symbol (most history). Symbols without a cache entry are
    skipped — callers can supply synthetic series for those.
    """
    cache_dir = cache_dir or (Path(__file__).resolve().parents[2] / ".cache" / "ohlcv")
    out: dict[str, OHLCVSeries] = {}
    if not cache_dir.is_dir():
        return out
    import json

    for sym in symbols:
        candidates = sorted(
            cache_dir.glob(f"{sym}_1d_*.json"),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if not candidates:
            continue
        try:
            data = json.loads(candidates[0].read_text(encoding="utf-8"))
            series = OHLCVSeries.model_validate(data)
            out[sym] = series
        except Exception as exc:  # noqa: BLE001
            log.warning("backtest: failed to load %s: %s", candidates[0], exc)
    return out


__all__ = [
    "Backtester",
    "BacktestOutcome",
    "BacktestSummary",
    "format_summary",
    "load_history_from_cache",
    "summarize",
    "write_csv",
]
