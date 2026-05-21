"""EMA alignment + slope → TrendScore."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from trading_engine.core.types import OHLCVSeries
from trading_engine.features.indicators import ema


class TrendClassification(StrEnum):
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    RANGE = "range"


@dataclass(frozen=True)
class TrendScore:
    score: float  # 0–1
    classification: TrendClassification
    ema8_slope: float
    reason_codes: list[str]


def compute_trend_score(
    series: OHLCVSeries,
    *,
    ema_periods: tuple[int, ...] = (8, 20, 50),
) -> TrendScore:
    """EMA alignment and slope → trend score."""
    e8 = ema(series, ema_periods[0])
    e20 = ema(series, ema_periods[1])
    e50 = ema(series, ema_periods[2])
    close = series.to_dataframe()["close"]
    last_close = float(close.iloc[-1])
    last8 = float(e8.iloc[-1])
    last20 = float(e20.iloc[-1])
    last50 = float(e50.iloc[-1])

    slope = 0.0
    if len(e8) >= 5:
        slope = float((e8.iloc[-1] - e8.iloc[-5]) / max(e8.iloc[-5], 1e-9) * 100)

    reasons: list[str] = []
    if last8 > last20 > last50 and last_close > last8:
        classification = TrendClassification.UPTREND
        score = 0.85
        reasons.extend(["ema_bull_stack", "price_above_8ema"])
    elif last8 < last20 < last50 and last_close < last8:
        classification = TrendClassification.DOWNTREND
        score = 0.15
        reasons.extend(["ema_bear_stack", "price_below_8ema"])
    else:
        classification = TrendClassification.RANGE
        score = 0.45
        reasons.append("ema_mixed")

    if slope > 0.5:
        reasons.append("ema8_slope_positive")
        score = min(1.0, score + 0.1)
    elif slope < -0.5:
        reasons.append("ema8_slope_negative")
        score = max(0.0, score - 0.1)

    return TrendScore(
        score=float(np.clip(score, 0.0, 1.0)),
        classification=classification,
        ema8_slope=slope,
        reason_codes=reasons,
    )
