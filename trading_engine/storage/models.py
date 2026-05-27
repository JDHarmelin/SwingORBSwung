"""SQLAlchemy models mirroring the DB outline in the spec.

Tables: candles, market_regime, sector_scores, symbol_scores, signals,
signal_events. Long-form columns (notes, reason_codes, payload, contract,
target_plan) are stored as JSON text so the persisted row is the source of
truth for signal replay.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CandleRow(Base):
    __tablename__ = "candles"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)


class MarketRegimeRow(Base):
    __tablename__ = "market_regime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    regime: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    notes_json: Mapped[Any] = mapped_column(JSON, default=list)


class SectorScoreRow(Base):
    __tablename__ = "sector_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    sector: Mapped[str] = mapped_column(String(64), index=True)
    rs_1d: Mapped[float] = mapped_column(Float)
    rs_5d: Mapped[float] = mapped_column(Float)
    rs_20d: Mapped[float] = mapped_column(Float)
    breadth_score: Mapped[float] = mapped_column(Float)
    composite_score: Mapped[float] = mapped_column(Float)


class SymbolScoreRow(Base):
    __tablename__ = "symbol_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    direction_bucket: Mapped[str] = mapped_column(String(8))
    rs_score: Mapped[float] = mapped_column(Float)
    sector_score: Mapped[float] = mapped_column(Float)
    structure_score: Mapped[float] = mapped_column(Float)
    trend_score: Mapped[float] = mapped_column(Float)
    volume_score: Mapped[float] = mapped_column(Float)
    catalyst_score: Mapped[float] = mapped_column(Float)
    composite_score: Mapped[float] = mapped_column(Float)
    reason_codes_json: Mapped[Any] = mapped_column(JSON, default=list)


class SignalRow(Base):
    __tablename__ = "signals"

    signal_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    setup_type: Mapped[str] = mapped_column(String(48))
    direction: Mapped[str] = mapped_column(String(8))
    trigger_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    target_plan_json: Mapped[Any] = mapped_column(JSON)
    contract_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str] = mapped_column(String(1024))
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), index=True)
    risk_class: Mapped[str] = mapped_column(String(16))
    reason_codes_json: Mapped[Any] = mapped_column(JSON, default=list)
    confidence_components_json: Mapped[Any] = mapped_column(JSON, default=dict)
    risk_profile_json: Mapped[Any] = mapped_column(JSON, default=dict)


class SignalEventRow(Base):
    __tablename__ = "signal_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(96), index=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    event_payload_json: Mapped[Any] = mapped_column(JSON, default=dict)


__all__ = [
    "Base",
    "CandleRow",
    "MarketRegimeRow",
    "SectorScoreRow",
    "SignalEventRow",
    "SignalRow",
    "SymbolScoreRow",
]
