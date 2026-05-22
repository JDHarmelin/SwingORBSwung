"""Technical feature library (indicators, RS, trend, structure, volume).

Pure functions over ``OHLCVSeries`` — deterministic and replayable.
"""

from trading_engine.features.compression import (
    Pivot,
    StructurePattern,
    StructureScore,
    Trendline,
    TrendlineBreak,
    detect_inside_day,
    local_pivots,
    range_contraction_ratio,
    structure_score,
    tight_closes,
    trendline_break,
)
from trading_engine.features.indicators import (
    OpeningRange,
    PriorDayLevels,
    above_vwap,
    atr,
    below_vwap,
    ema,
    ema_set,
    gap_pct,
    opening_range,
    prior_day_levels,
    relative_volume,
    rolling_volume_average,
    true_range,
    vwap,
)
from trading_engine.features.relative_strength import (
    CompositeRelativeStrength,
    RelativeStrengthResult,
    composite_relative_strength,
    relative_strength,
)
from trading_engine.features.trend import (
    TrendDirection,
    TrendScore,
    efficiency_ratio,
    trend_score,
)
from trading_engine.features.volume import VolumeExpansionScore, volume_expansion_score

__all__ = [
    "CompositeRelativeStrength",
    "OpeningRange",
    "Pivot",
    "PriorDayLevels",
    "RelativeStrengthResult",
    "StructurePattern",
    "StructureScore",
    "TrendDirection",
    "TrendScore",
    "Trendline",
    "TrendlineBreak",
    "VolumeExpansionScore",
    "above_vwap",
    "atr",
    "below_vwap",
    "composite_relative_strength",
    "detect_inside_day",
    "efficiency_ratio",
    "ema",
    "ema_set",
    "gap_pct",
    "local_pivots",
    "opening_range",
    "prior_day_levels",
    "range_contraction_ratio",
    "relative_strength",
    "relative_volume",
    "rolling_volume_average",
    "structure_score",
    "tight_closes",
    "trend_score",
    "trendline_break",
    "true_range",
    "volume_expansion_score",
    "vwap",
]
