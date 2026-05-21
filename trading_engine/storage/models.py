"""SQLAlchemy ORM models — mirrors DB outline."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CandleRow(Base):
    __tablename__ = "candles"
    __table_args__ = (Index("ix_candles_sym_tf_ts", "symbol", "timeframe", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)


class MarketRegimeRow(Base):
    __tablename__ = "market_regime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    regime: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    notes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class SectorScoreRow(Base):
    __tablename__ = "sector_scores"
    __table_args__ = (Index("ix_sector_sector_ts", "sector", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sector: Mapped[str] = mapped_column(String(64), nullable=False)
    rs_1d: Mapped[float] = mapped_column(Float, nullable=False)
    rs_5d: Mapped[float] = mapped_column(Float, nullable=False)
    rs_20d: Mapped[float] = mapped_column(Float, nullable=False)
    breadth_score: Mapped[float] = mapped_column(Float, nullable=False)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)


class SymbolScoreRow(Base):
    __tablename__ = "symbol_scores"
    __table_args__ = (Index("ix_symbol_sym_ts", "symbol", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    direction_bucket: Mapped[str] = mapped_column(String(8), nullable=False)
    rs_score: Mapped[float] = mapped_column(Float, nullable=False)
    sector_score: Mapped[float] = mapped_column(Float, nullable=False)
    structure_score: Mapped[float] = mapped_column(Float, nullable=False)
    trend_score: Mapped[float] = mapped_column(Float, nullable=False)
    volume_score: Mapped[float] = mapped_column(Float, nullable=False)
    catalyst_score: Mapped[float] = mapped_column(Float, nullable=False)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class SignalRow(Base):
    __tablename__ = "signals"
    __table_args__ = (Index("ix_signals_status", "status"),)

    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    setup_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    trigger_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_price: Mapped[float] = mapped_column(Float, nullable=False)
    target_plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    contract_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_class: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class SignalEventRow(Base):
    __tablename__ = "signal_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
