"""Universe liquidity filter + stock ranking buckets."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_engine.core.config import FactorWeights, LiquidityConfig
from trading_engine.core.types import Direction, Timeframe
from trading_engine.scanners.stock_ranker import SymbolRankInputs, rank_symbols
from trading_engine.scanners.universe_builder import build_universe, tradable_symbols
from trading_engine.testing.synthetic import (
    breakdown_series,
    choppy_series,
    clean_uptrend_series,
)

_AS_OF = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)
_WEIGHTS = FactorWeights(
    relative_strength=0.30,
    sector_strength=0.20,
    structure=0.20,
    trend=0.15,
    volume_expansion=0.10,
    catalyst=0.05,
)


def test_universe_filters_low_dollar_volume() -> None:
    # Synthetic base_volume ~1M, price ~100 → ADDV ~100M. Set a min above that
    # for one symbol class by using a very high threshold.
    series = {"UPTRD": clean_uptrend_series(symbol="UPTRD", timeframe=Timeframe.D1)}
    loose = LiquidityConfig(
        min_price=10.0,
        min_avg_daily_dollar_volume=1_000_000,
        min_option_open_interest=1,
        min_option_volume=1,
        max_option_bid_ask_spread_pct=8.0,
    )
    strict = LiquidityConfig(
        min_price=10.0,
        min_avg_daily_dollar_volume=10_000_000_000,
        min_option_open_interest=1,
        min_option_volume=1,
        max_option_bid_ask_spread_pct=8.0,
    )
    assert tradable_symbols(build_universe(series, loose)) == ["UPTRD"]
    assert tradable_symbols(build_universe(series, strict)) == []


def test_ranker_buckets_long_and_short() -> None:
    spy = choppy_series(symbol="SPY", timeframe=Timeframe.D1)
    qqq = choppy_series(symbol="QQQ", timeframe=Timeframe.D1, seed=9)
    bench = {"SPY": spy, "QQQ": qqq}
    inputs = [
        SymbolRankInputs(
            "UPTRD", clean_uptrend_series(symbol="UPTRD", timeframe=Timeframe.D1), bench, 0.4
        ),
        SymbolRankInputs(
            "BRKD", breakdown_series(symbol="BRKD", timeframe=Timeframe.D1), bench, -0.4
        ),
    ]
    ranked = rank_symbols(inputs, _WEIGHTS, as_of=_AS_OF, top_n=20)
    assert ranked.longs[0].symbol == "UPTRD"
    assert ranked.longs[0].direction_bucket is Direction.LONG
    assert ranked.shorts[0].symbol == "BRKD"
    assert ranked.shorts[0].direction_bucket is Direction.SHORT
    assert ranked.longs[0].composite_score > 0 > ranked.shorts[0].composite_score


def test_ranker_min_composite_filters_weak_names() -> None:
    spy = choppy_series(symbol="SPY", timeframe=Timeframe.D1)
    bench = {"SPY": spy}
    inputs = [
        SymbolRankInputs(
            "CHOP", choppy_series(symbol="CHOP", timeframe=Timeframe.D1, seed=11), bench, 0.0
        ),
    ]
    ranked = rank_symbols(inputs, _WEIGHTS, as_of=_AS_OF, top_n=20, min_abs_composite=0.5)
    assert ranked.longs == []
    assert ranked.shorts == []
