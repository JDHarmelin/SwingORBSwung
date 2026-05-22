"""Trend score classification on each Wave 0 fixture."""

from __future__ import annotations

from trading_engine.features.trend import TrendDirection, trend_score


def test_uptrend_is_uptrend(uptrend_daily) -> None:
    t = trend_score(uptrend_daily)
    assert t.direction is TrendDirection.UPTREND
    assert t.score > 0.2
    assert t.ema_8 > t.ema_20 > t.ema_50


def test_breakdown_is_downtrend(breakdown_daily) -> None:
    t = trend_score(breakdown_daily)
    assert t.direction is TrendDirection.DOWNTREND
    assert t.score < -0.1


def test_chop_is_range(chop_daily) -> None:
    t = trend_score(chop_daily)
    assert t.direction is TrendDirection.RANGE
    assert abs(t.score) < 0.3
