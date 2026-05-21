"""Core technical indicators — pure functions over OHLCVSeries / DataFrames."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from trading_engine.core.types import OHLCVSeries, Timeframe


def _df(series: OHLCVSeries) -> pd.DataFrame:
    return series.to_dataframe()


def ema(series: OHLCVSeries, period: int) -> pd.Series:
    """Exponential moving average of close."""
    return _df(series)["close"].ewm(span=period, adjust=False).mean()


def atr(series: OHLCVSeries, period: int = 14) -> pd.Series:
    """Average true range."""
    df = _df(series)
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def rolling_volume_avg(series: OHLCVSeries, period: int = 20) -> pd.Series:
    return _df(series)["volume"].rolling(period, min_periods=1).mean()


def prior_day_high_low(series: OHLCVSeries) -> tuple[float | None, float | None]:
    """Prior bar high/low (daily) or prior session bar for intraday."""
    df = _df(series)
    if len(df) < 2:
        return None, None
    prev = df.iloc[-2]
    return float(prev["high"]), float(prev["low"])


def opening_range(series: OHLCVSeries, bars: int = 6) -> tuple[float, float] | None:
    """First N bars high/low (intraday ORB helper)."""
    df = _df(series)
    if len(df) < bars:
        return None
    window = df.iloc[:bars]
    return float(window["high"].max()), float(window["low"].min())


def gap_pct(series: OHLCVSeries) -> float | None:
    """Open vs prior close gap percentage."""
    df = _df(series)
    if len(df) < 2:
        return None
    prev_close = float(df["close"].iloc[-2])
    today_open = float(df["open"].iloc[-1])
    if prev_close == 0:
        return None
    return (today_open - prev_close) / prev_close * 100.0


def session_vwap(series: OHLCVSeries) -> pd.Series:
    """Session VWAP for intraday; cumulative VWAP for daily."""
    df = _df(series)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_vol = df["volume"].cumsum()
    cum_pv = (typical * df["volume"]).cumsum()
    return cum_pv / cum_vol.replace(0, np.nan)


def vwap_position(series: OHLCVSeries) -> str:
    """Return 'above' | 'below' | 'at' relative to session VWAP."""
    df = _df(series)
    if df.empty:
        return "at"
    vwap = session_vwap(series)
    close = float(df["close"].iloc[-1])
    last_vwap = float(vwap.iloc[-1])
    if close > last_vwap * 1.001:
        return "above"
    if close < last_vwap * 0.999:
        return "below"
    return "at"


@dataclass(frozen=True)
class VWAPContext:
    position: str
    vwap: float
    close: float


def vwap_context(series: OHLCVSeries) -> VWAPContext:
    df = _df(series)
    v = session_vwap(series)
    close = float(df["close"].iloc[-1])
    return VWAPContext(position=vwap_position(series), vwap=float(v.iloc[-1]), close=close)


def is_intraday(timeframe: Timeframe) -> bool:
    return timeframe != Timeframe.D1
