"""Market regime engine (spec §3).

Classifies the environment as long-bias / short-bias / mixed / no-trade from
index trend (SPY/QQQ vs 8/20/50 EMA), intraday VWAP posture, and an event
filter. Non-negotiable rule: never alert without regime context, so this is
the first gate in the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_engine.core.types import MarketRegime, OHLCVSeries, RegimeType
from trading_engine.features.indicators import above_vwap
from trading_engine.features.trend import TrendDirection, trend_score


@dataclass(frozen=True)
class RegimeInputs:
    """Per-index inputs the regime engine consumes.

    ``daily`` is required; ``intraday`` (5m) is optional and, when present,
    contributes the VWAP-posture signal.
    """

    symbol: str
    daily: OHLCVSeries
    intraday: OHLCVSeries | None = None


def _index_bias(inp: RegimeInputs) -> tuple[float, list[str]]:
    """Return a per-index bias in [-1, 1] and reason notes."""
    notes: list[str] = []
    t = trend_score(inp.daily)
    bias = t.score
    if t.direction is TrendDirection.UPTREND:
        notes.append(f"{inp.symbol} daily uptrend ({t.score:+.2f})")
    elif t.direction is TrendDirection.DOWNTREND:
        notes.append(f"{inp.symbol} daily downtrend ({t.score:+.2f})")
    else:
        notes.append(f"{inp.symbol} daily range")

    if inp.intraday is not None:
        av = above_vwap(inp.intraday)
        last_above = bool(av.iloc[-1])
        # Nudge bias by VWAP posture.
        bias += 0.2 if last_above else -0.2
        notes.append(f"{inp.symbol} {'above' if last_above else 'below'} VWAP")
    return bias, notes


def classify_regime(
    indices: list[RegimeInputs],
    *,
    as_of: datetime,
    event_within_hours: int | None = None,
    block_if_event_within_hours: int = 4,
    long_threshold: float = 0.25,
    short_threshold: float = -0.25,
) -> MarketRegime:
    """Combine index biases + event filter into a ``MarketRegime``.

    ``event_within_hours`` is the hours until the next blocking macro/earnings
    event (None if none scheduled). If it is within
    ``block_if_event_within_hours``, the regime is forced to NO_TRADE.
    """
    if not indices:
        raise ValueError("classify_regime requires at least one index")

    # Event filter takes precedence (spec: event-risk → no-trade).
    if event_within_hours is not None and event_within_hours <= block_if_event_within_hours:
        return MarketRegime(
            timestamp=as_of,
            regime=RegimeType.NO_TRADE,
            confidence=0.9,
            notes=[f"Event within {event_within_hours}h — no-trade window"],
        )

    biases: list[float] = []
    notes: list[str] = []
    for inp in indices:
        b, n = _index_bias(inp)
        biases.append(b)
        notes.extend(n)

    avg = sum(biases) / len(biases)
    all_long = all(b > 0 for b in biases)
    all_short = all(b < 0 for b in biases)

    if avg >= long_threshold and all_long:
        regime = RegimeType.LONG_BIAS
    elif avg <= short_threshold and all_short:
        regime = RegimeType.SHORT_BIAS
    elif abs(avg) < long_threshold:
        regime = RegimeType.MIXED
    else:
        # Directional average but indices disagree → tactical/mixed.
        regime = RegimeType.MIXED

    confidence = min(0.99, 0.5 + abs(avg) / 2.0)
    notes.append(f"avg index bias {avg:+.2f} → {regime.value}")
    return MarketRegime(timestamp=as_of, regime=regime, confidence=confidence, notes=notes)


def regime_allows(regime: MarketRegime, *, want_short: bool) -> bool:
    """Whether the regime permits a long (default) or short candidate."""
    if regime.regime is RegimeType.NO_TRADE:
        return False
    if want_short:
        return regime.regime in {RegimeType.SHORT_BIAS, RegimeType.MIXED}
    return regime.regime in {RegimeType.LONG_BIAS, RegimeType.MIXED}


__all__ = ["RegimeInputs", "classify_regime", "regime_allows"]
