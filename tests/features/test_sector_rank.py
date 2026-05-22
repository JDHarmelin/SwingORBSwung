"""Sector ranking: leaders score above laggards."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_engine.core.types import Timeframe
from trading_engine.features.sector_rank import (
    lagging_sectors,
    leading_sectors,
    rank_sectors,
)
from trading_engine.testing.synthetic import (
    breakdown_series,
    choppy_series,
    clean_uptrend_series,
)

_AS_OF = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)


def test_rank_sectors_orders_strong_above_weak() -> None:
    spy = clean_uptrend_series(symbol="SPY", timeframe=Timeframe.D1)
    sectors = {
        "semis": clean_uptrend_series(symbol="SMH", timeframe=Timeframe.D1),
        "energy": choppy_series(symbol="XLE", timeframe=Timeframe.D1),
        "weak": breakdown_series(symbol="BRKD", timeframe=Timeframe.D1),
    }
    ranked = rank_sectors(sectors, spy, as_of=_AS_OF)
    names = [s.sector for s in ranked]
    assert names[0] in {"semis", "energy"}
    assert names[-1] == "weak"
    assert ranked[0].composite_score > ranked[-1].composite_score


def test_leading_and_lagging_helpers() -> None:
    spy = clean_uptrend_series(symbol="SPY", timeframe=Timeframe.D1)
    sectors = {
        "semis": clean_uptrend_series(symbol="SMH", timeframe=Timeframe.D1),
        "weak": breakdown_series(symbol="BRKD", timeframe=Timeframe.D1),
    }
    ranked = rank_sectors(sectors, spy, as_of=_AS_OF)
    assert leading_sectors(ranked, n=1)[0].sector == "semis"
    assert lagging_sectors(ranked, n=1)[0].sector == "weak"
