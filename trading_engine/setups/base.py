"""Setup detector base types."""

from __future__ import annotations

import uuid
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
    return Signal(
        signal_id=str(uuid.uuid4()),
        timestamp=datetime.now(tz=UTC),
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
