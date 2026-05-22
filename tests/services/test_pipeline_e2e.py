"""End-to-end: full pipeline against mock providers + in-memory repo."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_engine.alerts.sinks import InMemoryAlertSink
from trading_engine.core.config import (
    AlertsConfig,
    ContractConfig,
    FactorWeights,
    LiquidityConfig,
    LoggingConfig,
    RegimeConfig,
    RiskConfig,
    Settings,
    StorageConfig,
    Universe,
)
from trading_engine.data.mock_provider import (
    MockEventsProvider,
    MockMarketDataProvider,
    MockOptionsDataProvider,
)
from trading_engine.services.confirmation import AlwaysOnGate
from trading_engine.services.management_service import ManagementService
from trading_engine.services.signal_service import SignalService
from trading_engine.storage import InMemoryRepository

_AS_OF = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        liquidity=LiquidityConfig(
            min_price=10.0,
            min_avg_daily_dollar_volume=10_000_000,
            min_option_open_interest=500,
            min_option_volume=100,
            max_option_bid_ask_spread_pct=8.0,
        ),
        factor_weights=FactorWeights(
            relative_strength=0.30,
            sector_strength=0.20,
            structure=0.20,
            trend=0.15,
            volume_expansion=0.10,
            catalyst=0.05,
        ),
        risk=RiskConfig(
            trim1_gain_pct=30.0, trim2_gain_pct=60.0,
            move_stop_to_be_after_trim1=True, runner_trail="8EMA",
            forced_exit_before_event=True,
        ),
        contract=ContractConfig(
            swing_dte_min=14, swing_dte_max=45, day_dte_min=0, day_dte_max=7,
            delta_target_min=0.30, delta_target_max=0.45, lotto_delta_max=0.20,
            reject_if_spread_pct_above=8.0,
        ),
        regime=RegimeConfig(
            vwap_lookback_min=30, emas=[8, 20, 50],
            block_if_event_within_hours=4, index_symbols=["SPY", "QQQ"],
        ),
        storage=StorageConfig(),
        alerts=AlertsConfig(),
        logging=LoggingConfig(),
    )


def _universe() -> Universe:
    return Universe(
        # Mix the synthetic symbols so the mock provider has matching shapes.
        symbols=["UPTRD", "PB8", "FLAG", "BRKD"],
        indices=["SPY", "QQQ"],
        sector_etfs={"semis": "SMH", "energy": "XLE"},
    )


@pytest.fixture
def services():
    settings = _settings()
    universe = _universe()
    sink = InMemoryAlertSink()
    repo = InMemoryRepository()
    md, od, ev = (MockMarketDataProvider(), MockOptionsDataProvider(), MockEventsProvider())
    signal_service = SignalService(
        settings=settings, universe=universe,
        market_data=md, options_data=od, events=ev,
        repo=repo, alerts=sink,
    )
    mgmt_service = ManagementService(options_data=od, repo=repo, alerts=sink)
    return signal_service, mgmt_service, repo, sink


@pytest.mark.asyncio
async def test_pipeline_persists_candidates_without_alerting(services) -> None:
    signal_service, _mgmt, repo, sink = services
    result = await signal_service.run_pipeline(_AS_OF)

    # Regime + scores persisted.
    assert await repo.latest_regime() is not None
    assert await repo.latest_sector_scores()
    assert await repo.latest_symbol_scores()

    # Candidates persisted but no alert dispatched (execution-only contract).
    assert len(result.candidates) >= 1
    persisted = await repo.get_signal(result.candidates[0].signal_id)
    assert persisted is not None
    assert sink.messages == []


@pytest.mark.asyncio
async def test_confirm_and_alert_fires_only_after_gate(services) -> None:
    signal_service, _mgmt, repo, sink = services
    result = await signal_service.run_pipeline(_AS_OF)
    assert sink.messages == []  # silent generation phase

    # AlwaysOnGate confirms every candidate → all should alert exactly once.
    # Pin ``now`` to _AS_OF so candidates aren't flagged stale by wall-clock.
    alerted = await signal_service.confirm_and_alert(AlwaysOnGate(), now=_AS_OF)
    assert len(alerted) == len(result.candidates)
    assert len(sink.messages) == len(result.candidates)

    # All triggered signals were transitioned in storage.
    for a in alerted:
        s = await repo.get_signal(a.signal_id)
        assert s is not None and s.status.value == "triggered"

    # Idempotent: re-running finds no more PENDING.
    again = await signal_service.confirm_and_alert(AlwaysOnGate(), now=_AS_OF)
    assert again == []


@pytest.mark.asyncio
async def test_expire_stale_candidates(services) -> None:
    signal_service, _mgmt, repo, _sink = services
    await signal_service.run_pipeline(_AS_OF)

    # Force the TTL to 0 hours so every candidate is instantly stale.
    signal_service.settings = signal_service.settings.model_copy(
        update={
            "execution": signal_service.settings.execution.model_copy(
                update={"candidate_ttl_hours": 0}
            )
        }
    )
    expired_ids = await signal_service.expire_stale_candidates()
    assert expired_ids
    for sid in expired_ids:
        sig = await repo.get_signal(sid)
        assert sig is not None and sig.status.value == "expired_risk"


@pytest.mark.asyncio
async def test_no_signals_when_universe_empty(services) -> None:
    signal_service, _mgmt, _repo, sink = services
    signal_service.settings = signal_service.settings.model_copy(
        update={"liquidity": signal_service.settings.liquidity.model_copy(
            update={"min_avg_daily_dollar_volume": 1e15}
        )}
    )
    result = await signal_service.run_pipeline(_AS_OF)
    assert result.candidates == []
    assert sink.messages == []
