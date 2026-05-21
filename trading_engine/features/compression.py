"""Range contraction, inside days, compression geometry → StructureScore."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from trading_engine.core.types import OHLCVSeries
from trading_engine.features.indicators import atr


@dataclass(frozen=True)
class StructureScore:
    score: float
    compression_detected: bool
    inside_day: bool
    breakout_proximity: float
    reason_codes: list[str]


def detect_inside_day(series: OHLCVSeries) -> bool:
    df = series.to_dataframe()
    if len(df) < 2:
        return False
    today, prev = df.iloc[-1], df.iloc[-2]
    return bool(today["high"] <= prev["high"] and today["low"] >= prev["low"])


def range_contraction_ratio(series: OHLCVSeries, lookback: int = 10) -> float:
    """Recent range / prior range — lower means more compressed."""
    df = series.to_dataframe()
    if len(df) < lookback * 2:
        return 1.0
    recent = df.iloc[-lookback:]
    prior = df.iloc[-(lookback * 2) : -lookback]
    recent_range = float(recent["high"].max() - recent["low"].min())
    prior_range = float(prior["high"].max() - prior["low"].min())
    if prior_range <= 0:
        return 1.0
    return recent_range / prior_range


def local_pivots(series: OHLCVSeries, window: int = 3) -> tuple[list[float], list[float]]:
    """Simple local swing highs/lows."""
    df = series.to_dataframe()
    highs: list[float] = []
    lows: list[float] = []
    for i in range(window, len(df) - window):
        h = float(df["high"].iloc[i])
        low_val = float(df["low"].iloc[i])
        if h >= float(df["high"].iloc[i - window : i + window + 1].max()):
            highs.append(h)
        if low_val <= float(df["low"].iloc[i - window : i + window + 1].min()):
            lows.append(low_val)
    return highs, lows


def trendline_break(series: OHLCVSeries, lookback: int = 15) -> bool:
    """Close breaks above recent compression high."""
    df = series.to_dataframe()
    if len(df) < lookback + 1:
        return False
    resistance = float(df["high"].iloc[-(lookback + 1) : -1].max())
    return float(df["close"].iloc[-1]) > resistance


def compute_structure_score(series: OHLCVSeries) -> StructureScore:
    inside = detect_inside_day(series)
    ratio = range_contraction_ratio(series)
    compression = ratio < 0.55
    breakout_near = trendline_break(series)
    atr_series = atr(series)
    atr_val = float(atr_series.iloc[-1]) if len(atr_series) else 0.0
    close = float(series.to_dataframe()["close"].iloc[-1])
    proximity = 0.0
    if atr_val > 0:
        pd_h, _ = (
            float(series.to_dataframe()["high"].iloc[-10:].max()),
            float(series.to_dataframe()["low"].iloc[-10:].min()),
        )
        proximity = max(0.0, 1.0 - (pd_h - close) / atr_val)

    score = 0.4
    reasons: list[str] = []
    if compression:
        score += 0.25
        reasons.append("range_contraction")
    if inside:
        score += 0.15
        reasons.append("inside_day")
    if breakout_near:
        score += 0.25
        reasons.append("trendline_break")
    if proximity > 0.7:
        score += 0.1
        reasons.append("near_breakout")

    return StructureScore(
        score=float(np.clip(score, 0.0, 1.0)),
        compression_detected=compression,
        inside_day=inside,
        breakout_proximity=float(np.clip(proximity, 0.0, 1.0)),
        reason_codes=reasons,
    )
