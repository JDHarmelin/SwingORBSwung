"""all_paper_outcomes aggregation + wallet P&L math."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_engine.app import render_wallet
from trading_engine.core.config import (
    AlertsConfig,
    AppConfig,
    ContractConfig,
    ExecutionConfig,
    FactorWeights,
    LiquidityConfig,
    LoggingConfig,
    RegimeConfig,
    RiskConfig,
    Secrets,
    Settings,
    StorageConfig,
    Universe,
)
from trading_engine.core.types import (
    Direction,
    RiskClass,
    SetupType,
    Signal,
    SignalEvent,
    SignalStatus,
    TargetPlan,
)
from trading_engine.storage import InMemoryRepository

_AS_OF = datetime(2026, 5, 19, 14, 0, tzinfo=UTC)


def _app_config() -> AppConfig:
    settings = Settings(
        liquidity=LiquidityConfig(
            min_price=10.0, min_avg_daily_dollar_volume=10_000_000,
            min_option_open_interest=500, min_option_volume=100,
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
            max_loss_dollars={"standard": 200.0},
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
        execution=ExecutionConfig(),
        logging=LoggingConfig(),
    )
    return AppConfig(
        settings=settings,
        universe=Universe(symbols=["AAA"], indices=["SPY"], sector_etfs={}),
        secrets=Secrets(
            polygon_api_key=None, telegram_bot_token=None,
            telegram_chat_id=None, database_url="sqlite://",
        ),
    )


def _signal(sid: str, symbol: str, setup: SetupType) -> Signal:
    return Signal(
        signal_id=sid, timestamp=_AS_OF, symbol=symbol,
        setup_type=setup, direction=Direction.LONG,
        trigger_price=100.0, stop_price=95.0,
        target_plan=TargetPlan(
            trim1_gain_pct=30.0, trim2_gain_pct=60.0,
            move_stop_to_be_after_trim1=True, runner_trail="8EMA",
            forced_exit_before_event=True,
        ),
        rationale="t", confidence=0.80,
        status=SignalStatus.TRIGGERED, risk_class=RiskClass("standard"),
    )


async def _seed(repo: InMemoryRepository) -> None:
    # win +2.0R, loss -1.0R → net +1.0R.
    await repo.save_signal(_signal("w", "WIN", SetupType.A_BREAKOUT_CONTINUATION))
    await repo.save_signal(_signal("l", "LOS", SetupType.C_EMA_CONTINUATION))
    await repo.append_signal_event(SignalEvent(
        signal_id="w", event_timestamp=_AS_OF, event_type="paper_outcome",
        event_payload={"result": "win", "r_multiple": 2.0, "bars_held": 5, "triggered": True},
    ))
    await repo.append_signal_event(SignalEvent(
        signal_id="l", event_timestamp=_AS_OF, event_type="paper_outcome",
        event_payload={"result": "loss", "r_multiple": -1.0, "bars_held": 3, "triggered": True},
    ))


@pytest.mark.asyncio
async def test_all_paper_outcomes_shape() -> None:
    repo = InMemoryRepository()
    await _seed(repo)
    outcomes = await repo.all_paper_outcomes()
    assert len(outcomes) == 2
    by_id = {o["signal_id"]: o for o in outcomes}
    assert by_id["w"]["result"] == "win"
    assert by_id["w"]["setup_type"] == "A_breakout_continuation"
    assert by_id["l"]["r_multiple"] == -1.0


@pytest.mark.asyncio
async def test_wallet_pnl_math() -> None:
    repo = InMemoryRepository()
    await _seed(repo)
    outcomes = await repo.all_paper_outcomes()
    cfg = _app_config()
    report = render_wallet(outcomes, cfg, starting_balance=10_000.0)

    # net R = +1.0; risk per trade = $200 → +$200 P&L; ending $10,200.
    assert "total R:          +1.00R" in report
    assert "total P&L:        $200.00" in report
    assert "ending balance:   $10,200.00" in report
    assert "win/loss/open:    1/1/0" in report
    assert "win rate:         50.0%" in report
