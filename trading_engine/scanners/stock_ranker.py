"""Stock ranking engine (spec §5).

Combines the feature scores into a signed composite per the spec's factor
model, then splits the universe into top-N long and short candidate buckets
with machine-readable reason codes.

Composite (signed; positive favours long):
    0.30*RS + 0.20*Sector + 0.20*Structure + 0.15*Trend + 0.10*Volume + 0.05*Catalyst

Volume expansion is direction-agnostic, so it is applied in the direction of
the trend (confirms whichever way the name is moving).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_engine.core.config import FactorWeights
from trading_engine.core.types import Direction, OHLCVSeries, SymbolScore, Timeframe
from trading_engine.features.compression import structure_score
from trading_engine.features.relative_strength import composite_relative_strength
from trading_engine.features.trend import trend_score
from trading_engine.features.volume import volume_expansion_score


@dataclass(frozen=True)
class SymbolRankInputs:
    symbol: str
    daily: OHLCVSeries
    benchmarks_daily: dict[str, OHLCVSeries]
    sector_composite: float = 0.0
    catalyst_score: float = 0.0
    stock_intraday: OHLCVSeries | None = None
    benchmarks_intraday: dict[str, OHLCVSeries] | None = None


def score_symbol(inp: SymbolRankInputs, weights: FactorWeights, *, as_of: datetime) -> SymbolScore:
    if inp.daily.timeframe is not Timeframe.D1:
        raise ValueError("score_symbol requires a daily series")

    rs = composite_relative_strength(
        inp.daily,
        inp.benchmarks_daily,
        stock_intraday=inp.stock_intraday,
        benchmarks_intraday=inp.benchmarks_intraday,
    )
    trend = trend_score(inp.daily)
    structure = structure_score(inp.daily)
    vol = volume_expansion_score(inp.daily)

    trend_sign = 1.0 if trend.score >= 0 else -1.0
    vol_directional = vol.score * trend_sign

    composite = (
        weights.relative_strength * rs.rs_score
        + weights.sector_strength * inp.sector_composite
        + weights.structure * structure.score
        + weights.trend * trend.score
        + weights.volume_expansion * vol_directional
        + weights.catalyst * inp.catalyst_score
    )
    composite = max(-1.0, min(1.0, composite))

    direction = Direction.LONG if composite >= 0 else Direction.SHORT

    reasons: list[str] = []
    reasons.extend(rs.reason_codes[:2])
    reasons.extend(trend.reason_codes[:1])
    reasons.extend(structure.reason_codes[:1])
    reasons.extend(vol.reason_codes[:1])
    if inp.sector_composite > 0.2:
        reasons.append(f"Sector strong ({inp.sector_composite:+.2f})")
    elif inp.sector_composite < -0.2:
        reasons.append(f"Sector weak ({inp.sector_composite:+.2f})")
    if inp.catalyst_score:
        reasons.append(f"Catalyst ({inp.catalyst_score:+.2f})")

    return SymbolScore(
        timestamp=as_of,
        symbol=inp.symbol,
        direction_bucket=direction,
        rs_score=rs.rs_score,
        sector_score=inp.sector_composite,
        structure_score=structure.score,
        trend_score=trend.score,
        volume_score=vol_directional,
        catalyst_score=inp.catalyst_score,
        composite_score=composite,
        reason_codes=reasons,
    )


@dataclass(frozen=True)
class RankedCandidates:
    longs: list[SymbolScore]
    shorts: list[SymbolScore]


def rank_symbols(
    inputs: list[SymbolRankInputs],
    weights: FactorWeights,
    *,
    as_of: datetime,
    top_n: int = 20,
    min_abs_composite: float = 0.0,
) -> RankedCandidates:
    """Score every symbol and return the top-N long and short candidates.

    ``min_abs_composite`` drops names whose conviction is below the floor —
    raise it for the "few, high-conviction" target.
    """
    scored = [score_symbol(i, weights, as_of=as_of) for i in inputs]
    longs = sorted(
        (s for s in scored if s.composite_score >= min_abs_composite),
        key=lambda s: s.composite_score,
        reverse=True,
    )[:top_n]
    shorts = sorted(
        (s for s in scored if s.composite_score <= -min_abs_composite),
        key=lambda s: s.composite_score,
    )[:top_n]
    return RankedCandidates(longs=longs, shorts=shorts)


__all__ = [
    "RankedCandidates",
    "SymbolRankInputs",
    "rank_symbols",
    "score_symbol",
]
