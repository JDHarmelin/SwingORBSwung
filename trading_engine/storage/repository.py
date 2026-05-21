"""SQLAlchemy Repository implementation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from trading_engine.core.types import (
    Candle,
    MarketRegime,
    SectorScore,
    Signal,
    SignalEvent,
    SignalStatus,
    SymbolScore,
    Timeframe,
)
from trading_engine.storage.db import create_engine_from_config, init_schema, session_factory
from trading_engine.storage.models import (
    CandleRow,
    MarketRegimeRow,
    SectorScoreRow,
    SignalEventRow,
    SignalRow,
    SymbolScoreRow,
)
from trading_engine.storage.serializers import (
    candle_to_row,
    event_to_row,
    regime_to_row,
    row_to_candle,
    row_to_event,
    row_to_regime,
    row_to_sector,
    row_to_signal,
    row_to_symbol,
    sector_to_row,
    signal_to_row,
    symbol_to_row,
)


class SqlRepository:
    """Async-compatible repository (methods are async for interface compliance)."""

    def __init__(self, engine: Engine | None = None, session_maker: sessionmaker | None = None) -> None:
        if engine is None:
            from trading_engine.core.config import load_app_config

            engine = create_engine_from_config(load_app_config())
            init_schema(engine)
        self._engine = engine
        self._session = session_maker or session_factory(engine)

    def _sess(self) -> Session:
        return self._session()

    async def upsert_candles(self, candles: list[Candle]) -> None:
        if not candles:
            return
        sym = candles[0].symbol
        tf = candles[0].timeframe.value
        with self._sess() as s:
            s.execute(
                delete(CandleRow).where(
                    CandleRow.symbol == sym,
                    CandleRow.timeframe == tf,
                )
            )
            s.add_all([candle_to_row(c) for c in candles])
            s.commit()

    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        tf = timeframe.value
        with self._sess() as s:
            rows = s.scalars(
                select(CandleRow)
                .where(
                    CandleRow.symbol == symbol,
                    CandleRow.timeframe == tf,
                    CandleRow.timestamp >= start,
                    CandleRow.timestamp <= end,
                )
                .order_by(CandleRow.timestamp)
            ).all()
        return [row_to_candle(r) for r in rows]

    async def save_regime(self, regime: MarketRegime) -> None:
        with self._sess() as s:
            s.add(regime_to_row(regime))
            s.commit()

    async def latest_regime(self) -> MarketRegime | None:
        with self._sess() as s:
            row = s.scalars(
                select(MarketRegimeRow).order_by(MarketRegimeRow.timestamp.desc()).limit(1)
            ).first()
        return row_to_regime(row) if row else None

    async def save_sector_scores(self, scores: list[SectorScore]) -> None:
        with self._sess() as s:
            s.add_all([sector_to_row(sc) for sc in scores])
            s.commit()

    async def latest_sector_scores(self) -> list[SectorScore]:
        with self._sess() as s:
            subq = select(SectorScoreRow.timestamp).order_by(SectorScoreRow.timestamp.desc()).limit(1)
            ts = s.scalar(subq)
            if ts is None:
                return []
            rows = s.scalars(select(SectorScoreRow).where(SectorScoreRow.timestamp == ts)).all()
        return [row_to_sector(r) for r in rows]

    async def save_symbol_scores(self, scores: list[SymbolScore]) -> None:
        with self._sess() as s:
            s.add_all([symbol_to_row(sc) for sc in scores])
            s.commit()

    async def latest_symbol_scores(self) -> list[SymbolScore]:
        with self._sess() as s:
            subq = select(SymbolScoreRow.timestamp).order_by(SymbolScoreRow.timestamp.desc()).limit(1)
            ts = s.scalar(subq)
            if ts is None:
                return []
            rows = s.scalars(select(SymbolScoreRow).where(SymbolScoreRow.timestamp == ts)).all()
        return [row_to_symbol(r) for r in rows]

    async def save_signal(self, signal: Signal) -> None:
        with self._sess() as s:
            existing = s.get(SignalRow, signal.signal_id)
            row = signal_to_row(signal)
            if existing:
                for k, v in row.__dict__.items():
                    if k != "_sa_instance_state":
                        setattr(existing, k, v)
            else:
                s.add(row)
            s.commit()

    async def get_signal(self, signal_id: str) -> Signal | None:
        with self._sess() as s:
            row = s.get(SignalRow, signal_id)
        return row_to_signal(row) if row else None

    async def open_signals(self) -> list[Signal]:
        open_statuses = {
            SignalStatus.PENDING.value,
            SignalStatus.TRIGGERED.value,
            SignalStatus.TRIMMED.value,
        }
        with self._sess() as s:
            rows = s.scalars(
                select(SignalRow).where(SignalRow.status.in_(open_statuses))
            ).all()
        return [row_to_signal(r) for r in rows]

    async def append_signal_event(self, event: SignalEvent) -> None:
        with self._sess() as s:
            s.add(event_to_row(event))
            s.commit()

    async def list_signal_events(self, signal_id: str) -> list[SignalEvent]:
        with self._sess() as s:
            rows = s.scalars(
                select(SignalEventRow)
                .where(SignalEventRow.signal_id == signal_id)
                .order_by(SignalEventRow.event_timestamp)
            ).all()
        return [row_to_event(r) for r in rows]
