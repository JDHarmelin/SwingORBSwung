"""Market regime engine — spec §3."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.interfaces import EventsProvider, MarketDataProvider
from trading_engine.core.types import MarketRegime, RegimeType, Timeframe
from trading_engine.features.indicators import vwap_position
from trading_engine.features.trend import TrendClassification, compute_trend_score


async def compute_market_regime(
    market: MarketDataProvider,
    events: EventsProvider,
    *,
    config: AppConfig | None = None,
    block_events: bool = False,
) -> MarketRegime:
    config = config or load_app_config()
    now = datetime.now(tz=UTC)
    start = now - timedelta(days=60)
    notes: list[str] = []
    long_votes = 0
    short_votes = 0

    for sym in ("SPY", "QQQ"):
        series = await market.get_ohlcv(sym, Timeframe.D1, start, now)
        intraday = await market.get_ohlcv(sym, Timeframe.M5, now - timedelta(days=1), now)
        if vwap_position(intraday) == "above":
            long_votes += 1
            notes.append(f"{sym} above VWAP")
        elif vwap_position(intraday) == "below":
            short_votes += 1
            notes.append(f"{sym} below VWAP")
        trend = compute_trend_score(series)
        if trend.classification == TrendClassification.UPTREND:
            long_votes += 1
        elif trend.classification == TrendClassification.DOWNTREND:
            short_votes += 1

    # Event filter
    if block_events:
        for sym in ("AAPL", "MSFT", "NVDA"):
            earn = await events.next_earnings_date(sym)
            if earn and abs((earn - now.date()).days) <= 1:
                return MarketRegime(
                    timestamp=now,
                    regime=RegimeType.NO_TRADE,
                    confidence=0.9,
                    notes=["event_risk_block"],
                )

    if long_votes >= 3 and short_votes <= 1:
        regime = RegimeType.LONG_BIAS
        conf = 0.75
    elif short_votes >= 3 and long_votes <= 1:
        regime = RegimeType.SHORT_BIAS
        conf = 0.75
    elif long_votes > 0 and short_votes > 0:
        regime = RegimeType.MIXED
        conf = 0.55
    else:
        regime = RegimeType.NO_TRADE
        conf = 0.4
        notes.append("weak_index_alignment")

    return MarketRegime(timestamp=now, regime=regime, confidence=conf, notes=notes)
