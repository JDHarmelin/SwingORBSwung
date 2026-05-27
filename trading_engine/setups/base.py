"""Setup detection scaffolding (spec §6).

A ``SetupContext`` carries everything a detector needs for one symbol; each
detector is a small class exposing ``setup_type``, ``explanation``, and
``detect(ctx) -> list[Signal]``. Detectors are pure given the context, so a
signal is fully replayable from stored candles + context (non-negotiable rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from trading_engine.core.types import (
    Direction,
    MarketRegime,
    OHLCVSeries,
    RiskClass,
    SetupType,
    Signal,
    SignalStatus,
    SymbolScore,
    TargetPlan,
)


@dataclass(frozen=True)
class SetupContext:
    """Inputs for detecting setups on one symbol at one point in time."""

    symbol: str
    as_of: datetime
    daily: OHLCVSeries
    regime: MarketRegime
    intraday: OHLCVSeries | None = None
    symbol_score: SymbolScore | None = None
    sector_composite: float = 0.0
    is_index: bool = False
    target_plan: TargetPlan = field(default_factory=TargetPlan)


def make_signal_id(
    symbol: str, setup: SetupType, direction: Direction, as_of: datetime, trigger: float
) -> str:
    """Deterministic id keyed on the candidate's identity for the trading day.

    Format: ``symbol:setup:direction:YYYYMMDD``. Re-scans through the same
    session upsert the existing PENDING row instead of accumulating duplicates;
    the trigger isn't included so a tiny price refit doesn't multiply rows.
    """
    _ = trigger  # kept in signature for callers that still pass it
    return f"{symbol.upper()}:{setup.value}:{direction.value}:{as_of:%Y%m%d}"


def base_confidence(ctx: SetupContext, setup_quality: float) -> float:
    """Blend the symbol's composite conviction with a per-setup quality term.

    Both inputs are in roughly [0, 1] after normalisation; result clipped to
    [0, 1]. ``setup_quality`` lets a detector express how textbook the trigger
    looks independent of the ranking score.
    """
    composite = abs(ctx.symbol_score.composite_score) if ctx.symbol_score else 0.3
    conviction = min(1.0, 0.5 + composite)  # 0.5..1.0
    quality = max(0.0, min(1.0, setup_quality))
    return round(max(0.0, min(1.0, 0.6 * conviction + 0.4 * quality)), 4)


def _max_loss_dollars_for(risk_class: RiskClass) -> float:
    """Look up the dollar risk cap for ``risk_class``.

    Prefers values from loaded settings YAML when available, falls back to
    ``DEFAULT_MAX_LOSS_DOLLARS``. Wrapped in a try/except so setup builders
    never fail just because config isn't loadable in the current process.
    """
    from trading_engine.core.config import DEFAULT_MAX_LOSS_DOLLARS

    key = risk_class.value
    try:
        from trading_engine.core.config import load_settings

        cfg = load_settings()
        caps = getattr(cfg.risk, "max_loss_dollars", {}) or {}
        if key in caps:
            return float(caps[key])
    except Exception:
        pass
    return float(DEFAULT_MAX_LOSS_DOLLARS.get(key, DEFAULT_MAX_LOSS_DOLLARS["standard"]))


def compute_risk_profile(
    *, trigger_price: float, stop_price: float, risk_class: RiskClass
) -> dict[str, float | str]:
    """Build the numeric risk profile dict attached to every Signal.

    Position sizing should consume this rather than the string ``risk_class``
    tag — stop distance varies by orders of magnitude across setups.
    """
    stop_distance = abs(float(trigger_price) - float(stop_price))
    entry = float(trigger_price) if trigger_price != 0 else 0.0
    stop_distance_pct = (stop_distance / entry) if entry else 0.0
    max_loss = _max_loss_dollars_for(risk_class)
    shares = int(max_loss // stop_distance) if stop_distance > 0 else 0
    return {
        "stop_distance": round(stop_distance, 6),
        "stop_distance_pct": round(stop_distance_pct, 6),
        "risk_per_share": round(stop_distance, 6),
        "max_loss_dollars": round(max_loss, 2),
        "shares_at_max_loss": float(shares),
        "setup_class": risk_class.value,
    }


def build_signal(
    ctx: SetupContext,
    *,
    setup: SetupType,
    direction: Direction,
    trigger_price: float,
    stop_price: float,
    rationale: str,
    setup_quality: float,
    reason_codes: list[str],
    risk_class: RiskClass = RiskClass.STANDARD,
    confidence_components: dict[str, float] | None = None,
) -> Signal:
    confidence = base_confidence(ctx, setup_quality)
    composite = abs(ctx.symbol_score.composite_score) if ctx.symbol_score else 0.3
    conviction = min(1.0, 0.5 + composite)
    quality = max(0.0, min(1.0, setup_quality))
    # Always expose the two ingredients of base_confidence so calibration has a
    # consistent floor across setups. Setup-specific factors layer on top.
    components: dict[str, float] = {
        "conviction": round(0.6 * conviction, 4),
        "setup_quality": round(0.4 * quality, 4),
    }
    if confidence_components:
        for k, v in confidence_components.items():
            components[k] = round(float(v), 4)
    risk_profile = compute_risk_profile(
        trigger_price=round(trigger_price, 4),
        stop_price=round(stop_price, 4),
        risk_class=risk_class,
    )
    return Signal(
        signal_id=make_signal_id(ctx.symbol, setup, direction, ctx.as_of, trigger_price),
        timestamp=ctx.as_of,
        symbol=ctx.symbol,
        setup_type=setup,
        direction=direction,
        trigger_price=round(trigger_price, 4),
        stop_price=round(stop_price, 4),
        target_plan=ctx.target_plan,
        contract=None,  # filled by the contract selector downstream
        rationale=rationale,
        confidence=confidence,
        status=SignalStatus.PENDING,
        risk_class=risk_class,
        reason_codes=reason_codes,
        confidence_components=components,
        risk_profile=risk_profile,
    )


@runtime_checkable
class SetupDetector(Protocol):
    setup_type: SetupType
    explanation: str

    def detect(self, ctx: SetupContext) -> list[Signal]: ...


__all__ = [
    "SetupContext",
    "SetupDetector",
    "base_confidence",
    "build_signal",
    "compute_risk_profile",
    "make_signal_id",
]
