"""Storage round-trip tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from trading_engine.core.types import (
    Direction,
    MarketRegime,
    RegimeType,
    SectorScore,
    SetupType,
    Signal,
    SignalEvent,
    SignalStatus,
    SymbolScore,
    TargetPlan,
    Timeframe,
)
from trading_engine.storage.db import init_schema, session_factory
from trading_engine.storage.repository import SqlRepository
from trading_engine.testing.synthetic import clean_uptrend_series


@pytest.fixture
def repo() -> SqlRepository:
    engine = create_engine("sqlite:///:memory:")
    init_schema(engine)
    return SqlRepository(engine=engine, session_maker=session_factory(engine))


@pytest.mark.asyncio
async def test_candle_round_trip(repo: SqlRepository) -> None:
    series = clean_uptrend_series("TST", Timeframe.D1, n=10)
    candles = series.candles
    await repo.upsert_candles(candles)
    start, end = candles[0].timestamp, candles[-1].timestamp
    loaded = await repo.get_candles("TST", Timeframe.D1, start, end)
    assert len(loaded) == len(candles)
    assert loaded[-1].close == candles[-1].close


@pytest.mark.asyncio
async def test_regime_round_trip(repo: SqlRepository) -> None:
    regime = MarketRegime(
        timestamp=datetime.now(tz=UTC),
        regime=RegimeType.LONG_BIAS,
        confidence=0.8,
        notes=["QQQ above VWAP"],
    )
    await repo.save_regime(regime)
    loaded = await repo.latest_regime()
    assert loaded is not None
    assert loaded.regime == RegimeType.LONG_BIAS


@pytest.mark.asyncio
async def test_signal_and_events(repo: SqlRepository) -> None:
    sig = Signal(
        signal_id="sig-1",
        timestamp=datetime.now(tz=UTC),
        symbol="UPTRD",
        setup_type=SetupType.A_BREAKOUT_CONTINUATION,
        direction=Direction.LONG,
        trigger_price=100.0,
        stop_price=95.0,
        target_plan=TargetPlan(),
        rationale="test",
        confidence=0.75,
        status=SignalStatus.PENDING,
    )
    await repo.save_signal(sig)
    sig.status = SignalStatus.TRIGGERED
    await repo.save_signal(sig)
    loaded = await repo.get_signal("sig-1")
    assert loaded is not None
    assert loaded.status == SignalStatus.TRIGGERED

    ev = SignalEvent(
        signal_id="sig-1",
        event_timestamp=datetime.now(tz=UTC),
        event_type="trim1",
        event_payload={"gain_pct": 30},
    )
    await repo.append_signal_event(ev)
    events = await repo.list_signal_events("sig-1")
    assert len(events) == 1


@pytest.mark.asyncio
async def test_scores_round_trip(repo: SqlRepository) -> None:
    ts = datetime.now(tz=UTC)
    sector = SectorScore(
        timestamp=ts,
        sector="tech",
        rs_1d=1.0,
        rs_5d=2.0,
        rs_20d=3.0,
        breadth_score=0.7,
        composite_score=0.8,
    )
    await repo.save_sector_scores([sector])
    loaded_s = await repo.latest_sector_scores()
    assert len(loaded_s) == 1

    sym = SymbolScore(
        timestamp=ts,
        symbol="UPTRD",
        direction_bucket=Direction.LONG,
        rs_score=0.8,
        sector_score=0.7,
        structure_score=0.6,
        trend_score=0.9,
        volume_score=0.5,
        catalyst_score=0.0,
        composite_score=0.75,
        reason_codes=["rs_positive"],
    )
    await repo.save_symbol_scores([sym])
    loaded = await repo.latest_symbol_scores()
    assert loaded[0].symbol == "UPTRD"
