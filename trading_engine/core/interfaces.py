"""Protocol interfaces — seams between modules.

No implementations here. Other waves implement these against real providers
(Polygon, Telegram, etc.); the mock provider in ``trading_engine.data``
implements them against the test fixtures so every wave can run today
without API keys.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from trading_engine.core.types import (
    Candle,
    MarketRegime,
    OHLCVSeries,
    OptionChain,
    SectorScore,
    Signal,
    SignalEvent,
    SymbolScore,
    Timeframe,
)


@runtime_checkable
class MarketDataProvider(Protocol):
    """OHLCV + latest quote for equities, ETFs, and indices."""

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> OHLCVSeries: ...

    async def get_latest_quote(self, symbol: str) -> Candle: ...


@runtime_checkable
class OptionsDataProvider(Protocol):
    """Snapshot of an option chain (bid/ask, IV, greeks, OI, volume)."""

    async def get_option_chain(
        self,
        underlying: str,
        as_of: datetime | None = None,
    ) -> OptionChain: ...


@runtime_checkable
class EventsProvider(Protocol):
    """Corporate events relevant to event-risk filtering."""

    async def next_earnings_date(self, symbol: str) -> date | None: ...

    async def next_ex_dividend_date(self, symbol: str) -> date | None: ...


@runtime_checkable
class AlertSink(Protocol):
    """Send a formatted alert. Implementations must be dedupe-aware.

    ``dedupe_key`` is the idempotency key — two calls with the same key should
    not result in two outbound messages.
    """

    async def send(self, message: str, *, dedupe_key: str) -> None: ...


@runtime_checkable
class Repository(Protocol):
    """Persistence seam — mirrors the DB outline tables in the spec.

    Implementations may use SQLAlchemy, in-memory dicts (tests), or other
    backends. Methods are async to allow non-blocking I/O.
    """

    # candles
    async def upsert_candles(self, candles: list[Candle]) -> None: ...

    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]: ...

    # market_regime
    async def save_regime(self, regime: MarketRegime) -> None: ...

    async def latest_regime(self) -> MarketRegime | None: ...

    # sector_scores
    async def save_sector_scores(self, scores: list[SectorScore]) -> None: ...

    async def latest_sector_scores(self) -> list[SectorScore]: ...

    # symbol_scores
    async def save_symbol_scores(self, scores: list[SymbolScore]) -> None: ...

    async def latest_symbol_scores(self) -> list[SymbolScore]: ...

    # signals + events
    async def save_signal(self, signal: Signal) -> None: ...

    async def get_signal(self, signal_id: str) -> Signal | None: ...

    async def open_signals(self) -> list[Signal]: ...

    async def append_signal_event(self, event: SignalEvent) -> None: ...

    async def list_signal_events(self, signal_id: str) -> list[SignalEvent]: ...


__all__ = [
    "AlertSink",
    "EventsProvider",
    "MarketDataProvider",
    "OptionsDataProvider",
    "Repository",
]
