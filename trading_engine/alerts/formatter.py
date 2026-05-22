"""Pure Telegram message formatting — blunt, digestible alerts (spec §9, §10)."""

from __future__ import annotations

from trading_engine.core.types import ContractSuggestion, Signal, SignalEvent, TargetPlan

# Headline badge by risk class — sets expectations before any numbers.
_RISK_BADGE = {
    "a_plus": "🟢 A+ SETUP",
    "standard": "🟢 SETUP",
    "lotto": "🎲 LOTTO — high risk, size small",
    "hedge": "🛡️ HEDGE",
}


def _contract_line(contract: ContractSuggestion | None) -> str:
    if contract is None:
        return "🎟️ CONTRACT: (pending selection)"
    opt = "C" if "call" in contract.direction else "P"
    base = f"🎟️ CONTRACT: {contract.expiry:%b %d} {contract.strike:.0f}{opt}"
    if contract.delta is not None:
        return f"{base} (~{contract.delta:.2f} delta)"
    return base


def _targets_line(plan: TargetPlan) -> str:
    return (
        f"🎯 MANAGE: trim +{plan.trim1_gain_pct:.0f}%, "
        f"+{plan.trim2_gain_pct:.0f}%, trail the rest on {plan.runner_trail}"
    )


def format_signal(signal: Signal) -> str:
    """Render the primary alert: one glance tells you the call and the condition."""
    is_long = signal.direction.value == "long"
    bias = "LONG" if is_long else "SHORT"
    conf = int(signal.confidence * 100)
    badge = _RISK_BADGE.get(signal.risk_class.value, "🟢 SETUP")
    setup = signal.setup_type.value.replace("_", " ").title()
    why = ", ".join(signal.reason_codes) if signal.reason_codes else signal.rationale

    break_word = "ABOVE" if is_long else "BELOW"
    stop_word = "below" if is_long else "above"
    entry = signal.trigger_price
    stop = signal.stop_price
    stop_pct = abs(entry - stop) / entry * 100 if entry else 0.0

    lines = [
        f"{badge} — {bias} {signal.symbol}",
        f"{setup} · CONFIDENCE: {conf}/100",
        "",
        f"👉 DO THIS: enter ONLY IF {signal.symbol} breaks {break_word} {entry:.2f}.",
        "   No break = no trade. Already well past it = you're late, skip it.",
        f"🛑 STOP if it goes {stop_word} {stop:.2f}  ({stop_pct:.1f}% from entry)",
        _targets_line(signal.target_plan),
        _contract_line(signal.contract),
        "",
        f"📋 WHY: {why}",
        "ℹ️ A conditional trigger, not a buy-now order — the engine flags setups that "
        "match your rules; it can't predict the outcome. You make the call.",
    ]
    return "\n".join(lines)


_FOLLOW_UP_TEMPLATES = {
    "triggered": "✅ ENTERED: {symbol} crossed {price} — the setup is now live.",
    "stop_hit": "🛑 STOPPED OUT: {symbol} — thesis broke, you're out.",
    "trim1": "🎯 TRIM 1: {symbol} hit the first target — take partial profit.",
    "be_moved": "🔒 STOP → BREAKEVEN: {symbol} — risk is now free.",
    "runner_exit": "🏁 RUNNER OUT: {symbol} — trail hit, close the remainder.",
    "expiry_risk": "⏳ EXPIRY RISK: {symbol} — roll or close before theta bites.",
    "roll": "🔄 ROLL: {symbol} — consider rolling to a later expiry.",
}


def format_follow_up(event: SignalEvent, symbol: str = "") -> str:
    """Render a follow-up alert per spec §10."""
    sym = symbol or event.event_payload.get("symbol", "")
    template = _FOLLOW_UP_TEMPLATES.get(event.event_type, f"EVENT: {event.event_type}")
    price = event.event_payload.get("price", "")
    return template.format(symbol=sym, price=price)
