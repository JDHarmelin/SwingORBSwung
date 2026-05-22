"""Price-level helpers shared by setup detectors.

Thin wrappers over the feature library so detectors read declaratively.
"""

from __future__ import annotations

import numpy as np

from trading_engine.core.types import OHLCVSeries
from trading_engine.features.compression import local_pivots
from trading_engine.features.indicators import atr, ema_set


def last_close(series: OHLCVSeries) -> float:
    return float(series.to_dataframe()["close"].iloc[-1])


def last_atr(series: OHLCVSeries, length: int = 14) -> float:
    a = atr(series, length=length)
    val = float(a.iloc[-1])
    return val if np.isfinite(val) else 0.0


def ema_value(series: OHLCVSeries, length: int) -> float:
    e = ema_set(series, (length,))[f"ema_{length}"]
    val = float(e.iloc[-1])
    return val if np.isfinite(val) else float("nan")


def recent_swing_high(series: OHLCVSeries, *, lookback: int = 40, exclude_last: int = 1) -> float | None:
    """Most recent swing-high price, ignoring the final ``exclude_last`` bars
    (so an in-progress breakout bar doesn't count as its own resistance)."""
    pivots = [p for p in local_pivots(series, lookback=lookback) if p.kind == "high"]
    n = len(series.candles)
    pivots = [p for p in pivots if p.index <= n - 1 - exclude_last]
    return pivots[-1].price if pivots else None


def recent_swing_low(series: OHLCVSeries, *, lookback: int = 40, exclude_last: int = 1) -> float | None:
    pivots = [p for p in local_pivots(series, lookback=lookback) if p.kind == "low"]
    n = len(series.candles)
    pivots = [p for p in pivots if p.index <= n - 1 - exclude_last]
    return pivots[-1].price if pivots else None


def highest_high(series: OHLCVSeries, *, lookback: int = 20, exclude_last: int = 1) -> float:
    df = series.to_dataframe()
    window = df["high"].iloc[-(lookback + exclude_last) : len(df) - exclude_last]
    return float(window.max()) if not window.empty else float(df["high"].max())


def lowest_low(series: OHLCVSeries, *, lookback: int = 20, exclude_last: int = 1) -> float:
    df = series.to_dataframe()
    window = df["low"].iloc[-(lookback + exclude_last) : len(df) - exclude_last]
    return float(window.min()) if not window.empty else float(df["low"].min())


__all__ = [
    "ema_value",
    "highest_high",
    "last_atr",
    "last_close",
    "lowest_low",
    "recent_swing_high",
    "recent_swing_low",
]
