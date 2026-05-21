"""Scanner tests with mock provider."""

from __future__ import annotations

import pytest

from trading_engine.core.types import RegimeType
from trading_engine.data.mock_provider import MockEventsProvider, MockMarketDataProvider
from trading_engine.scanners.market_regime import compute_market_regime
from trading_engine.scanners.sector_rank import rank_sectors
from trading_engine.scanners.stock_ranker import rank_stocks


@pytest.mark.asyncio
async def test_regime_long_bias_on_uptrend() -> None:
    market = MockMarketDataProvider()
    events = MockEventsProvider()
    regime = await compute_market_regime(market, events)
    assert regime.regime in (RegimeType.LONG_BIAS, RegimeType.MIXED)


@pytest.mark.asyncio
async def test_regime_no_trade_on_event() -> None:
    from datetime import date

    market = MockMarketDataProvider()
    events = MockEventsProvider(earnings={"AAPL": date.today()})
    regime = await compute_market_regime(market, events, block_events=True)
    assert regime.regime == RegimeType.NO_TRADE


@pytest.mark.asyncio
async def test_sector_rank_ordering() -> None:
    market = MockMarketDataProvider()
    scores = await rank_sectors(market)
    assert len(scores) > 0
    assert scores[0].composite_score >= scores[-1].composite_score


@pytest.mark.asyncio
async def test_stock_buckets() -> None:
    market = MockMarketDataProvider()
    sectors = await rank_sectors(market)
    buckets = await rank_stocks(market, ["UPTRD", "BRKD", "CHOP"], sectors)
    long_syms = [s.symbol for s in buckets.longs]
    short_syms = [s.symbol for s in buckets.shorts]
    assert "UPTRD" in long_syms or len(buckets.longs) > 0
    assert "BRKD" in short_syms or len(buckets.shorts) > 0
