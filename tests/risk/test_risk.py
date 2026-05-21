"""Risk engine tests."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_engine.core.types import Direction, SetupType, Signal, SignalStatus, TargetPlan
from trading_engine.risk.contract_selector import select_contract
from trading_engine.risk.risk_class import classify_risk
from trading_engine.risk.trade_management import evaluate_management
from trading_engine.testing.synthetic import sample_option_chain


def _signal() -> Signal:
    return Signal(
        signal_id="r-1",
        timestamp=datetime.now(tz=UTC),
        symbol="UPTRD",
        setup_type=SetupType.A_BREAKOUT_CONTINUATION,
        direction=Direction.LONG,
        trigger_price=125.0,
        stop_price=120.0,
        target_plan=TargetPlan(),
        rationale="test",
        confidence=0.8,
        status=SignalStatus.PENDING,
    )


def test_rejects_illiquid_contract() -> None:
    chain = sample_option_chain("UPTRD")
    bad = [c for c in chain.contracts if c.open_interest < 100][0]
    assert bad.spread_pct is None or bad.spread_pct > 8


def test_selects_standard_delta() -> None:
    chain = sample_option_chain("UPTRD")
    sug = select_contract(_signal(), chain)
    assert sug is not None
    assert sug.delta is not None
    assert 0.30 <= abs(sug.delta) <= 0.45


def test_trim_event() -> None:
    sig = _signal()
    sig.status = SignalStatus.TRIGGERED
    ev = evaluate_management(sig, option_gain_pct=35.0)
    assert ev is not None
    assert ev.event_type == "trim1"


def test_risk_class_a_plus() -> None:
    sig = _signal()
    sig.confidence = 0.9
    sig.reason_codes = ["a", "b", "c", "d"]
    assert classify_risk(sig).value == "a_plus"
