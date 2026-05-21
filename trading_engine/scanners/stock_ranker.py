"""Stock ranking — spec §5 composite score."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.interfaces import MarketDataProvider
from trading_engine.core.types import Direction, SectorScore, SymbolScore, Timeframe
from trading_engine.features.compression import compute_structure_score
from trading_engine.features.relative_strength import relative_strength
from trading_engine.features.trend import compute_trend_score
from trading_engine.features.volume import volume_expansion_score


@dataclass(frozen=True)
class RankedBuckets:
    longs: list[SymbolScore]
    shorts: list[SymbolScore]


async def rank_stocks(
    market: MarketDataProvider,
    symbols: list[str],
    sector_scores: list[SectorScore],
    *,
    config: AppConfig | None = None,
) -> RankedBuckets:
    config = config or load_app_config()
    weights = config.settings.factor_weights
    now = datetime.now(tz=UTC)
    start = now - timedelta(days=30)
    spy = await market.get_ohlcv("SPY", Timeframe.D1, start, now)
    qqq = await market.get_ohlcv("QQQ", Timeframe.D1, start, now)
    sector_map = {s.sector: s.composite_score for s in sector_scores}

    long_scores: list[SymbolScore] = []
    short_scores: list[SymbolScore] = []

    for sym in symbols:
        series = await market.get_ohlcv(sym, Timeframe.D1, start, now)
        rs = relative_strength(series, spy, qqq)
        struct = compute_structure_score(series)
        trend = compute_trend_score(series)
        vol = volume_expansion_score(series)
        sector_score = max(sector_map.values()) if sector_map else 0.5
        catalyst = 0.0
        composite = (
            weights.relative_strength * rs.score
            + weights.sector_strength * sector_score
            + weights.structure * struct.score
            + weights.trend * trend.score
            + weights.volume_expansion * vol.score
            + weights.catalyst * catalyst
        )
        reasons = rs.reason_codes + struct.reason_codes + trend.reason_codes + vol.reason_codes
        score = SymbolScore(
            timestamp=now,
            symbol=sym,
            direction_bucket=Direction.LONG if composite >= 0.5 else Direction.SHORT,
            rs_score=rs.score,
            sector_score=sector_score,
            structure_score=struct.score,
            trend_score=trend.score,
            volume_score=vol.score,
            catalyst_score=catalyst,
            composite_score=composite,
            reason_codes=reasons,
        )
        if composite >= 0.55:
            long_scores.append(score)
        if composite <= 0.45 or rs.vs_spy_5d < -1:
            short_scores.append(
                SymbolScore(
                    **{**score.model_dump(), "direction_bucket": Direction.SHORT}
                )
            )

    long_scores.sort(key=lambda s: s.composite_score, reverse=True)
    short_scores.sort(key=lambda s: s.composite_score)
    return RankedBuckets(
        longs=long_scores[:20],
        shorts=short_scores[:20],
    )
