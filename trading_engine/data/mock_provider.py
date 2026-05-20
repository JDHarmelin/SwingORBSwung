"""In-memory mock data adapters.

Implement the ``MarketDataProvider``, ``OptionsDataProvider``, and
``EventsProvider`` protocols against the synthetic fixtures so every later
wave can run today without API keys. Wave 1 adds the real Polygon adapter
alongside (not replacing) these.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from trading_engine.core.types import (
    Candle,
    OHLCVSeries,
    OptionChain,
    Timeframe,
)
from trading_engine.testing.synthetic import (
    breakdown_series,
    choppy_series,
    clean_uptrend_series,
    compression_then_breakout_series,
    pullback_to_8ema_series,
    sample_option_chain,
    sample_sector_etf_series,
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


# Canonical mapping from synthetic symbol → series generator.
_SHAPES: dict[str, Any] = {
    "UPTRD": clean_uptrend_series,
    "PB8": pullback_to_8ema_series,
    "FLAG": compression_then_breakout_series,
    "BRKD": breakdown_series,
    "CHOP": choppy_series,
}


class MockMarketDataProvider:
    """Serves synthetic OHLCV. Symbol → shape mapping is intentionally simple
    so tests can reason about it; unknown symbols fall back to a clean
    uptrend."""

    def __init__(self, extra_shapes: dict[str, Any] | None = None) -> None:
        self._shapes: dict[str, Any] = {**_SHAPES, **(extra_shapes or {})}

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> OHLCVSeries:
        shape = self._shapes.get(symbol)
        if shape is None:
            # Sector ETFs and unknown symbols → use sector helper which falls
            # back to choppy for genuinely unknown tickers.
            return sample_sector_etf_series(etf=symbol, timeframe=timeframe)
        series = shape(symbol=symbol, timeframe=timeframe)
        # Crop to [start, end] window — coerce both sides to tz-aware UTC.
        s, e = _aware(start), _aware(end)
        candles = [c for c in series.candles if s <= _aware(c.timestamp) <= e]
        return OHLCVSeries(symbol=symbol, timeframe=timeframe, candles=candles or series.candles)

    async def get_latest_quote(self, symbol: str) -> Candle:
        now = datetime.now(tz=UTC)
        series = await self.get_ohlcv(
            symbol,
            Timeframe.M5,
            now - timedelta(days=1),
            now,
        )
        return series.candles[-1]


class MockOptionsDataProvider:
    """Serves the sample option chain. The chain's ``underlying`` is rewritten
    so callers always get a chain matching the underlying they asked for."""

    async def get_option_chain(self, underlying: str, as_of: datetime | None = None) -> OptionChain:
        chain = sample_option_chain(underlying=underlying, as_of=as_of)
        return chain


class MockEventsProvider:
    """Returns deterministic event dates. By default no events nearby — which
    means the regime engine should not block trades in tests unless a test
    explicitly seeds an event."""

    def __init__(
        self,
        earnings: dict[str, date] | None = None,
        ex_dividend: dict[str, date] | None = None,
    ) -> None:
        self._earnings = earnings or {}
        self._ex_div = ex_dividend or {}

    async def next_earnings_date(self, symbol: str) -> date | None:
        return self._earnings.get(symbol)

    async def next_ex_dividend_date(self, symbol: str) -> date | None:
        return self._ex_div.get(symbol)


__all__ = [
    "MockEventsProvider",
    "MockMarketDataProvider",
    "MockOptionsDataProvider",
]
