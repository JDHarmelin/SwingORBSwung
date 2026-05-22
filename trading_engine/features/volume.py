"""Volume expansion / contraction scoring (spec §5 VolumeExpansionScore)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from trading_engine.core.types import OHLCVSeries
from trading_engine.features.indicators import relative_volume, rolling_volume_average


@dataclass(frozen=True)
class VolumeExpansionScore:
    score: float  # [-1, 1]
    current_volume: float
    avg_volume: float
    relative_volume: float  # current / avg
    recent_relative_volume: float  # mean of last ``recent`` bars' rel-vol
    reason_codes: list[str] = field(default_factory=list)


def volume_expansion_score(
    series: OHLCVSeries,
    *,
    avg_length: int = 20,
    recent: int = 3,
    expansion_threshold: float = 1.3,
    contraction_threshold: float = 0.7,
) -> VolumeExpansionScore:
    """Score current/recent volume vs trailing average.

    The score is ``tanh((rel - 1) * 2)`` blended 60/40 with the same on the
    ``recent``-bar average, so a single big bar lifts the score but sustained
    expansion lifts it more.
    """
    if avg_length <= 0 or recent <= 0:
        raise ValueError("avg_length and recent must be > 0")
    avg = rolling_volume_average(series, avg_length)
    rel = relative_volume(series, avg_length)
    df = series.to_dataframe()
    cur_v = float(df["volume"].iloc[-1])
    avg_v = float(avg.iloc[-1]) if not np.isnan(avg.iloc[-1]) else float("nan")
    if np.isnan(avg_v) or avg_v == 0:
        return VolumeExpansionScore(
            score=0.0,
            current_volume=cur_v,
            avg_volume=float(avg_v) if not np.isnan(avg_v) else 0.0,
            relative_volume=float("nan"),
            recent_relative_volume=float("nan"),
            reason_codes=["Insufficient bars for volume average"],
        )

    cur_rel = float(rel.iloc[-1])
    recent_rel = float(rel.iloc[-recent:].mean())
    cur_component = float(np.tanh((cur_rel - 1.0) * 2.0))
    recent_component = float(np.tanh((recent_rel - 1.0) * 2.0))
    score = float(np.clip(0.6 * cur_component + 0.4 * recent_component, -1.0, 1.0))

    reasons: list[str] = []
    if cur_rel >= expansion_threshold:
        reasons.append(f"Volume expansion: {cur_rel:.2f}× avg{avg_length}")
    elif cur_rel <= contraction_threshold:
        reasons.append(f"Volume contraction: {cur_rel:.2f}× avg{avg_length}")
    if recent_rel >= expansion_threshold:
        reasons.append(f"Sustained expansion last {recent}b: {recent_rel:.2f}× avg")
    elif recent_rel <= contraction_threshold:
        reasons.append(f"Sustained contraction last {recent}b: {recent_rel:.2f}× avg")

    return VolumeExpansionScore(
        score=score,
        current_volume=cur_v,
        avg_volume=avg_v,
        relative_volume=cur_rel,
        recent_relative_volume=recent_rel,
        reason_codes=reasons,
    )


__all__ = ["VolumeExpansionScore", "volume_expansion_score"]
