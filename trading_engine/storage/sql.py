"""SQLAlchemy-backed ``Repository`` implementation.

Wraps a synchronous SQLAlchemy engine in ``asyncio.to_thread`` so the rest of
the system can stay async without pulling in an async-DB driver. Suitable for
SQLite (default) and any standard sync DB URL.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from trading_engine.core.types import (
    Candle,
    MarketRegime,
    RegimeType,
    SectorScore,
    Signal,
    SignalEvent,
    SignalStatus,
    SymbolScore,
    TargetPlan,
    Timeframe,
)
from trading_engine.storage.models import (
    Base,
    CandleRow,
    MarketRegimeRow,
    SectorScoreRow,
    SignalEventRow,
    SignalRow,
    SymbolScoreRow,
)

_R = TypeVar("_R")


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite DateTime drops tzinfo on store, so naive UTC comes back on read.
    Normalise to tz-aware UTC so downstream tz arithmetic doesn't crash."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Row ↔ domain conversion
# ---------------------------------------------------------------------------


def _candle_to_row(c: Candle) -> CandleRow:
    return CandleRow(
        symbol=c.symbol,
        timeframe=c.timeframe.value,
        timestamp=c.timestamp,
        open=c.open,
        high=c.high,
        low=c.low,
        close=c.close,
        volume=c.volume,
    )


def _row_to_candle(r: CandleRow) -> Candle:
    return Candle(
        symbol=r.symbol,
        timeframe=Timeframe(r.timeframe),
        timestamp=_aware(r.timestamp) or r.timestamp,
        open=r.open,
        high=r.high,
        low=r.low,
        close=r.close,
        volume=r.volume,
    )


def _signal_to_row(s: Signal) -> SignalRow:
    return SignalRow(
        signal_id=s.signal_id,
        timestamp=s.timestamp,
        symbol=s.symbol,
        setup_type=s.setup_type.value,
        direction=s.direction.value,
        trigger_price=s.trigger_price,
        stop_price=s.stop_price,
        target_plan_json=json.loads(s.target_plan.model_dump_json()),
        contract_json=(
            json.loads(s.contract.model_dump_json()) if s.contract is not None else None
        ),
        rationale=s.rationale,
        confidence=s.confidence,
        status=s.status.value,
        risk_class=s.risk_class.value,
        reason_codes_json=list(s.reason_codes),
        confidence_components_json=dict(s.confidence_components),
        risk_profile_json=dict(s.risk_profile),
    )


def _row_to_signal(r: SignalRow) -> Signal:
    from trading_engine.core.types import (
        ContractSuggestion,
        Direction,
        RiskClass,
        SetupType,
    )

    return Signal(
        signal_id=r.signal_id,
        timestamp=_aware(r.timestamp) or r.timestamp,
        symbol=r.symbol,
        setup_type=SetupType(r.setup_type),
        direction=Direction(r.direction),
        trigger_price=r.trigger_price,
        stop_price=r.stop_price,
        target_plan=TargetPlan.model_validate(r.target_plan_json),
        contract=(
            ContractSuggestion.model_validate(r.contract_json)
            if r.contract_json is not None
            else None
        ),
        rationale=r.rationale,
        confidence=r.confidence,
        status=SignalStatus(r.status),
        risk_class=RiskClass(r.risk_class),
        reason_codes=list(r.reason_codes_json or []),
        confidence_components=dict(r.confidence_components_json or {}),
        risk_profile=dict(r.risk_profile_json or {}),
    )


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class SqlRepository:
    """Sync SQLAlchemy implementation wrapped in ``asyncio.to_thread``."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self._engine: Engine = create_engine(database_url, echo=echo, future=True)
        Base.metadata.create_all(self._engine)
        self._migrate_signals_confidence_components()
        self._migrate_signals_risk_profile()
        self._Session: sessionmaker[Session] = sessionmaker(self._engine, expire_on_commit=False)

    def _migrate_signals_confidence_components(self) -> None:
        """Add ``confidence_components_json`` to pre-existing ``signals`` tables.

        ``create_all`` won't ALTER an existing table, so SQLite DBs created
        before this column was added need a one-shot patch. No-op when the
        column is already present or when the dialect rejects the introspect.
        """
        from sqlalchemy import inspect, text

        try:
            inspector = inspect(self._engine)
            if "signals" not in inspector.get_table_names():
                return
            cols = {c["name"] for c in inspector.get_columns("signals")}
            if "confidence_components_json" in cols:
                return
            with self._engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE signals ADD COLUMN confidence_components_json JSON")
                )
        except Exception:
            # Best-effort migration: an unsupported dialect just skips and the
            # default empty dict path keeps reads working.
            return

    def _migrate_signals_risk_profile(self) -> None:
        """Add ``risk_profile_json`` to pre-existing ``signals`` tables.

        Mirrors the confidence_components patch above — ``create_all`` won't
        ALTER an existing table, so older SQLite DBs need a one-shot patch.
        """
        from sqlalchemy import inspect, text

        try:
            inspector = inspect(self._engine)
            if "signals" not in inspector.get_table_names():
                return
            cols = {c["name"] for c in inspector.get_columns("signals")}
            if "risk_profile_json" in cols:
                return
            with self._engine.begin() as conn:
                conn.execute(text("ALTER TABLE signals ADD COLUMN risk_profile_json JSON"))
        except Exception:
            return

    # ------------- helpers -----------------------------------------------
    def _session(self) -> Session:
        return self._Session()

    async def _run(self, fn: Callable[..., _R], *args: Any) -> _R:
        return await asyncio.to_thread(fn, *args)

    # ------------- candles -----------------------------------------------
    def _upsert_candles_sync(self, candles: list[Candle]) -> None:
        with self._session() as s:
            for c in candles:
                existing = (
                    s.query(CandleRow)
                    .filter_by(symbol=c.symbol, timeframe=c.timeframe.value, timestamp=c.timestamp)
                    .one_or_none()
                )
                if existing is None:
                    s.add(_candle_to_row(c))
                else:
                    existing.open = c.open
                    existing.high = c.high
                    existing.low = c.low
                    existing.close = c.close
                    existing.volume = c.volume
            s.commit()

    async def upsert_candles(self, candles: list[Candle]) -> None:
        if not candles:
            return
        await self._run(self._upsert_candles_sync, candles)

    def _get_candles_sync(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        with self._session() as s:
            rows = (
                s.execute(
                    select(CandleRow)
                    .where(CandleRow.symbol == symbol)
                    .where(CandleRow.timeframe == timeframe.value)
                    .where(CandleRow.timestamp >= start)
                    .where(CandleRow.timestamp <= end)
                    .order_by(CandleRow.timestamp.asc())
                )
                .scalars()
                .all()
            )
        return [_row_to_candle(r) for r in rows]

    async def get_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        return await self._run(self._get_candles_sync, symbol, timeframe, start, end)

    # ------------- market_regime -----------------------------------------
    def _save_regime_sync(self, regime: MarketRegime) -> None:
        with self._session() as s:
            s.add(
                MarketRegimeRow(
                    timestamp=regime.timestamp,
                    regime=regime.regime.value,
                    confidence=regime.confidence,
                    notes_json=list(regime.notes),
                )
            )
            s.commit()

    async def save_regime(self, regime: MarketRegime) -> None:
        await self._run(self._save_regime_sync, regime)

    def _latest_regime_sync(self) -> MarketRegime | None:
        with self._session() as s:
            row = s.execute(
                select(MarketRegimeRow).order_by(MarketRegimeRow.timestamp.desc()).limit(1)
            ).scalar_one_or_none()
        if row is None:
            return None
        return MarketRegime(
            timestamp=_aware(row.timestamp) or row.timestamp,
            regime=RegimeType(row.regime),
            confidence=row.confidence,
            notes=list(row.notes_json or []),
        )

    async def latest_regime(self) -> MarketRegime | None:
        return await self._run(self._latest_regime_sync)

    # ------------- sector_scores -----------------------------------------
    def _save_sector_scores_sync(self, scores: list[SectorScore]) -> None:
        with self._session() as s:
            s.add_all(
                SectorScoreRow(
                    timestamp=sc.timestamp,
                    sector=sc.sector,
                    rs_1d=sc.rs_1d,
                    rs_5d=sc.rs_5d,
                    rs_20d=sc.rs_20d,
                    breadth_score=sc.breadth_score,
                    composite_score=sc.composite_score,
                )
                for sc in scores
            )
            s.commit()

    async def save_sector_scores(self, scores: list[SectorScore]) -> None:
        if not scores:
            return
        await self._run(self._save_sector_scores_sync, scores)

    def _latest_sector_scores_sync(self) -> list[SectorScore]:
        with self._session() as s:
            latest_ts = s.execute(
                select(SectorScoreRow.timestamp)
                .order_by(SectorScoreRow.timestamp.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_ts is None:
                return []
            rows = (
                s.execute(select(SectorScoreRow).where(SectorScoreRow.timestamp == latest_ts))
                .scalars()
                .all()
            )
        return [
            SectorScore(
                timestamp=_aware(r.timestamp) or r.timestamp,
                sector=r.sector,
                rs_1d=r.rs_1d,
                rs_5d=r.rs_5d,
                rs_20d=r.rs_20d,
                breadth_score=r.breadth_score,
                composite_score=r.composite_score,
            )
            for r in rows
        ]

    async def latest_sector_scores(self) -> list[SectorScore]:
        return await self._run(self._latest_sector_scores_sync)

    # ------------- symbol_scores -----------------------------------------
    def _save_symbol_scores_sync(self, scores: list[SymbolScore]) -> None:
        with self._session() as s:
            s.add_all(
                SymbolScoreRow(
                    timestamp=sc.timestamp,
                    symbol=sc.symbol,
                    direction_bucket=sc.direction_bucket.value,
                    rs_score=sc.rs_score,
                    sector_score=sc.sector_score,
                    structure_score=sc.structure_score,
                    trend_score=sc.trend_score,
                    volume_score=sc.volume_score,
                    catalyst_score=sc.catalyst_score,
                    composite_score=sc.composite_score,
                    reason_codes_json=list(sc.reason_codes),
                )
                for sc in scores
            )
            s.commit()

    async def save_symbol_scores(self, scores: list[SymbolScore]) -> None:
        if not scores:
            return
        await self._run(self._save_symbol_scores_sync, scores)

    def _latest_symbol_scores_sync(self) -> list[SymbolScore]:
        from trading_engine.core.types import Direction

        with self._session() as s:
            latest_ts = s.execute(
                select(SymbolScoreRow.timestamp)
                .order_by(SymbolScoreRow.timestamp.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_ts is None:
                return []
            rows = (
                s.execute(select(SymbolScoreRow).where(SymbolScoreRow.timestamp == latest_ts))
                .scalars()
                .all()
            )
        return [
            SymbolScore(
                timestamp=_aware(r.timestamp) or r.timestamp,
                symbol=r.symbol,
                direction_bucket=Direction(r.direction_bucket),
                rs_score=r.rs_score,
                sector_score=r.sector_score,
                structure_score=r.structure_score,
                trend_score=r.trend_score,
                volume_score=r.volume_score,
                catalyst_score=r.catalyst_score,
                composite_score=r.composite_score,
                reason_codes=list(r.reason_codes_json or []),
            )
            for r in rows
        ]

    async def latest_symbol_scores(self) -> list[SymbolScore]:
        return await self._run(self._latest_symbol_scores_sync)

    # ------------- signals + events --------------------------------------
    def _save_signal_sync(self, signal: Signal) -> None:
        with self._session() as s:
            existing = s.get(SignalRow, signal.signal_id)
            row = _signal_to_row(signal)
            if existing is None:
                s.add(row)
            else:
                for col in (
                    "timestamp", "symbol", "setup_type", "direction", "trigger_price",
                    "stop_price", "target_plan_json", "contract_json", "rationale",
                    "confidence", "status", "risk_class", "reason_codes_json",
                    "confidence_components_json",
                    "risk_profile_json",
                ):
                    setattr(existing, col, getattr(row, col))
            s.commit()

    async def save_signal(self, signal: Signal) -> None:
        await self._run(self._save_signal_sync, signal)

    def _get_signal_sync(self, signal_id: str) -> Signal | None:
        with self._session() as s:
            row = s.get(SignalRow, signal_id)
            if row is None:
                return None
            return _row_to_signal(row)

    async def get_signal(self, signal_id: str) -> Signal | None:
        return await self._run(self._get_signal_sync, signal_id)

    def _open_signals_sync(self) -> list[Signal]:
        with self._session() as s:
            rows = (
                s.execute(
                    select(SignalRow).where(
                        SignalRow.status.in_(
                            [SignalStatus.PENDING.value, SignalStatus.TRIGGERED.value,
                             SignalStatus.TRIMMED.value]
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [_row_to_signal(r) for r in rows]

    async def open_signals(self) -> list[Signal]:
        return await self._run(self._open_signals_sync)

    def _append_event_sync(self, event: SignalEvent) -> None:
        with self._session() as s:
            s.add(
                SignalEventRow(
                    signal_id=event.signal_id,
                    event_timestamp=event.event_timestamp,
                    event_type=event.event_type,
                    event_payload_json=dict(event.event_payload),
                )
            )
            s.commit()

    async def append_signal_event(self, event: SignalEvent) -> None:
        await self._run(self._append_event_sync, event)

    def _list_events_sync(self, signal_id: str) -> list[SignalEvent]:
        with self._session() as s:
            rows = (
                s.execute(
                    select(SignalEventRow)
                    .where(SignalEventRow.signal_id == signal_id)
                    .order_by(SignalEventRow.event_timestamp.asc())
                )
                .scalars()
                .all()
            )
        return [
            SignalEvent(
                signal_id=r.signal_id,
                event_timestamp=_aware(r.event_timestamp) or r.event_timestamp,
                event_type=r.event_type,
                event_payload=dict(r.event_payload_json or {}),
            )
            for r in rows
        ]

    async def list_signal_events(self, signal_id: str) -> list[SignalEvent]:
        return await self._run(self._list_events_sync, signal_id)


__all__ = ["SqlRepository"]
