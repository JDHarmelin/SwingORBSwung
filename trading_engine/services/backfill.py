"""Backfill — pull candles from a provider into the repository."""

from __future__ import annotations

import asyncio
from datetime import datetime

from trading_engine.core.interfaces import MarketDataProvider, Repository
from trading_engine.core.types import OHLCVSeries, Timeframe


async def backfill_symbol(
    provider: MarketDataProvider,
    repo: Repository,
    symbol: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
) -> OHLCVSeries:
    series = await provider.get_ohlcv(symbol, timeframe, start, end)
    await repo.upsert_candles(series.candles)
    return series


async def backfill_universe(
    provider: MarketDataProvider,
    repo: Repository,
    symbols: list[str],
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    *,
    concurrency: int = 8,
) -> dict[str, OHLCVSeries]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(sym: str) -> tuple[str, OHLCVSeries]:
        async with sem:
            return sym, await backfill_symbol(provider, repo, sym, timeframe, start, end)

    pairs = await asyncio.gather(*[_one(s) for s in symbols])
    return dict(pairs)


__all__ = ["backfill_symbol", "backfill_universe"]
