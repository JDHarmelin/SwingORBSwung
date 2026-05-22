"""Setup detection scaffolding (spec §6).

A ``SetupContext`` carries everything a detector needs for one symbol; each
detector is a small class exposing ``setup_type``, ``explanation``, and
``detect(ctx) -> list[Signal]``. Detectors are pure given the context, so a
signal is fully replayable from stored candles + context (non-negotiable rule).
"""

from __future__ import annotations

import hashlib
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


def make_signal_id(symbol: str, setup: SetupType, as_of: datetime, trigger: float) -> str:
    """Deterministic id from the signal's identity → stable dedupe + replay."""
    raw = f"{symbol}|{setup.value}|{as_of.isoformat()}|{round(trigger, 4)}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]  # noqa: S324 (non-crypto id)
    return f"{symbol.lower()}-{setup.value}-{digest}"


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
) -> Signal:
    return Signal(
        signal_id=make_signal_id(ctx.symbol, setup, ctx.as_of, trigger_price),
        timestamp=ctx.as_of,
        symbol=ctx.symbol,
        setup_type=setup,
        direction=direction,
        trigger_price=round(trigger_price, 4),
        stop_price=round(stop_price, 4),
        target_plan=ctx.target_plan,
        contract=None,  # filled by the contract selector downstream
        rationale=rationale,
        confidence=base_confidence(ctx, setup_quality),
        status=SignalStatus.PENDING,
        risk_class=risk_class,
        reason_codes=reason_codes,
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
    "make_signal_id",
]
