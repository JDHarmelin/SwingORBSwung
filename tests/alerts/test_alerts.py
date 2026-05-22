"""Alert formatter + in-memory sink dedupe behaviour."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from trading_engine.alerts.formatter import (
    dedupe_key,
    event_dedupe_key,
    format_event,
    format_signal,
)
from trading_engine.alerts.sinks import InMemoryAlertSink
from trading_engine.core.types import (
    ContractSuggestion,
    Direction,
    RiskClass,
    SetupType,
    Signal,
    SignalEvent,
    TargetPlan,
)

_AS_OF = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)


def _signal(*, with_contract: bool = True) -> Signal:
    contract = (
        ContractSuggestion(
            ticker="O:UPTRD260619C00130000",
            direction="long_call",
            expiry=date(2026, 6, 19),
            strike=130.0,
            delta=0.38,
            bid_ask_spread_pct=2.5,
            classification="standard_swing",
            open_interest=2500,
            volume=400,
        )
        if with_contract
        else None
    )
    return Signal(
        signal_id="uptrd-A-abc123",
        timestamp=_AS_OF,
        symbol="UPTRD",
        setup_type=SetupType.A_BREAKOUT_CONTINUATION,
        direction=Direction.LONG,
        trigger_price=125.40,
        stop_price=122.95,
        target_plan=TargetPlan(),
        contract=contract,
        rationale="breakout on volume",
        confidence=0.81,
        risk_class=RiskClass.A_PLUS,
        reason_codes=["Breakout > swing high", "RS+ vs SPY 20d"],
    )


def test_format_signal_contains_required_fields() -> None:
    msg = format_signal(_signal())
    for needle in (
        "SETUP: Breakout Continuation",
        "TICKER: UPTRD",
        "BIAS: Long",
        "ENTRY: Above 125.40",
        "STOP: Below 122.95",
        "CONTRACT: 2026-06-19 130C",
        "CONFIDENCE: 81/100",
    ):
        assert needle in msg, f"missing: {needle}\n---\n{msg}"


def test_format_signal_handles_missing_contract() -> None:
    msg = format_signal(_signal(with_contract=False))
    assert "Awaiting chain" in msg


def test_format_event() -> None:
    sig = _signal()
    event = SignalEvent(
        signal_id=sig.signal_id,
        event_timestamp=_AS_OF,
        event_type="trim1",
        event_payload={"gain_pct": 35.0},
    )
    msg = format_event(event, sig)
    assert "[TRIM 1] UPTRD" in msg
    assert "gain_pct=35.0" in msg


@pytest.mark.asyncio
async def test_in_memory_sink_dedupes() -> None:
    sink = InMemoryAlertSink()
    sig = _signal()
    msg = format_signal(sig)
    await sink.send(msg, dedupe_key=dedupe_key(sig))
    await sink.send(msg, dedupe_key=dedupe_key(sig))  # same key — drop
    assert len(sink.messages) == 1


@pytest.mark.asyncio
async def test_in_memory_sink_distinct_event_keys() -> None:
    sink = InMemoryAlertSink()
    sig = _signal()
    e1 = SignalEvent(signal_id=sig.signal_id, event_timestamp=_AS_OF, event_type="trim1")
    e2 = SignalEvent(signal_id=sig.signal_id, event_timestamp=_AS_OF, event_type="be_moved")
    await sink.send(format_event(e1, sig), dedupe_key=event_dedupe_key(e1))
    await sink.send(format_event(e2, sig), dedupe_key=event_dedupe_key(e2))
    assert len(sink.messages) == 2
