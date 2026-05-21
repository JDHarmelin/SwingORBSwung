"""Historical candle backfill."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from trading_engine.core.interfaces import MarketDataProvider, Repository
from trading_engine.core.types import Timeframe

logger = logging.getLogger(__name__)


async def backfill_universe(
    market: MarketDataProvider,
    repo: Repository,
    symbols: list[str],
    *,
    days: int = 90,
    timeframes: tuple[Timeframe, ...] = (Timeframe.D1, Timeframe.M5),
) -> int:
    """Pull and store historical candles; returns total candles saved."""
    now = datetime.now(tz=UTC)
    start = now - timedelta(days=days)
    total = 0
    for sym in symbols:
        for tf in timeframes:
            series = await market.get_ohlcv(sym, tf, start, now)
            if series.candles:
                await repo.upsert_candles(series.candles)
                total += len(series.candles)
                logger.info("backfilled %s %s bars=%s", sym, tf.value, len(series.candles))
    return total
