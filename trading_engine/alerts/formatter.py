"""Pure Telegram message formatting — spec §9 and §10."""

from __future__ import annotations

from trading_engine.core.types import ContractSuggestion, Signal, SignalEvent, TargetPlan


def _contract_line(contract: ContractSuggestion | None) -> str:
    if contract is None:
        return "CONTRACT: (pending selection)"
    opt = "C" if "call" in contract.direction else "P"
    base = f"CONTRACT: {contract.expiry:%Y-%m-%d} {contract.strike:.0f}{opt}"
    if contract.delta is not None:
        return f"{base}, ~{contract.delta:.2f} delta"
    return base


def _targets_line(plan: TargetPlan) -> str:
    return (
        f"TARGETS: Trim 1 +{plan.trim1_gain_pct:.0f}%, "
        f"trim 2 +{plan.trim2_gain_pct:.0f}%, runner trail {plan.runner_trail}"
    )


def format_signal(signal: Signal) -> str:
    """Render primary alert per spec §9."""
    why = ", ".join(signal.reason_codes) if signal.reason_codes else signal.rationale
    bias = "Long" if signal.direction.value == "long" else "Short"
    conf = int(signal.confidence * 100)
    lines = [
        f"SETUP: {signal.setup_type.value.replace('_', ' ').title()}",
        f"TICKER: {signal.symbol}",
        f"BIAS: {bias}",
        f"WHY: {why}",
        f"ENTRY: Above {signal.trigger_price:.2f}"
        if signal.direction.value == "long"
        else f"ENTRY: Below {signal.trigger_price:.2f}",
        f"STOP: Below {signal.stop_price:.2f}"
        if signal.direction.value == "long"
        else f"STOP: Above {signal.stop_price:.2f}",
        _contract_line(signal.contract),
        _targets_line(signal.target_plan),
        f"CONFIDENCE: {conf}/100",
        f"TIMESTAMP: {signal.timestamp.isoformat()}",
    ]
    return "\n".join(lines)


_FOLLOW_UP_TEMPLATES = {
    "triggered": "ENTRY TRIGGERED: {symbol} at {price}",
    "stop_hit": "STOP HIT: {symbol}",
    "trim1": "TRIM 1: {symbol} — target gain reached",
    "be_moved": "STOP MOVED TO BREAKEVEN: {symbol}",
    "runner_exit": "RUNNER EXIT: {symbol}",
    "expiry_risk": "EXPIRY RISK: {symbol} — review position",
    "roll": "ROLL CANDIDATE: {symbol}",
}


def format_follow_up(event: SignalEvent, symbol: str = "") -> str:
    """Render follow-up alert per spec §10."""
    sym = symbol or event.event_payload.get("symbol", "")
    template = _FOLLOW_UP_TEMPLATES.get(event.event_type, f"EVENT: {event.event_type}")
    price = event.event_payload.get("price", "")
    return template.format(symbol=sym, price=price)
