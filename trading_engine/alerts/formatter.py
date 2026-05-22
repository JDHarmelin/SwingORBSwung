"""Render a ``Signal`` into the Telegram message format from spec §9."""

from __future__ import annotations

from trading_engine.core.types import (
    ContractSuggestion,
    Direction,
    Signal,
    SignalEvent,
    TargetPlan,
)

_SETUP_LABELS: dict[str, str] = {
    "A_breakout_continuation": "Breakout Continuation",
    "B_breakout_retest": "Breakout Retest",
    "C_ema_continuation": "8 EMA Continuation",
    "D_compression_break": "Compression / Wedge / Flag Break",
    "E_relative_weakness": "Relative Weakness Breakdown",
    "F_index_tactical": "Index Tactical (Day)",
}


def _bias(direction: Direction) -> str:
    return "Long" if direction is Direction.LONG else "Short"


def _entry_clause(signal: Signal) -> str:
    side = "Above" if signal.direction is Direction.LONG else "Below"
    return f"{side} {signal.trigger_price:.2f}"


def _stop_clause(signal: Signal) -> str:
    side = "Below" if signal.direction is Direction.LONG else "Above"
    return f"{side} {signal.stop_price:.2f}"


def _contract_line(c: ContractSuggestion | None) -> str:
    if c is None:
        return "Awaiting chain — no liquid contract found"
    side = "C" if c.direction == "long_call" else "P"
    delta = f", ~{c.delta:+.2f} delta" if c.delta is not None else ""
    return f"{c.expiry:%Y-%m-%d} {c.strike:g}{side}{delta} ({c.classification})"


def _targets_line(plan: TargetPlan) -> str:
    parts = [
        f"Trim 1 +{plan.trim1_gain_pct:.0f}%",
        f"Trim 2 +{plan.trim2_gain_pct:.0f}%",
        f"runner trail {plan.runner_trail}",
    ]
    if plan.move_stop_to_be_after_trim1:
        parts.append("stop→BE after T1")
    return ", ".join(parts)


def format_signal(signal: Signal) -> str:
    """Render the trigger alert (spec §9 format)."""
    setup = _SETUP_LABELS.get(signal.setup_type.value, signal.setup_type.value)
    why = "; ".join(signal.reason_codes) or signal.rationale
    return "\n".join(
        [
            f"SETUP: {setup}",
            f"TICKER: {signal.symbol}",
            f"BIAS: {_bias(signal.direction)}",
            f"WHY: {why}",
            f"ENTRY: {_entry_clause(signal)}",
            f"STOP: {_stop_clause(signal)}",
            f"CONTRACT: {_contract_line(signal.contract)}",
            f"TARGETS: {_targets_line(signal.target_plan)}",
            f"CONFIDENCE: {int(round(signal.confidence * 100))}/100",
            f"RISK: {signal.risk_class.value}",
            f"TS: {signal.timestamp.isoformat()}",
        ]
    )


def format_event(event: SignalEvent, signal: Signal) -> str:
    """Render a management follow-up alert (spec §10)."""
    label = {
        "triggered": "TRIGGERED",
        "stop_hit": "STOPPED",
        "trim1": "TRIM 1",
        "trim2": "TRIM 2",
        "be_moved": "STOP → BREAKEVEN",
        "runner_exit": "RUNNER EXIT",
        "expiry_risk": "EXPIRY RISK",
        "roll": "ROLL CANDIDATE",
    }.get(event.event_type, event.event_type.upper())
    payload_bits = ", ".join(f"{k}={v}" for k, v in event.event_payload.items())
    payload = f" ({payload_bits})" if payload_bits else ""
    return f"[{label}] {signal.symbol} {signal.setup_type.value}{payload}"


def dedupe_key(signal: Signal) -> str:
    """Stable idempotency key for trigger alerts (matches signal_id)."""
    return f"signal:{signal.signal_id}"


def event_dedupe_key(event: SignalEvent) -> str:
    return f"event:{event.signal_id}:{event.event_type}"


__all__ = ["dedupe_key", "event_dedupe_key", "format_event", "format_signal"]
