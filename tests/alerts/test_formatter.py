"""Alert formatter and dedupe tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_engine.alerts.dedupe import AlertDeduper
from trading_engine.alerts.formatter import format_follow_up, format_signal
from trading_engine.core.types import (
    ContractSuggestion,
    Direction,
    SetupType,
    Signal,
    SignalEvent,
    SignalStatus,
    TargetPlan,
)


def _sample_signal() -> Signal:
    return Signal(
        signal_id="t-1",
        timestamp=datetime(2026, 5, 20, 12, 45, tzinfo=UTC),
        symbol="NVDA",
        setup_type=SetupType.B_BREAKOUT_RETEST,
        direction=Direction.LONG,
        trigger_price=132.40,
        stop_price=130.95,
        target_plan=TargetPlan(trim1_gain_pct=30, trim2_gain_pct=60, runner_trail="8EMA"),
        contract=ContractSuggestion(
            ticker="NVDA",
            direction="long_call",
            expiry=datetime(2026, 6, 19, tzinfo=UTC).date(),
            strike=135.0,
            delta=0.38,
            bid_ask_spread_pct=4.8,
            classification="standard_swing",
        ),
        rationale="SMH leading, retest holding",
        confidence=0.81,
        status=SignalStatus.PENDING,
        reason_codes=["rs_positive", "retest_hold"],
    )


def test_format_signal_snapshot() -> None:
    msg = format_signal(_sample_signal())
    assert "SETUP:" in msg
    assert "NVDA" in msg
    assert "CONFIDENCE: 81/100" in msg
    assert "132.40" in msg


def test_format_follow_up() -> None:
    ev = SignalEvent(
        signal_id="t-1",
        event_timestamp=datetime.now(tz=UTC),
        event_type="trim1",
        event_payload={"symbol": "NVDA"},
    )
    assert "TRIM 1" in format_follow_up(ev, symbol="NVDA")


def test_dedupe_window() -> None:
    times = [datetime(2026, 1, 1, 12, 0, tzinfo=UTC)]

    def clock() -> datetime:
        return times[-1]

    d = AlertDeduper(window=timedelta(minutes=30), _now=clock)
    assert d.should_send("sig:pending")
    assert not d.should_send("sig:pending")
    times.append(datetime(2026, 1, 1, 12, 31, tzinfo=UTC))
    assert d.should_send("sig:pending")
