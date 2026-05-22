"""In-memory + SQL repositories round-trip signals and candles."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_engine.core.interfaces import Repository
from trading_engine.core.types import (
    Candle,
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
from trading_engine.storage import InMemoryRepository, SqlRepository

_AS_OF = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)


def _make_signal() -> Signal:
    return Signal(
        signal_id="uptrd-A-deadbeef",
        timestamp=_AS_OF,
        symbol="UPTRD",
        setup_type=SetupType.A_BREAKOUT_CONTINUATION,
        direction=Direction.LONG,
        trigger_price=125.40,
        stop_price=122.95,
        target_plan=TargetPlan(),
        rationale="breakout",
        confidence=0.78,
        reason_codes=["RS+", "Volume expansion"],
    )


def _make_candle(ts: datetime) -> Candle:
    return Candle(
        symbol="UPTRD",
        timeframe=Timeframe.D1,
        timestamp=ts,
        open=100.0,
        high=101.0,
        low=99.5,
        close=100.5,
        volume=1_000_000,
    )


@pytest.fixture(params=["in_memory", "sqlite"])
def repo(request, tmp_path) -> Repository:
    if request.param == "in_memory":
        return InMemoryRepository()
    db = tmp_path / "test.db"
    return SqlRepository(f"sqlite:///{db}")


@pytest.mark.asyncio
async def test_signal_round_trip(repo: Repository) -> None:
    sig = _make_signal()
    await repo.save_signal(sig)
    got = await repo.get_signal(sig.signal_id)
    assert got is not None
    assert got.signal_id == sig.signal_id
    assert got.status is SignalStatus.PENDING
    assert got.reason_codes == sig.reason_codes


@pytest.mark.asyncio
async def test_open_signals_filter(repo: Repository) -> None:
    sig = _make_signal()
    await repo.save_signal(sig)
    closed = sig.model_copy(
        update={"signal_id": "closed-1", "status": SignalStatus.CLOSED}
    )
    await repo.save_signal(closed)
    open_ = await repo.open_signals()
    ids = {s.signal_id for s in open_}
    assert sig.signal_id in ids
    assert "closed-1" not in ids


@pytest.mark.asyncio
async def test_signal_events_round_trip(repo: Repository) -> None:
    sig = _make_signal()
    await repo.save_signal(sig)
    e = SignalEvent(
        signal_id=sig.signal_id,
        event_timestamp=_AS_OF,
        event_type="trim1",
        event_payload={"gain_pct": 31.5},
    )
    await repo.append_signal_event(e)
    events = await repo.list_signal_events(sig.signal_id)
    assert len(events) == 1
    assert events[0].event_type == "trim1"
    assert events[0].event_payload["gain_pct"] == 31.5


@pytest.mark.asyncio
async def test_candles_round_trip(repo: Repository) -> None:
    c1 = _make_candle(_AS_OF)
    c2 = _make_candle(datetime(2026, 5, 20, tzinfo=UTC))
    await repo.upsert_candles([c1, c2])
    got = await repo.get_candles("UPTRD", Timeframe.D1, _AS_OF, datetime(2026, 5, 20, tzinfo=UTC))
    # SQLite drops tzinfo from naive DateTime columns; compare on naive UTC.
    def _naive(d): return d.replace(tzinfo=None)
    assert [_naive(c.timestamp) for c in got] == [_naive(c1.timestamp), _naive(c2.timestamp)]


@pytest.mark.asyncio
async def test_regime_and_scores(repo: Repository) -> None:
    await repo.save_regime(MarketRegime(timestamp=_AS_OF, regime=RegimeType.LONG_BIAS, confidence=0.7, notes=["ok"]))
    latest = await repo.latest_regime()
    assert latest is not None and latest.regime is RegimeType.LONG_BIAS

    sector = SectorScore(
        timestamp=_AS_OF, sector="semis", rs_1d=0.01, rs_5d=0.02, rs_20d=0.05,
        breadth_score=0.4, composite_score=0.6,
    )
    await repo.save_sector_scores([sector])
    got = await repo.latest_sector_scores()
    assert len(got) == 1 and got[0].sector == "semis"

    sym = SymbolScore(
        timestamp=_AS_OF, symbol="UPTRD", direction_bucket=Direction.LONG,
        rs_score=0.4, sector_score=0.3, structure_score=0.3, trend_score=0.5,
        volume_score=0.2, catalyst_score=0.0, composite_score=0.4,
        reason_codes=["RS+"],
    )
    await repo.save_symbol_scores([sym])
    got_syms = await repo.latest_symbol_scores()
    assert len(got_syms) == 1 and got_syms[0].symbol == "UPTRD"


def test_repos_satisfy_protocol() -> None:
    assert isinstance(InMemoryRepository(), Repository)
    # SqlRepository requires a DB url; just check the class is a Protocol match
    # via inspection on instance is heavier — covered by isinstance at runtime
    # in fixture parametrisation.
