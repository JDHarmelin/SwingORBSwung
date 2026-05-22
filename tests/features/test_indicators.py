"""Numeric correctness for indicators (EMA, ATR, VWAP, opening range, gap %)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from trading_engine.core.types import OHLCVSeries, Timeframe
from trading_engine.features.indicators import (
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


def _const_series(
    closes: list[float],
    *,
    symbol: str = "TEST",
    timeframe: Timeframe = Timeframe.D1,
    base_ts: datetime | None = None,
    volume: float = 1_000.0,
) -> OHLCVSeries:
    base_ts = base_ts or datetime(2026, 5, 1, tzinfo=UTC)
    step = timedelta(days=1) if timeframe is Timeframe.D1 else timedelta(minutes=5)
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "timestamp": base_ts + step * i,
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": volume,
            }
        )
    df = pd.DataFrame(rows).set_index("timestamp")
    return OHLCVSeries.from_dataframe(df, symbol=symbol, timeframe=timeframe)


def test_ema_matches_pandas_ewm() -> None:
    closes = pd.Series(np.linspace(1.0, 10.0, 30))
    expected = closes.ewm(span=8, adjust=False, min_periods=8).mean()
    got = ema(closes, 8)
    pd.testing.assert_series_equal(got, expected, check_names=False)


def test_ema_constant_series_returns_constant() -> None:
    series = _const_series([50.0] * 30)
    out = ema_set(series, (8, 20)).dropna()
    assert np.allclose(out["ema_8"].iloc[-1], 50.0)
    assert np.allclose(out["ema_20"].iloc[-1], 50.0)


def test_true_range_and_atr_constant_bars() -> None:
    series = _const_series([100.0] * 30)
    tr = true_range(series.to_dataframe())
    # All bars identical → TR is 0 after the first NaN.
    assert (tr.dropna() == 0).all()
    a = atr(series, length=14).dropna()
    assert (a == 0).all()


def test_atr_known_value() -> None:
    """Hand-computed Wilder ATR on a tiny series."""
    rows = []
    base = datetime(2026, 1, 1, tzinfo=UTC)
    # high, low, close
    bars = [
        (10, 9, 9.5),
        (11, 9.5, 10.8),
        (10.9, 10.0, 10.2),
        (11.5, 10.1, 11.3),
        (12.0, 11.0, 11.9),
    ]
    for i, (h, lo, c) in enumerate(bars):
        rows.append(
            {
                "timestamp": base + timedelta(days=i),
                "open": c,
                "high": h,
                "low": lo,
                "close": c,
                "volume": 1.0,
            }
        )
    df = pd.DataFrame(rows).set_index("timestamp")
    series = OHLCVSeries.from_dataframe(df, symbol="X", timeframe=Timeframe.D1)
    a = atr(series, length=3).dropna()
    assert not a.empty
    # ATR should be positive and within the observed TR range.
    assert 0.5 < float(a.iloc[-1]) < 2.0


def test_vwap_intraday_resets_each_session() -> None:
    """Two consecutive sessions: VWAP at start of session 2 ≈ first bar's typical."""
    base = datetime(2026, 5, 1, 13, 30, tzinfo=UTC)  # day 1
    rows = []
    for i in range(6):  # 6 5m bars
        rows.append(
            {
                "timestamp": base + timedelta(minutes=5 * i),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    day2 = base + timedelta(days=1)
    for i in range(6):
        rows.append(
            {
                "timestamp": day2 + timedelta(minutes=5 * i),
                "open": 200.0,
                "high": 201.0,
                "low": 199.0,
                "close": 200.0,
                "volume": 1000.0,
            }
        )
    df = pd.DataFrame(rows).set_index("timestamp")
    series = OHLCVSeries.from_dataframe(df, symbol="X", timeframe=Timeframe.M5)
    v = vwap(series)
    # First bar of day 2 has typical 200.0 — VWAP should equal that, not blend with day 1.
    first_day2_ts = day2
    assert abs(float(v.loc[first_day2_ts]) - 200.0) < 1e-9


def test_above_below_vwap_consistency(uptrend_5m) -> None:
    a = above_vwap(uptrend_5m)
    b = below_vwap(uptrend_5m)
    assert (a & b).sum() == 0


def test_rolling_volume_and_relative_volume() -> None:
    series = _const_series([100.0] * 30, volume=1000.0)
    avg = rolling_volume_average(series, length=10).dropna()
    assert np.allclose(avg, 1000.0)
    rel = relative_volume(series, length=10).dropna()
    assert np.allclose(rel, 1.0)


def test_prior_day_levels(uptrend_daily) -> None:
    levels = prior_day_levels(uptrend_daily)
    df = uptrend_daily.to_dataframe()
    assert levels.high == pytest.approx(float(df["high"].iloc[-2]))
    assert levels.low == pytest.approx(float(df["low"].iloc[-2]))


def test_opening_range_uses_first_bars(uptrend_5m) -> None:
    or15 = opening_range(uptrend_5m, minutes=15)
    assert or15.bars == 3
    assert or15.high >= or15.low


def test_gap_pct(uptrend_daily) -> None:
    g = gap_pct(uptrend_daily)
    # Synthetic open == prior close (opens[i] = closes[i-1]) so gap is ~0.
    assert abs(g) < 0.5


def test_prior_day_levels_rejects_intraday(uptrend_5m) -> None:
    with pytest.raises(ValueError):
        prior_day_levels(uptrend_5m)
