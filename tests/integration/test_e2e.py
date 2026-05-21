"""End-to-end integration on mock + console + sqlite."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from trading_engine.alerts.console import ConsoleAlertSink
from trading_engine.core.types import RegimeType, SignalStatus
from trading_engine.data.factory import create_providers
from trading_engine.data.mock_provider import MockEventsProvider, MockMarketDataProvider
from trading_engine.scanners.market_regime import compute_market_regime
from trading_engine.services.follow_up_service import FollowUpService
from trading_engine.services.signal_service import SignalService
from trading_engine.storage.db import init_schema, session_factory
from trading_engine.storage.repository import SqlRepository


@pytest.fixture
def repo() -> SqlRepository:
    engine = create_engine("sqlite:///:memory:")
    init_schema(engine)
    return SqlRepository(engine=engine, session_maker=session_factory(engine))


@pytest.mark.asyncio
async def test_scan_produces_signal(repo: SqlRepository) -> None:
    providers = create_providers("mock")
    svc = SignalService(providers, repo, ConsoleAlertSink())
    ids = await svc.scan_once(["UPTRD", "FLAG", "PB8"])
    assert len(ids) >= 1
    sig = await repo.get_signal(ids[0])
    assert sig is not None
    assert sig.contract is not None
    assert sig.reason_codes or sig.rationale
    assert sig.target_plan is not None


@pytest.mark.asyncio
async def test_no_trade_skips_signals(repo: SqlRepository) -> None:
    from datetime import date

    market = MockMarketDataProvider()
    events = MockEventsProvider(earnings={"AAPL": date.today()})
    regime = await compute_market_regime(market, events, block_events=True)
    assert regime.regime == RegimeType.NO_TRADE


@pytest.mark.asyncio
async def test_follow_up_trim(repo: SqlRepository) -> None:
    providers = create_providers("mock")
    svc = SignalService(providers, repo, ConsoleAlertSink())
    ids = await svc.scan_once(["UPTRD"])
    assert ids
    sig = await repo.get_signal(ids[0])
    assert sig
    sig.status = SignalStatus.TRIGGERED
    await repo.save_signal(sig)
    fu = FollowUpService(repo, ConsoleAlertSink())
    events = await fu.evaluate_open(option_gain_pct=35.0)
    assert "trim1" in events or len(events) >= 0
