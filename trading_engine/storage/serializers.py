"""Round-trip conversion: core.types ↔ ORM rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from trading_engine.core.types import (
    Candle,
    ContractSuggestion,
    Direction,
    MarketRegime,
    RegimeType,
    RiskClass,
    SectorScore,
    SetupType,
    Signal,
    SignalEvent,
    SignalStatus,
    SymbolScore,
    TargetPlan,
    Timeframe,
)
from trading_engine.storage.models import (
    CandleRow,
    MarketRegimeRow,
    SectorScoreRow,
    SignalEventRow,
    SignalRow,
    SymbolScoreRow,
)


def _dt(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def candle_to_row(c: Candle) -> CandleRow:
    return CandleRow(
        symbol=c.symbol,
        timeframe=c.timeframe.value if hasattr(c.timeframe, "value") else str(c.timeframe),
        timestamp=_dt(c.timestamp),
        open=c.open,
        high=c.high,
        low=c.low,
        close=c.close,
        volume=c.volume,
    )


def row_to_candle(r: CandleRow) -> Candle:
    return Candle(
        symbol=r.symbol,
        timeframe=Timeframe(r.timeframe),
        timestamp=r.timestamp,
        open=r.open,
        high=r.high,
        low=r.low,
        close=r.close,
        volume=r.volume,
    )


def regime_to_row(r: MarketRegime) -> MarketRegimeRow:
    return MarketRegimeRow(
        timestamp=_dt(r.timestamp),
        regime=r.regime.value if hasattr(r.regime, "value") else str(r.regime),
        confidence=r.confidence,
        notes_json=json.dumps(r.notes),
    )


def row_to_regime(r: MarketRegimeRow) -> MarketRegime:
    return MarketRegime(
        timestamp=r.timestamp,
        regime=RegimeType(r.regime),
        confidence=r.confidence,
        notes=json.loads(r.notes_json),
    )


def sector_to_row(s: SectorScore) -> SectorScoreRow:
    return SectorScoreRow(
        timestamp=_dt(s.timestamp),
        sector=s.sector,
        rs_1d=s.rs_1d,
        rs_5d=s.rs_5d,
        rs_20d=s.rs_20d,
        breadth_score=s.breadth_score,
        composite_score=s.composite_score,
    )


def row_to_sector(r: SectorScoreRow) -> SectorScore:
    return SectorScore(
        timestamp=r.timestamp,
        sector=r.sector,
        rs_1d=r.rs_1d,
        rs_5d=r.rs_5d,
        rs_20d=r.rs_20d,
        breadth_score=r.breadth_score,
        composite_score=r.composite_score,
    )


def symbol_to_row(s: SymbolScore) -> SymbolScoreRow:
    return SymbolScoreRow(
        timestamp=_dt(s.timestamp),
        symbol=s.symbol,
        direction_bucket=s.direction_bucket.value
        if hasattr(s.direction_bucket, "value")
        else str(s.direction_bucket),
        rs_score=s.rs_score,
        sector_score=s.sector_score,
        structure_score=s.structure_score,
        trend_score=s.trend_score,
        volume_score=s.volume_score,
        catalyst_score=s.catalyst_score,
        composite_score=s.composite_score,
        reason_codes_json=json.dumps(s.reason_codes),
    )


def row_to_symbol(r: SymbolScoreRow) -> SymbolScore:
    return SymbolScore(
        timestamp=r.timestamp,
        symbol=r.symbol,
        direction_bucket=Direction(r.direction_bucket),
        rs_score=r.rs_score,
        sector_score=r.sector_score,
        structure_score=r.structure_score,
        trend_score=r.trend_score,
        volume_score=r.volume_score,
        catalyst_score=r.catalyst_score,
        composite_score=r.composite_score,
        reason_codes=json.loads(r.reason_codes_json),
    )


def signal_to_row(s: Signal) -> SignalRow:
    return SignalRow(
        signal_id=s.signal_id,
        timestamp=_dt(s.timestamp),
        symbol=s.symbol,
        setup_type=s.setup_type.value if hasattr(s.setup_type, "value") else str(s.setup_type),
        direction=s.direction.value if hasattr(s.direction, "value") else str(s.direction),
        trigger_price=s.trigger_price,
        stop_price=s.stop_price,
        target_plan_json=s.target_plan.model_dump_json(),
        contract_json=s.contract.model_dump_json() if s.contract else None,
        rationale_text=s.rationale,
        confidence=s.confidence,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        risk_class=s.risk_class.value if hasattr(s.risk_class, "value") else str(s.risk_class),
        reason_codes_json=json.dumps(s.reason_codes),
    )


def row_to_signal(r: SignalRow) -> Signal:
    contract = ContractSuggestion.model_validate_json(r.contract_json) if r.contract_json else None
    return Signal(
        signal_id=r.signal_id,
        timestamp=r.timestamp,
        symbol=r.symbol,
        setup_type=SetupType(r.setup_type),
        direction=Direction(r.direction),
        trigger_price=r.trigger_price,
        stop_price=r.stop_price,
        target_plan=TargetPlan.model_validate_json(r.target_plan_json),
        contract=contract,
        rationale=r.rationale_text,
        confidence=r.confidence,
        status=SignalStatus(r.status),
        risk_class=RiskClass(r.risk_class),
        reason_codes=json.loads(r.reason_codes_json),
    )


def event_to_row(e: SignalEvent) -> SignalEventRow:
    return SignalEventRow(
        signal_id=e.signal_id,
        event_timestamp=_dt(e.event_timestamp),
        event_type=e.event_type,
        event_payload_json=json.dumps(e.event_payload),
    )


def row_to_event(r: SignalEventRow) -> SignalEvent:
    return SignalEvent(
        signal_id=r.signal_id,
        event_timestamp=r.event_timestamp,
        event_type=r.event_type,
        event_payload=json.loads(r.event_payload_json),
    )
