"""In-memory ``Repository`` implementation.

Drop-in for the SQL repo when running locally / in tests. Thread-safe enough
for single-process async use.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from trading_engine.core.types import (
    Candle,
    MarketRegime,
    SectorScore,
    Signal,
    SignalEvent,
    SymbolScore,
    Timeframe,
)


class InMemoryRepository:
    def __init__(self) -> None:
        # (symbol, timeframe) → ordered candles
        self._candles: dict[tuple[str, Timeframe], list[Candle]] = defaultdict(list)
        self._regimes: list[MarketRegime] = []
        self._sector_scores: list[SectorScore] = []
        self._symbol_scores: list[SymbolScore] = []
        self._signals: dict[str, Signal] = {}
        self._events: dict[str, list[SignalEvent]] = defaultdict(list)

    # candles --------------------------------------------------------------
    async def upsert_candles(self, candles: list[Candle]) -> None:
        for c in candles:
            key = (c.symbol, c.timeframe)
            existing = self._candles[key]
            # Replace by timestamp if present, else append.
            for i, e in enumerate(existing):
                if e.timestamp == c.timestamp:
                    existing[i] = c
                    break
            else:
                existing.append(c)
            existing.sort(key=lambda x: x.timestamp)

    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        return [
            c
            for c in self._candles.get((symbol, timeframe), [])
            if start <= c.timestamp <= end
        ]

    # market_regime --------------------------------------------------------
    async def save_regime(self, regime: MarketRegime) -> None:
        self._regimes.append(regime)

    async def latest_regime(self) -> MarketRegime | None:
        return self._regimes[-1] if self._regimes else None

    # sector_scores --------------------------------------------------------
    async def save_sector_scores(self, scores: list[SectorScore]) -> None:
        self._sector_scores.extend(scores)

    async def latest_sector_scores(self) -> list[SectorScore]:
        if not self._sector_scores:
            return []
        latest_ts = max(s.timestamp for s in self._sector_scores)
        return [s for s in self._sector_scores if s.timestamp == latest_ts]

    # symbol_scores --------------------------------------------------------
    async def save_symbol_scores(self, scores: list[SymbolScore]) -> None:
        self._symbol_scores.extend(scores)

    async def latest_symbol_scores(self) -> list[SymbolScore]:
        if not self._symbol_scores:
            return []
        latest_ts = max(s.timestamp for s in self._symbol_scores)
        return [s for s in self._symbol_scores if s.timestamp == latest_ts]

    # signals + events -----------------------------------------------------
    async def save_signal(self, signal: Signal) -> None:
        self._signals[signal.signal_id] = signal

    async def get_signal(self, signal_id: str) -> Signal | None:
        return self._signals.get(signal_id)

    async def open_signals(self) -> list[Signal]:
        from trading_engine.core.types import SignalStatus

        return [
            s for s in self._signals.values()
            if s.status in {SignalStatus.PENDING, SignalStatus.TRIGGERED, SignalStatus.TRIMMED}
        ]

    async def append_signal_event(self, event: SignalEvent) -> None:
        self._events[event.signal_id].append(event)

    async def list_signal_events(self, signal_id: str) -> list[SignalEvent]:
        return list(self._events.get(signal_id, []))

    async def all_paper_outcomes(self) -> list[dict]:
        out: list[dict] = []
        for sig in self._signals.values():
            for ev in self._events.get(sig.signal_id, []):
                if ev.event_type != "paper_outcome":
                    continue
                p = ev.event_payload
                out.append(
                    {
                        "signal_id": sig.signal_id,
                        "symbol": sig.symbol,
                        "setup_type": sig.setup_type.value,
                        "direction": sig.direction.value,
                        "confidence": sig.confidence,
                        "result": p.get("result"),
                        "r_multiple": p.get("r_multiple"),
                        "bars_held": p.get("bars_held"),
                        "triggered": p.get("triggered"),
                        "timestamp": ev.event_timestamp,
                    }
                )
        return out


__all__ = ["InMemoryRepository"]
