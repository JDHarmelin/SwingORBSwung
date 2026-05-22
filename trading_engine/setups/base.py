"""Setup detector base types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from trading_engine.core.types import (
    Direction,
    MarketRegime,
    OHLCVSeries,
    OptionChain,
    RegimeType,
    SetupType,
    Signal,
    SymbolScore,
    TargetPlan,
)


@dataclass
class SetupContext:
    symbol: str
    candles: dict[str, OHLCVSeries]  # keyed by timeframe value
    regime: MarketRegime
    symbol_score: SymbolScore
    sector_score: float = 0.5
    option_chain: OptionChain | None = None


class Setup(Protocol):
    setup_type: SetupType
    explanation: str

    def detect(self, context: SetupContext) -> list[Signal]: ...


def _candidate_id(symbol: str, setup_type: SetupType, direction: Direction, ts: datetime) -> str:
    """Deterministic candidate id: one candidate per symbol+setup+direction+UTC day.

    Re-scanning the same setup on the same day yields the same id, so
    ``save_signal`` upserts in place instead of piling up duplicate PENDING rows
    (the candidate-backlog bug). A new trading day produces a fresh id.
    """
    day = ts.astimezone(UTC).strftime("%Y%m%d")
    return f"{symbol}:{setup_type.value}:{direction.value}:{day}"


def _new_signal(
    context: SetupContext,
    setup_type: SetupType,
    direction: Direction,
    trigger: float,
    stop: float,
    rationale: str,
    reason_codes: list[str],
    confidence: float,
) -> Signal:
    now = datetime.now(tz=UTC)
    return Signal(
        signal_id=_candidate_id(context.symbol, setup_type, direction, now),
        timestamp=now,
        symbol=context.symbol,
        setup_type=setup_type,
        direction=direction,
        trigger_price=trigger,
        stop_price=stop,
        target_plan=TargetPlan(),
        rationale=rationale,
        confidence=confidence,
        reason_codes=reason_codes,
    )


def regime_allows_long(regime: MarketRegime) -> bool:
    return regime.regime in (RegimeType.LONG_BIAS, RegimeType.MIXED)


def regime_allows_short(regime: MarketRegime) -> bool:
    return regime.regime in (RegimeType.SHORT_BIAS, RegimeType.MIXED)
