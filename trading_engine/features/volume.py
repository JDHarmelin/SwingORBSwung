"""Volume expansion vs rolling average."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from trading_engine.core.types import OHLCVSeries
from trading_engine.features.indicators import rolling_volume_avg


@dataclass(frozen=True)
class VolumeExpansionScore:
    score: float
    ratio: float
    reason_codes: list[str]


def volume_expansion_score(series: OHLCVSeries, period: int = 20) -> VolumeExpansionScore:
    df = series.to_dataframe()
    avg = rolling_volume_avg(series, period)
    last_vol = float(df["volume"].iloc[-1])
    last_avg = float(avg.iloc[-1]) if len(avg) else last_vol
    ratio = last_vol / last_avg if last_avg > 0 else 1.0

    reasons: list[str] = []
    if ratio >= 1.5:
        reasons.append("volume_expansion")
    if ratio >= 2.0:
        reasons.append("volume_surge")

    score = float(np.clip(0.3 + (ratio - 1.0) * 0.35, 0.0, 1.0))
    return VolumeExpansionScore(score=score, ratio=ratio, reason_codes=reasons)
