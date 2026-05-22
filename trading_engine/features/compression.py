"""Compression / wedge / flag detection + ``StructureScore`` (spec §5, §6 D).

Exposes reusable primitives so Wave 2 setup detectors can re-use them:
``detect_inside_day``, ``range_contraction_ratio``, ``local_pivots``,
``trendline_break``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from trading_engine.core.types import OHLCVSeries
from trading_engine.features.indicators import atr

# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def detect_inside_day(series: OHLCVSeries, *, index: int = -1) -> bool:
    """True if the bar at ``index`` has high<=prev.high and low>=prev.low."""
    df = series.to_dataframe()
    if len(df) < 2 or abs(index) > len(df):
        return False
    cur = df.iloc[index]
    prev = df.iloc[index - 1]
    return bool(cur["high"] <= prev["high"] and cur["low"] >= prev["low"])


def range_contraction_ratio(
    series: OHLCVSeries, *, window: int = 5, baseline: int = 20
) -> float:
    """Ratio of recent average true range to the ``baseline`` ATR.

    < 1.0 means the most recent bars are tighter than the trailing baseline.
    """
    if window <= 0 or baseline <= window:
        raise ValueError("baseline must be > window > 0")
    df = series.to_dataframe()
    if len(df) < baseline + 1:
        return float("nan")
    a = atr(series, length=baseline)
    recent = float(a.iloc[-window:].mean())
    base = float(a.iloc[-baseline])
    if not np.isfinite(base) or base == 0:
        return float("nan")
    return recent / base


def tight_closes(series: OHLCVSeries, *, window: int = 5, tightness: float = 0.4) -> bool:
    """True if the std of the last ``window`` closes is < ``tightness`` × ATR.

    ATR is computed with length=``window``.
    """
    df = series.to_dataframe()
    if len(df) < window + 1:
        return False
    a = atr(series, length=window)
    a_now = float(a.iloc[-1])
    if not np.isfinite(a_now) or a_now == 0:
        return False
    std = float(df["close"].iloc[-window:].std(ddof=0))
    return std < tightness * a_now


@dataclass(frozen=True)
class Pivot:
    index: int  # positional index in the input series
    price: float
    kind: str  # "high" or "low"


def local_pivots(
    series: OHLCVSeries, *, left: int = 3, right: int = 3, lookback: int | None = None
) -> list[Pivot]:
    """Local swing pivots: a bar is a high pivot if its high exceeds the
    ``left`` bars before and ``right`` bars after it (strict); analogous for
    lows. Edge bars without enough neighbours are skipped.

    ``lookback`` (if given) restricts the search to the last N bars.
    """
    df = series.to_dataframe()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)
    start = 0 if lookback is None else max(0, n - lookback)
    out: list[Pivot] = []
    for i in range(max(start, left), n - right):
        h = highs[i]
        if h > highs[i - left : i].max() and h > highs[i + 1 : i + right + 1].max():
            out.append(Pivot(index=i, price=float(h), kind="high"))
        lo = lows[i]
        if lo < lows[i - left : i].min() and lo < lows[i + 1 : i + right + 1].min():
            out.append(Pivot(index=i, price=float(lo), kind="low"))
    out.sort(key=lambda p: p.index)
    return out


@dataclass(frozen=True)
class Trendline:
    kind: str  # "support" (along lows) or "resistance" (along highs)
    slope: float  # per-bar
    intercept: float  # value at index 0
    anchors: tuple[int, int]  # positional indices of the two anchor pivots

    def value_at(self, index: int) -> float:
        return self.intercept + self.slope * index


def _fit_trendline(pivots: list[Pivot]) -> Trendline | None:
    """Fit a line through the two most recent pivots of the same kind."""
    if len(pivots) < 2:
        return None
    p2 = pivots[-1]
    p1 = pivots[-2]
    if p1.kind != p2.kind:
        return None
    dx = p2.index - p1.index
    if dx == 0:
        return None
    slope = (p2.price - p1.price) / dx
    intercept = p1.price - slope * p1.index
    kind = "resistance" if p1.kind == "high" else "support"
    return Trendline(kind=kind, slope=slope, intercept=intercept, anchors=(p1.index, p2.index))


@dataclass(frozen=True)
class TrendlineBreak:
    line: Trendline
    direction: str  # "up" (close above resistance) or "down" (close below support)
    break_index: int
    break_price: float
    distance_pct: float  # close vs line value, signed % of line value


def trendline_break(
    series: OHLCVSeries,
    *,
    left: int = 3,
    right: int = 3,
    lookback: int = 60,
    require_close: bool = True,
) -> TrendlineBreak | None:
    """Detect a break of the most recent same-kind pivot trendline.

    Returns ``None`` if no pivots are available or the latest close doesn't
    breach the fitted line.
    """
    pivots = local_pivots(series, left=left, right=right, lookback=lookback)
    highs = [p for p in pivots if p.kind == "high"]
    lows = [p for p in pivots if p.kind == "low"]
    df = series.to_dataframe()
    last_idx = len(df) - 1
    last_close = float(df["close"].iloc[-1])

    def _check(pvts: list[Pivot]) -> TrendlineBreak | None:
        line = _fit_trendline(pvts)
        if line is None:
            return None
        ref = line.value_at(last_idx)
        if ref == 0:
            return None
        if line.kind == "resistance" and (last_close > ref if require_close else True):
            return TrendlineBreak(
                line=line,
                direction="up",
                break_index=last_idx,
                break_price=last_close,
                distance_pct=(last_close - ref) / ref * 100.0,
            )
        if line.kind == "support" and (last_close < ref if require_close else True):
            return TrendlineBreak(
                line=line,
                direction="down",
                break_index=last_idx,
                break_price=last_close,
                distance_pct=(last_close - ref) / ref * 100.0,
            )
        return None

    # Prefer breaks of resistance for momentum-long usage, fall back to support.
    return _check(highs) or _check(lows)


# ---------------------------------------------------------------------------
# StructureScore
# ---------------------------------------------------------------------------


class StructurePattern(StrEnum):
    COMPRESSION = "compression"
    BREAKOUT_PROXIMITY = "breakout_proximity"
    INSIDE_DAY = "inside_day"
    NONE = "none"


@dataclass(frozen=True)
class StructureScore:
    score: float  # [-1, 1] (positive = bullish structure)
    pattern: StructurePattern
    contraction_ratio: float
    breakout_distance_pct: float  # signed % distance from recent swing high
    inside_day: bool
    pivots: list[Pivot] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)


def structure_score(
    series: OHLCVSeries,
    *,
    contraction_window: int = 5,
    contraction_baseline: int = 20,
    pivot_left: int = 3,
    pivot_right: int = 3,
    pivot_lookback: int = 40,
    proximity_pct: float = 1.5,
) -> StructureScore:
    """Combine contraction, breakout proximity, and inside-day into a score.

    "Breakout proximity" is measured against the most recent swing high in the
    lookback window: a close within ``proximity_pct`` of that high (or above
    it) earns a positive contribution.
    """
    df = series.to_dataframe()
    last_close = float(df["close"].iloc[-1])

    ratio = range_contraction_ratio(
        series, window=contraction_window, baseline=contraction_baseline
    )
    inside = detect_inside_day(series)
    pivots = local_pivots(series, left=pivot_left, right=pivot_right, lookback=pivot_lookback)
    swing_highs = [p for p in pivots if p.kind == "high"]
    last_high = swing_highs[-1].price if swing_highs else float("nan")
    if last_high and np.isfinite(last_high):
        breakout_dist = (last_close - last_high) / last_high * 100.0
    else:
        breakout_dist = float("nan")

    reasons: list[str] = []

    # Contraction component: lower ratio → more compressed → higher score.
    if np.isfinite(ratio):
        contraction_component = float(np.clip(1.0 - ratio, -1.0, 1.0))
        if ratio < 0.7:
            reasons.append(f"Range compression: ATR ratio {ratio:.2f}")
    else:
        contraction_component = 0.0

    # Proximity component: close near or above last swing high.
    if np.isfinite(breakout_dist):
        if breakout_dist >= 0:
            proximity_component = 1.0
            reasons.append(f"Above last swing high by {breakout_dist:+.2f}%")
        elif breakout_dist > -proximity_pct:
            proximity_component = 1.0 - (abs(breakout_dist) / proximity_pct)
            reasons.append(f"Within {abs(breakout_dist):.2f}% of swing high")
        else:
            proximity_component = float(np.clip(breakout_dist / 5.0, -1.0, 0.0))
    else:
        proximity_component = 0.0

    inside_component = 0.3 if inside else 0.0
    if inside:
        reasons.append("Inside day")

    raw = 0.5 * contraction_component + 0.4 * proximity_component + 0.1 * inside_component
    score = float(np.clip(raw + (0.2 * inside_component if inside else 0.0), -1.0, 1.0))

    if np.isfinite(ratio) and ratio < 0.7 and (
        np.isfinite(breakout_dist) and breakout_dist > -proximity_pct
    ):
        pattern = StructurePattern.COMPRESSION
    elif np.isfinite(breakout_dist) and breakout_dist > -proximity_pct:
        pattern = StructurePattern.BREAKOUT_PROXIMITY
    elif inside:
        pattern = StructurePattern.INSIDE_DAY
    else:
        pattern = StructurePattern.NONE

    return StructureScore(
        score=score,
        pattern=pattern,
        contraction_ratio=float(ratio) if np.isfinite(ratio) else float("nan"),
        breakout_distance_pct=float(breakout_dist) if np.isfinite(breakout_dist) else float("nan"),
        inside_day=inside,
        pivots=pivots,
        reason_codes=reasons,
    )


__all__ = [
    "Pivot",
    "StructurePattern",
    "StructureScore",
    "Trendline",
    "TrendlineBreak",
    "detect_inside_day",
    "local_pivots",
    "range_contraction_ratio",
    "structure_score",
    "tight_closes",
    "trendline_break",
]
