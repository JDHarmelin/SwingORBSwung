"""Technical feature library — pure functions over OHLCV."""

from trading_engine.features.compression import StructureScore, compute_structure_score
from trading_engine.features.indicators import (
    atr,
    ema,
    gap_pct,
    opening_range,
    prior_day_high_low,
    rolling_volume_avg,
    session_vwap,
    vwap_position,
)
from trading_engine.features.relative_strength import RelativeStrengthResult, relative_strength
from trading_engine.features.trend import TrendClassification, TrendScore, compute_trend_score
from trading_engine.features.volume import VolumeExpansionScore, volume_expansion_score

__all__ = [
    "StructureScore",
    "TrendClassification",
    "TrendScore",
    "VolumeExpansionScore",
    "RelativeStrengthResult",
    "atr",
    "compute_structure_score",
    "compute_trend_score",
    "ema",
    "gap_pct",
    "opening_range",
    "prior_day_high_low",
    "relative_strength",
    "rolling_volume_avg",
    "session_vwap",
    "volume_expansion_score",
    "vwap_position",
]
