"""Contract selection + trade management."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_engine.core.config import ContractConfig, LiquidityConfig, RiskConfig
from trading_engine.core.types import (
    Direction,
    RiskClass,
    SetupType,
    Signal,
    SignalStatus,
)
from trading_engine.risk.contract_selector import list_rejections, select_contract
from trading_engine.risk.position_sizing import suggest_size
from trading_engine.risk.trade_management import (
    ManagementUpdate,
    apply_event,
    build_target_plan,
    classify_risk,
    follow_up_events,
)

_AS_OF = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)


_LIQ = LiquidityConfig(
    min_price=10.0,
    min_avg_daily_dollar_volume=10_000_000,
    min_option_open_interest=500,
    min_option_volume=100,
    max_option_bid_ask_spread_pct=8.0,
)

_CFG = ContractConfig(
    swing_dte_min=14,
    swing_dte_max=45,
    day_dte_min=0,
    day_dte_max=7,
    delta_target_min=0.30,
    delta_target_max=0.45,
    lotto_delta_max=0.20,
    reject_if_spread_pct_above=8.0,
)

_RISK = RiskConfig(
    trim1_gain_pct=30.0,
    trim2_gain_pct=60.0,
    move_stop_to_be_after_trim1=True,
    runner_trail="8EMA",
    forced_exit_before_event=True,
)


def _signal() -> Signal:
    return Signal(
        signal_id="x-1",
        timestamp=_AS_OF,
        symbol="UPTRD",
        setup_type=SetupType.A_BREAKOUT_CONTINUATION,
        direction=Direction.LONG,
        trigger_price=125.0,
        stop_price=122.0,
        target_plan=build_target_plan(_RISK),
        rationale="test",
        confidence=0.7,
    )


def test_select_contract_picks_target_delta_call(option_chain) -> None:
    pick = select_contract(
        option_chain,
        direction=Direction.LONG,
        as_of=_AS_OF.date(),
        contract_cfg=_CFG,
        liquidity=_LIQ,
    )
    assert pick is not None
    assert pick.direction == "long_call"
    assert pick.delta is not None and 0.25 <= pick.delta <= 0.50
    assert pick.classification == "standard_swing"


def test_select_contract_picks_put_for_short(option_chain) -> None:
    pick = select_contract(
        option_chain,
        direction=Direction.SHORT,
        as_of=_AS_OF.date(),
        contract_cfg=_CFG,
        liquidity=_LIQ,
    )
    assert pick is not None
    assert pick.direction == "long_put"
    assert pick.delta is not None and -0.50 <= pick.delta <= -0.25


def test_illiquid_contract_rejected(option_chain) -> None:
    rejections = list_rejections(option_chain, _LIQ)
    # The fixture contains exactly one deliberately illiquid contract.
    assert len(rejections) == 1
    assert any("OI" in r or "spread" in r for r in rejections[0].reasons)


def test_classify_risk_band() -> None:
    assert classify_risk(0.9) is RiskClass.A_PLUS
    assert classify_risk(0.6) is RiskClass.STANDARD
    assert classify_risk(0.3) is RiskClass.LOTTO
    assert classify_risk(0.6, hedge=True) is RiskClass.HEDGE


def test_follow_up_events_trim_then_be() -> None:
    sig = _signal()
    update = ManagementUpdate(
        signal=sig,
        timestamp=_AS_OF,
        option_entry_price=1.00,
        option_current_price=1.35,  # +35%
    )
    events = follow_up_events(update, already_emitted=set())
    types = [e.event_type for e in events]
    assert "trim1" in types
    assert "be_moved" in types


def test_follow_up_events_dedupes() -> None:
    sig = _signal()
    update = ManagementUpdate(
        signal=sig, timestamp=_AS_OF, option_entry_price=1.00, option_current_price=1.35
    )
    events = follow_up_events(update, already_emitted={"trim1", "be_moved"})
    assert events == []


def test_follow_up_stop_hit_blocks_further_events() -> None:
    sig = _signal()
    update = ManagementUpdate(
        signal=sig,
        timestamp=_AS_OF,
        option_entry_price=1.00,
        option_current_price=0.30,
        stop_hit=True,
    )
    events = follow_up_events(update, already_emitted=set())
    assert [e.event_type for e in events] == ["stop_hit"]


def test_apply_event_advances_status() -> None:
    from trading_engine.core.types import SignalEvent

    sig = _signal()
    triggered = apply_event(sig, SignalEvent(signal_id=sig.signal_id, event_timestamp=_AS_OF,
                                             event_type="triggered"))
    assert triggered.status is SignalStatus.TRIGGERED
    stopped = apply_event(sig, SignalEvent(signal_id=sig.signal_id, event_timestamp=_AS_OF,
                                           event_type="stop_hit"))
    assert stopped.status is SignalStatus.STOPPED


def test_position_sizing_basic() -> None:
    sig = _signal()
    result = suggest_size(sig, None, account_size_usd=50_000, risk_per_trade_pct=0.5)
    assert result.contracts >= 0
    assert result.dollar_risk == 250.0
