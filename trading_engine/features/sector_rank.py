"""Sector / theme ranking (spec §4).

Ranks sector ETFs by relative performance vs SPY over 1d/5d/20d, plus a
breadth proxy derived from the ETF's own trend quality and volume expansion
(true constituent breadth needs member data not available to the mock
provider, so the ETF's structure stands in — documented approximation).

Pure functions over ``OHLCVSeries`` → ``SectorScore`` (spec DB outline).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from trading_engine.core.types import OHLCVSeries, SectorScore, Timeframe
from trading_engine.features.relative_strength import relative_strength
from trading_engine.features.trend import trend_score
from trading_engine.features.volume import volume_expansion_score


def _safe(x: float) -> float:
    return 0.0 if (x is None or np.isnan(x)) else float(x)


def sector_score(
    sector: str,
    etf_daily: OHLCVSeries,
    spy_daily: OHLCVSeries,
    *,
    as_of: datetime,
) -> SectorScore:
    """Score a single sector ETF vs SPY.

    ``composite_score`` blends a normalised RS score (0.5), trend quality
    (0.3), and a volume/breadth proxy (0.2), all in roughly [-1, 1].
    """
    if etf_daily.timeframe is not Timeframe.D1 or spy_daily.timeframe is not Timeframe.D1:
        raise ValueError("sector_score requires daily series")

    rs = relative_strength(etf_daily, spy_daily)
    trend = trend_score(etf_daily)
    vol = volume_expansion_score(etf_daily)
    # Breadth proxy: a sector that trends cleanly with expanding volume has
    # broad participation. Blend trend alignment with volume expansion.
    breadth = float(np.clip(0.6 * trend.score + 0.4 * vol.score, -1.0, 1.0))
    composite = float(np.clip(0.5 * rs.rs_score + 0.3 * trend.score + 0.2 * breadth, -1.0, 1.0))

    return SectorScore(
        timestamp=as_of,
        sector=sector,
        rs_1d=_safe(rs.excess_returns.get("1d", float("nan"))),
        rs_5d=_safe(rs.excess_returns.get("5d", float("nan"))),
        rs_20d=_safe(rs.excess_returns.get("20d", float("nan"))),
        breadth_score=breadth,
        composite_score=composite,
    )


def rank_sectors(
    sector_etf_series: dict[str, OHLCVSeries],
    spy_daily: OHLCVSeries,
    *,
    as_of: datetime,
) -> list[SectorScore]:
    """Score and rank every sector, strongest composite first."""
    scores = [
        sector_score(sector, etf, spy_daily, as_of=as_of)
        for sector, etf in sector_etf_series.items()
    ]
    scores.sort(key=lambda s: s.composite_score, reverse=True)
    return scores


def leading_sectors(scores: list[SectorScore], *, n: int = 3) -> list[SectorScore]:
    return scores[:n]


def lagging_sectors(scores: list[SectorScore], *, n: int = 3) -> list[SectorScore]:
    return sorted(scores, key=lambda s: s.composite_score)[:n]


__all__ = [
    "lagging_sectors",
    "leading_sectors",
    "rank_sectors",
    "sector_score",
]
