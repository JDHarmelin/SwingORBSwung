"""Sector ranking — spec §4."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.interfaces import MarketDataProvider
from trading_engine.core.types import SectorScore, Timeframe
from trading_engine.features.relative_strength import relative_strength


async def rank_sectors(
    market: MarketDataProvider,
    *,
    config: AppConfig | None = None,
) -> list[SectorScore]:
    config = config or load_app_config()
    now = datetime.now(tz=UTC)
    start = now - timedelta(days=30)
    spy = await market.get_ohlcv("SPY", Timeframe.D1, start, now)
    qqq = await market.get_ohlcv("QQQ", Timeframe.D1, start, now)
    scores: list[SectorScore] = []

    for sector, etf in config.universe.sector_etfs.items():
        etf_series = await market.get_ohlcv(etf, Timeframe.D1, start, now)
        rs = relative_strength(etf_series, spy, qqq)
        scores.append(
            SectorScore(
                timestamp=now,
                sector=sector,
                rs_1d=rs.vs_spy_1d,
                rs_5d=rs.vs_spy_5d,
                rs_20d=rs.vs_spy_20d,
                breadth_score=rs.score,
                composite_score=rs.score,
            )
        )

    return sorted(scores, key=lambda s: s.composite_score, reverse=True)
