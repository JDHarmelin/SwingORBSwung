"""Relative-strength tests against synthetic uptrend/breakdown vs benchmark."""

from __future__ import annotations

from trading_engine.core.types import Timeframe
from trading_engine.features.relative_strength import (
    composite_relative_strength,
    relative_strength,
)
from trading_engine.testing.synthetic import (
    breakdown_series,
    choppy_series,
    clean_uptrend_series,
)


def test_uptrend_outperforms_chop_benchmark() -> None:
    stock = clean_uptrend_series(symbol="UPTRD", timeframe=Timeframe.D1)
    bench = choppy_series(symbol="SPY", timeframe=Timeframe.D1)
    rs = relative_strength(stock, bench)
    assert rs.rs_score > 0.15
    # Multi-week excess return should be positive.
    assert rs.excess_returns["20d"] > 0
    assert any("RS+" in r for r in rs.reason_codes)


def test_breakdown_underperforms_uptrend_benchmark() -> None:
    stock = breakdown_series(symbol="BRKD", timeframe=Timeframe.D1)
    bench = clean_uptrend_series(symbol="SPY", timeframe=Timeframe.D1)
    rs = relative_strength(stock, bench)
    assert rs.rs_score < -0.2
    assert rs.excess_returns["20d"] < 0


def test_intraday_excess_populated_when_intraday_supplied() -> None:
    stock_d = clean_uptrend_series(symbol="UPTRD", timeframe=Timeframe.D1)
    bench_d = choppy_series(symbol="SPY", timeframe=Timeframe.D1)
    stock_i = clean_uptrend_series(symbol="UPTRD", timeframe=Timeframe.M5, n=120)
    bench_i = choppy_series(symbol="SPY", timeframe=Timeframe.M5, n=120)
    rs = relative_strength(
        stock_d, bench_d, stock_intraday=stock_i, benchmark_intraday=bench_i
    )
    assert rs.intraday_excess is not None


def test_composite_rs_across_benchmarks() -> None:
    stock = clean_uptrend_series(symbol="UPTRD", timeframe=Timeframe.D1)
    spy = choppy_series(symbol="SPY", timeframe=Timeframe.D1)
    qqq = choppy_series(symbol="QQQ", timeframe=Timeframe.D1, seed=6)
    comp = composite_relative_strength(stock, {"SPY": spy, "QQQ": qqq})
    assert comp.rs_score > 0
    assert set(comp.per_benchmark) == {"SPY", "QQQ"}
