"""Trade management + signal lifecycle (spec §8, §10).

Builds the ``TargetPlan`` from config and classifies a signal's ``RiskClass``;
emits follow-up ``SignalEvent`` records as the option's gain crosses the
trim/breakeven/runner thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from trading_engine.core.config import RiskConfig
from trading_engine.core.types import (
    RiskClass,
    Signal,
    SignalEvent,
    SignalStatus,
    TargetPlan,
)


def build_target_plan(cfg: RiskConfig, notes: list[str] | None = None) -> TargetPlan:
    return TargetPlan(
        trim1_gain_pct=cfg.trim1_gain_pct,
        trim2_gain_pct=cfg.trim2_gain_pct,
        move_stop_to_be_after_trim1=cfg.move_stop_to_be_after_trim1,
        runner_trail=cfg.runner_trail,
        forced_exit_before_event=cfg.forced_exit_before_event,
        notes=notes or [],
    )


def classify_risk(
    confidence: float, *, day_trade: bool = False, hedge: bool = False
) -> RiskClass:
    """Map confidence + flags to a risk class (spec §8)."""
    if hedge:
        return RiskClass.HEDGE
    if day_trade and confidence < 0.55:
        return RiskClass.LOTTO
    if confidence >= 0.8:
        return RiskClass.A_PLUS
    if confidence < 0.45:
        return RiskClass.LOTTO
    return RiskClass.STANDARD


@dataclass(frozen=True)
class ManagementUpdate:
    """A tick of P&L on the option side; the engine decides what events fire."""

    signal: Signal
    timestamp: datetime
    option_entry_price: float
    option_current_price: float
    stop_hit: bool = False

    @property
    def gain_pct(self) -> float:
        if self.option_entry_price <= 0:
            return 0.0
        return (self.option_current_price / self.option_entry_price - 1.0) * 100.0


def follow_up_events(
    update: ManagementUpdate,
    already_emitted: set[str],
    *,
    plan: TargetPlan | None = None,
) -> list[SignalEvent]:
    """Produce the next batch of management events not yet emitted (spec §10).

    ``already_emitted`` is the set of event_types previously persisted for the
    signal so duplicate trim/be alerts don't fire.
    """
    plan = plan or update.signal.target_plan
    events: list[SignalEvent] = []

    def _emit(event_type: str, payload: dict[str, Any] | None = None) -> None:
        if event_type in already_emitted:
            return
        events.append(
            SignalEvent(
                signal_id=update.signal.signal_id,
                event_timestamp=update.timestamp,
                event_type=event_type,
                event_payload=payload or {},
            )
        )

    if update.stop_hit:
        _emit("stop_hit", {"price": update.option_current_price})
        return events

    gain = update.gain_pct
    if gain >= plan.trim1_gain_pct:
        _emit("trim1", {"gain_pct": round(gain, 2)})
        if plan.move_stop_to_be_after_trim1 and "trim1" in {e.event_type for e in events} | already_emitted:
            _emit("be_moved", {"to": update.option_entry_price})
    if gain >= plan.trim2_gain_pct:
        _emit("trim2", {"gain_pct": round(gain, 2)})
    return events


def apply_event(signal: Signal, event: SignalEvent) -> Signal:
    """Return a copy of ``signal`` with status advanced by ``event``."""
    next_status = signal.status
    if event.event_type == "triggered":
        next_status = SignalStatus.TRIGGERED
    elif event.event_type == "stop_hit":
        next_status = SignalStatus.STOPPED
    elif event.event_type in {"trim1", "trim2"}:
        next_status = SignalStatus.TRIMMED
    elif event.event_type == "runner_exit":
        next_status = SignalStatus.CLOSED
    elif event.event_type == "expiry_risk":
        next_status = SignalStatus.EXPIRED_RISK
    return signal.model_copy(update={"status": next_status})


__all__ = [
    "ManagementUpdate",
    "apply_event",
    "build_target_plan",
    "classify_risk",
    "follow_up_events",
]
