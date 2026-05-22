"""Core technical indicators.

All functions are pure: they take an ``OHLCVSeries`` (or a derived DataFrame /
pandas Series) and return a pandas Series / scalar / typed dataclass. No
I/O, no global state — required for replayable signals.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trading_engine.core.types import OHLCVSeries, Timeframe

_INTRADAY_TIMEFRAMES = {Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.M30}


# ---------------------------------------------------------------------------
# Frame helpers
# ---------------------------------------------------------------------------


def _as_frame(series: OHLCVSeries) -> pd.DataFrame:
    df = series.to_dataframe()
    if df.empty:
        raise ValueError("OHLCVSeries is empty")
    return df


def _is_intraday(series: OHLCVSeries) -> bool:
    return series.timeframe in _INTRADAY_TIMEFRAMES


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


def ema(close: pd.Series, length: int) -> pd.Series:
    if length <= 0:
        raise ValueError("EMA length must be > 0")
    return close.ewm(span=length, adjust=False, min_periods=length).mean()


def ema_set(series: OHLCVSeries, lengths: tuple[int, ...] = (8, 20, 50)) -> pd.DataFrame:
    """Return a DataFrame with one column per requested EMA length."""
    df = _as_frame(series)
    out = pd.DataFrame(index=df.index)
    for length in lengths:
        out[f"ema_{length}"] = ema(df["close"], length)
    return out


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    a = df["high"] - df["low"]
    b = (df["high"] - prev_close).abs()
    c = (df["low"] - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(series: OHLCVSeries, length: int = 14) -> pd.Series:
    """Wilder's ATR (RMA of true range)."""
    if length <= 0:
        raise ValueError("ATR length must be > 0")
    df = _as_frame(series)
    tr = true_range(df)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


# ---------------------------------------------------------------------------
# VWAP (session-aware for intraday)
# ---------------------------------------------------------------------------


def vwap(series: OHLCVSeries) -> pd.Series:
    """Volume-weighted average price.

    For intraday timeframes the VWAP resets each session (calendar date of the
    bar timestamp). For daily timeframes a cumulative VWAP is returned.
    """
    df = _as_frame(series)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    if _is_intraday(series):
        session = pd.Series(pd.DatetimeIndex(df.index).date, index=df.index, name="session")
        cum_pv = pv.groupby(session).cumsum()
        cum_v = df["volume"].groupby(session).cumsum()
    else:
        cum_pv = pv.cumsum()
        cum_v = df["volume"].cumsum()
    out = cum_pv / cum_v.replace(0.0, np.nan)
    out.name = "vwap"
    return out


def above_vwap(series: OHLCVSeries) -> pd.Series:
    """Bool series: close strictly above session VWAP."""
    df = _as_frame(series)
    v = vwap(series)
    return df["close"] > v


def below_vwap(series: OHLCVSeries) -> pd.Series:
    df = _as_frame(series)
    v = vwap(series)
    return df["close"] < v


# ---------------------------------------------------------------------------
# Rolling volume averages
# ---------------------------------------------------------------------------


def rolling_volume_average(series: OHLCVSeries, length: int = 20) -> pd.Series:
    if length <= 0:
        raise ValueError("rolling_volume_average length must be > 0")
    df = _as_frame(series)
    return df["volume"].rolling(length, min_periods=length).mean()


def relative_volume(series: OHLCVSeries, length: int = 20) -> pd.Series:
    """Per-bar ratio of current volume to its trailing average."""
    df = _as_frame(series)
    avg = rolling_volume_average(series, length)
    return df["volume"] / avg.replace(0.0, np.nan)


# ---------------------------------------------------------------------------
# Prior-day high/low
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriorDayLevels:
    high: float
    low: float
    close: float


def prior_day_levels(daily_series: OHLCVSeries, *, lookback: int = 1) -> PriorDayLevels:
    """Levels from the bar ``lookback`` bars before the last bar (default 1)."""
    if daily_series.timeframe is not Timeframe.D1:
        raise ValueError("prior_day_levels requires a daily OHLCVSeries")
    df = _as_frame(daily_series)
    if len(df) < lookback + 1:
        raise ValueError(f"need at least {lookback + 1} daily bars, got {len(df)}")
    row = df.iloc[-1 - lookback]
    return PriorDayLevels(high=float(row["high"]), low=float(row["low"]), close=float(row["close"]))


# ---------------------------------------------------------------------------
# Opening range
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpeningRange:
    session_date: pd.Timestamp
    high: float
    low: float
    bars: int


def opening_range(
    intraday_series: OHLCVSeries, minutes: int = 15, *, session_date: pd.Timestamp | None = None
) -> OpeningRange:
    """Opening-range high/low for the first ``minutes`` of the session.

    Defaults to the most recent session in the series.
    """
    if not _is_intraday(intraday_series):
        raise ValueError("opening_range requires an intraday OHLCVSeries")
    df = _as_frame(intraday_series)
    sessions = pd.Series(pd.DatetimeIndex(df.index).date, index=df.index)
    target = sessions.iloc[-1] if session_date is None else pd.Timestamp(session_date).date()
    day = df[sessions == target]
    if day.empty:
        raise ValueError(f"no bars for session {target}")
    step_min = {
        Timeframe.M1: 1,
        Timeframe.M5: 5,
        Timeframe.M15: 15,
        Timeframe.M30: 30,
    }[intraday_series.timeframe]
    bars = max(1, minutes // step_min)
    window = day.iloc[:bars]
    return OpeningRange(
        session_date=pd.Timestamp(target),
        high=float(window["high"].max()),
        low=float(window["low"].min()),
        bars=len(window),
    )


# ---------------------------------------------------------------------------
# Gap %
# ---------------------------------------------------------------------------


def gap_pct(daily_series: OHLCVSeries) -> float:
    """Open-to-prior-close gap as a percentage of prior close (last bar)."""
    if daily_series.timeframe is not Timeframe.D1:
        raise ValueError("gap_pct requires a daily OHLCVSeries")
    df = _as_frame(daily_series)
    if len(df) < 2:
        raise ValueError("gap_pct requires at least 2 daily bars")
    prev_close = float(df["close"].iloc[-2])
    today_open = float(df["open"].iloc[-1])
    if prev_close == 0:
        return 0.0
    return (today_open - prev_close) / prev_close * 100.0


__all__ = [
    "OpeningRange",
    "PriorDayLevels",
    "above_vwap",
    "atr",
    "below_vwap",
    "ema",
    "ema_set",
    "gap_pct",
    "opening_range",
    "prior_day_levels",
    "relative_volume",
    "rolling_volume_average",
    "true_range",
    "vwap",
]
