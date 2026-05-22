"""Trend classification: EMA alignment + slope → ``TrendScore`` (spec §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd

from trading_engine.core.types import OHLCVSeries
from trading_engine.features.indicators import ema_set


class TrendDirection(StrEnum):
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    RANGE = "range"


@dataclass(frozen=True)
class TrendScore:
    direction: TrendDirection
    score: float  # [-1, 1]: +1 strong uptrend, -1 strong downtrend
    alignment: float  # [-1, 1]: how cleanly 8>20>50 (or inverse)
    slope_norm: float  # normalised slope of the 8EMA
    efficiency: float  # [0, 1]: path efficiency (Kaufman ER)
    ema_8: float
    ema_20: float
    ema_50: float
    reason_codes: list[str] = field(default_factory=list)


def _slope_norm(ema8: pd.Series, lookback: int = 8) -> float:
    """Normalised slope of the 8EMA over ``lookback`` bars: (last/first - 1)."""
    valid = ema8.dropna()
    if len(valid) < lookback + 1:
        return 0.0
    first = float(valid.iloc[-(lookback + 1)])
    last = float(valid.iloc[-1])
    if first == 0:
        return 0.0
    return (last / first) - 1.0


def efficiency_ratio(close: pd.Series, lookback: int = 20) -> float:
    """Kaufman efficiency ratio in [0, 1]: net move / summed absolute moves.

    Near 1 for a clean directional path, near 0 for choppy back-and-forth.
    Used to damp the trend score so a noisy random walk classifies as RANGE
    even when its EMAs are transiently aligned.
    """
    valid = close.dropna()
    if len(valid) < lookback + 1:
        return 0.0
    window = valid.iloc[-(lookback + 1):]
    net = abs(float(window.iloc[-1]) - float(window.iloc[0]))
    path = float(window.diff().abs().sum())
    if path == 0:
        return 0.0
    return net / path


def _alignment(e8: float, e20: float, e50: float) -> float:
    """Smooth alignment score in [-1, 1].

    Positive if 8>20>50, negative if 8<20<50. The magnitude reflects the
    relative spread between EMAs, capped to 1.
    """
    if any(np.isnan(v) for v in (e8, e20, e50)):
        return 0.0
    base = e50 if e50 != 0 else 1.0
    spread_top = (e8 - e20) / base
    spread_bot = (e20 - e50) / base
    # Both spreads same sign → aligned. Mean them and clip.
    if spread_top * spread_bot > 0:
        raw = (spread_top + spread_bot) / 2.0
        return float(np.clip(raw * 20.0, -1.0, 1.0))
    # Mixed: weaker alignment, take a damped signed sum.
    raw = (spread_top + spread_bot) / 2.0
    return float(np.clip(raw * 10.0, -1.0, 1.0))


def trend_score(
    series: OHLCVSeries,
    *,
    slope_lookback: int = 8,
    efficiency_lookback: int = 20,
    range_threshold: float = 0.15,
) -> TrendScore:
    """Combine EMA alignment and 8EMA slope into a [-1, 1] trend score,
    damped by path efficiency so choppy random walks read as RANGE.

    A magnitude below ``range_threshold`` classifies as RANGE; otherwise the
    sign sets uptrend/downtrend.
    """
    emas = ema_set(series, (8, 20, 50))
    if emas[["ema_8", "ema_20", "ema_50"]].dropna().empty:
        raise ValueError("series too short for 8/20/50 EMAs")

    close = series.to_dataframe()["close"]
    last = emas.iloc[-1]
    e8, e20, e50 = float(last["ema_8"]), float(last["ema_20"]), float(last["ema_50"])
    align = _alignment(e8, e20, e50)
    slope = _slope_norm(emas["ema_8"], lookback=slope_lookback)
    eff = efficiency_ratio(close, lookback=efficiency_lookback)
    # Empirically a ~3% 8-bar slope is a strong trend; scale by 30 so it
    # saturates tanh near that magnitude.
    slope_component = float(np.tanh(slope * 30.0))
    raw = 0.6 * align + 0.4 * slope_component
    # Damp by efficiency: a clean path keeps its score, chop collapses toward 0.
    score = float(np.clip(raw * eff, -1.0, 1.0))

    reasons: list[str] = []
    if e8 > e20 > e50:
        reasons.append("EMA stack bullish (8>20>50)")
    elif e8 < e20 < e50:
        reasons.append("EMA stack bearish (8<20<50)")
    else:
        reasons.append("EMA stack mixed")
    if slope > 0.005:
        reasons.append(f"8EMA rising +{slope * 100:.2f}%/{slope_lookback}b")
    elif slope < -0.005:
        reasons.append(f"8EMA falling {slope * 100:.2f}%/{slope_lookback}b")
    if eff < 0.3:
        reasons.append(f"Low path efficiency {eff:.2f} (choppy)")

    if abs(score) < range_threshold:
        direction = TrendDirection.RANGE
        reasons.append("Trend magnitude below range threshold")
    elif score > 0:
        direction = TrendDirection.UPTREND
    else:
        direction = TrendDirection.DOWNTREND

    return TrendScore(
        direction=direction,
        score=score,
        alignment=align,
        slope_norm=slope,
        efficiency=eff,
        ema_8=e8,
        ema_20=e20,
        ema_50=e50,
        reason_codes=reasons,
    )


__all__ = ["TrendDirection", "TrendScore", "efficiency_ratio", "trend_score"]
