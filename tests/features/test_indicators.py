"""Feature library tests."""

from __future__ import annotations

from trading_engine.core.types import Timeframe
from trading_engine.features.compression import compute_structure_score
from trading_engine.features.indicators import atr, ema, gap_pct, session_vwap
from trading_engine.features.relative_strength import relative_strength
from trading_engine.features.trend import TrendClassification, compute_trend_score
from trading_engine.features.volume import volume_expansion_score
from trading_engine.testing.synthetic import (
    choppy_series,
    clean_uptrend_series,
)


def test_ema_monotonic_uptrend(uptrend_daily) -> None:
    e = ema(uptrend_daily, 8)
    assert float(e.iloc[-1]) > float(e.iloc[0])


def test_atr_positive(uptrend_daily) -> None:
    a = atr(uptrend_daily)
    assert float(a.iloc[-1]) > 0


def test_rs_positive_for_outperformer() -> None:
    stock = clean_uptrend_series("UPTRD", Timeframe.D1)
    spy = clean_uptrend_series("SPY", Timeframe.D1)
    qqq = choppy_series("QQQ", Timeframe.D1)
    rs = relative_strength(stock, spy, qqq)
    assert rs.score >= 0.5


def test_compression_flags_on_flag_fixture(compression_daily) -> None:
    s = compute_structure_score(compression_daily)
    assert s.compression_detected or s.breakout_proximity > 0


def test_compression_not_on_pure_uptrend(uptrend_daily) -> None:
    s = compute_structure_score(uptrend_daily)
    assert not s.inside_day or s.score < 0.9


def test_trend_uptrend_classification(uptrend_daily) -> None:
    t = compute_trend_score(uptrend_daily)
    assert t.classification == TrendClassification.UPTREND


def test_trend_breakdown(breakdown_daily) -> None:
    t = compute_trend_score(breakdown_daily)
    assert t.classification in (TrendClassification.DOWNTREND, TrendClassification.RANGE)


def test_volume_expansion(compression_daily) -> None:
    v = volume_expansion_score(compression_daily)
    assert 0.0 <= v.score <= 1.0


def test_vwap_series(uptrend_5m) -> None:
    v = session_vwap(uptrend_5m)
    assert len(v) == len(uptrend_5m.candles)


def test_gap_pct_none_short_series() -> None:
    s = clean_uptrend_series(n=1)
    assert gap_pct(s) is None
