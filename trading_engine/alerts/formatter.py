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


_CONTRACT_REASON_PREFIX = "contract_unavailable:"


def _contract_line(
    c: ContractSuggestion | None, reason_codes: list[str] | None = None
) -> str:
    if c is None:
        # Surface the diagnostic stashed by signal_service (if any) so
        # operators can tell entitlement gaps from liquidity-filter rejection.
        detail = ""
        for code in reason_codes or []:
            if code.startswith(_CONTRACT_REASON_PREFIX):
                detail = f" — {code[len(_CONTRACT_REASON_PREFIX):].strip()}"
                break
        return f"Awaiting chain — no liquid contract found{detail}"
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


def _risk_profile_line(signal: Signal) -> str | None:
    """Render the numeric per-setup risk profile, or None if absent."""
    profile = getattr(signal, "risk_profile", None)
    if not profile:
        return None
    try:
        stop_dist = float(profile.get("stop_distance", 0.0))
        cap = float(profile.get("max_loss_dollars", 0.0))
        shares = int(float(profile.get("shares_at_max_loss", 0)))
        cls = profile.get("setup_class", signal.risk_class.value)
    except (TypeError, ValueError):
        return None
    return (
        f"RISK PROFILE: stop_dist={stop_dist:.2f} "
        f"(${cap:.0f} cap -> {shares} sh, class={cls})"
    )


def _setup_label(signal: Signal) -> str:
    return _SETUP_LABELS.get(signal.setup_type.value, signal.setup_type.value)


def format_signal(signal: Signal, companions: list[Signal] | None = None) -> str:
    """Render the trigger alert (spec §9 format).

    If ``companions`` are supplied, append an ``ALSO:`` line listing other
    setups that fired on the same (ticker, bias, bar). The primary signal is
    used for the SETUP/CONFIDENCE/entry/stop fields.
    """
    setup = _setup_label(signal)
    why = "; ".join(signal.reason_codes) or signal.rationale
    lines = [
        f"SETUP: {setup}",
        f"TICKER: {signal.symbol}",
        f"BIAS: {_bias(signal.direction)}",
        f"WHY: {why}",
        f"ENTRY: {_entry_clause(signal)}",
        f"STOP: {_stop_clause(signal)}",
        f"CONTRACT: {_contract_line(signal.contract, signal.reason_codes)}",
        f"TARGETS: {_targets_line(signal.target_plan)}",
        f"CONFIDENCE: {int(round(signal.confidence * 100))}/100",
        f"RISK: {signal.risk_class.value}",
        f"TS: {signal.timestamp.isoformat()}",
    ]
    rp_line = _risk_profile_line(signal)
    if rp_line is not None:
        lines.insert(-1, rp_line)
    if companions:
        also = ", ".join(
            f"{_setup_label(c)} ({int(round(c.confidence * 100))})" for c in companions
        )
        lines.append(f"ALSO: {also}")
    return "\n".join(lines)


def coalesce_signals(signals: list[Signal]) -> list[tuple[Signal, list[Signal]]]:
    """Group signals by (symbol, direction, timestamp) and pick a primary.

    Within each group the highest-confidence signal becomes the primary; the
    rest are returned as companions (sorted by confidence desc). Groups with a
    single signal yield an empty companion list. Group order follows the first
    appearance of each key in ``signals`` so output is stable.
    """
    groups: dict[tuple[str, str, str], list[Signal]] = {}
    order: list[tuple[str, str, str]] = []
    for sig in signals:
        key = (sig.symbol, sig.direction.value, sig.timestamp.isoformat())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(sig)
    out: list[tuple[Signal, list[Signal]]] = []
    for key in order:
        members = sorted(groups[key], key=lambda s: s.confidence, reverse=True)
        out.append((members[0], members[1:]))
    return out


def coalesced_dedupe_key(primary: Signal, companions: list[Signal]) -> str:
    """Dedupe key for a coalesced alert — stable across reruns of the same bar."""
    if not companions:
        return dedupe_key(primary)
    ids = sorted([primary.signal_id, *(c.signal_id for c in companions)])
    return "signals:" + "|".join(ids)


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


__all__ = [
    "coalesce_signals",
    "coalesced_dedupe_key",
    "dedupe_key",
    "event_dedupe_key",
    "format_event",
    "format_signal",
]
