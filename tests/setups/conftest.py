"""Helpers for setup detector tests: regime builders + bar appenders."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_engine.core.types import (
    Candle,
    Direction,
    MarketRegime,
    OHLCVSeries,
    RegimeType,
    SymbolScore,
)

AS_OF = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)


def make_regime(regime: RegimeType) -> MarketRegime:
    return MarketRegime(timestamp=AS_OF, regime=regime, confidence=0.8, notes=[])


def append_bar(
    series: OHLCVSeries,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> OHLCVSeries:
    last = series.candles[-1]
    step = last.timestamp - series.candles[-2].timestamp
    new = Candle(
        symbol=series.symbol,
        timeframe=series.timeframe,
        timestamp=last.timestamp + step,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )
    return series.model_copy(update={"candles": [*series.candles, new]})


def make_symbol_score(symbol: str, *, rs: float, composite: float) -> SymbolScore:
    return SymbolScore(
        timestamp=AS_OF,
        symbol=symbol,
        direction_bucket=Direction.LONG if composite >= 0 else Direction.SHORT,
        rs_score=rs,
        sector_score=0.0,
        structure_score=0.0,
        trend_score=0.0,
        volume_score=0.0,
        catalyst_score=0.0,
        composite_score=composite,
        reason_codes=[],
    )


@pytest.fixture
def long_regime() -> MarketRegime:
    return make_regime(RegimeType.LONG_BIAS)


@pytest.fixture
def short_regime() -> MarketRegime:
    return make_regime(RegimeType.SHORT_BIAS)


@pytest.fixture
def no_trade_regime() -> MarketRegime:
    return make_regime(RegimeType.NO_TRADE)
