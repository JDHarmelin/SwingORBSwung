"""confirm_and_alert outbound gating: confidence floor + per-tick cap.

Signals below the floor (or beyond the cap) must still be persisted as
TRIGGERED so paper tracking sees them; only the outbound alert is suppressed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_engine.alerts.sinks import InMemoryAlertSink
from trading_engine.core.config import (
    AlertsConfig,
    ContractConfig,
    ExecutionConfig,
    FactorWeights,
    LiquidityConfig,
    LoggingConfig,
    RegimeConfig,
    RiskConfig,
    Settings,
    StorageConfig,
    Universe,
)
from trading_engine.core.types import (
    Direction,
    RiskClass,
    SetupType,
    Signal,
    SignalStatus,
    TargetPlan,
)
from trading_engine.data.mock_provider import (
    MockEventsProvider,
    MockMarketDataProvider,
    MockOptionsDataProvider,
)
from trading_engine.services.confirmation import AlwaysOnGate
from trading_engine.services.signal_service import SignalService
from trading_engine.storage import InMemoryRepository

_AS_OF = datetime(2026, 5, 19, 14, 0, tzinfo=UTC)


def _settings(*, floor: float = 0.70, cap: int = 5) -> Settings:
    return Settings(
        liquidity=LiquidityConfig(
            min_price=10.0,
            min_avg_daily_dollar_volume=10_000_000,
            min_option_open_interest=500,
            min_option_volume=100,
            max_option_bid_ask_spread_pct=8.0,
        ),
        factor_weights=FactorWeights(
            relative_strength=0.30, sector_strength=0.20, structure=0.20,
            trend=0.15, volume_expansion=0.10, catalyst=0.05,
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
        execution=ExecutionConfig(min_alert_confidence=floor, max_alerts_per_tick=cap),
        logging=LoggingConfig(),
    )


def _signal(sid: str, confidence: float, *, symbol: str = "AAA") -> Signal:
    return Signal(
        signal_id=sid,
        timestamp=_AS_OF,
        symbol=symbol,
        setup_type=SetupType.A_BREAKOUT_CONTINUATION,
        direction=Direction.LONG,
        trigger_price=100.0,
        stop_price=95.0,
        target_plan=TargetPlan(
            trim1_gain_pct=30.0, trim2_gain_pct=60.0,
            move_stop_to_be_after_trim1=True, runner_trail="8EMA",
            forced_exit_before_event=True,
        ),
        rationale="test",
        confidence=confidence,
        status=SignalStatus.PENDING,
        risk_class=RiskClass("standard"),
    )


def _service(settings: Settings, repo: InMemoryRepository, sink: InMemoryAlertSink) -> SignalService:
    return SignalService(
        settings=settings,
        universe=Universe(symbols=["AAA"], indices=["SPY"], sector_etfs={}),
        market_data=MockMarketDataProvider(),
        options_data=MockOptionsDataProvider(),
        events=MockEventsProvider(),
        repo=repo,
        alerts=sink,
    )


@pytest.mark.asyncio
async def test_below_floor_not_sent_but_persisted_triggered() -> None:
    repo = InMemoryRepository()
    sink = InMemoryAlertSink()
    svc = _service(_settings(floor=0.70, cap=5), repo, sink)
    await repo.save_signal(_signal("low", 0.50, symbol="LOW"))
    await repo.save_signal(_signal("high", 0.80, symbol="HIGH"))

    alerted = await svc.confirm_and_alert(AlwaysOnGate(), now=_AS_OF)

    # Only the >= floor signal is alerted.
    assert [a.symbol for a in alerted] == ["HIGH"]
    assert len(sink.messages) == 1

    # But BOTH are persisted as TRIGGERED (tracking unaffected).
    for sid in ("low", "high"):
        s = await repo.get_signal(sid)
        assert s is not None and s.status is SignalStatus.TRIGGERED


@pytest.mark.asyncio
async def test_cap_limits_to_top_n_highest_confidence() -> None:
    repo = InMemoryRepository()
    sink = InMemoryAlertSink()
    svc = _service(_settings(floor=0.70, cap=2), repo, sink)
    for i, conf in enumerate((0.72, 0.99, 0.85, 0.90)):
        await repo.save_signal(_signal(f"s{i}", conf, symbol=f"SY{i}"))

    alerted = await svc.confirm_and_alert(AlwaysOnGate(), now=_AS_OF)

    # Cap=2 → only the two highest-confidence (0.99, 0.90) are sent.
    assert len(alerted) == 2
    assert len(sink.messages) == 2
    assert sorted(a.confidence for a in alerted) == [0.90, 0.99]

    # All four still persisted TRIGGERED.
    for i in range(4):
        s = await repo.get_signal(f"s{i}")
        assert s is not None and s.status is SignalStatus.TRIGGERED
