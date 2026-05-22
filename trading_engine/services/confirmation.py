"""Execution-confirmation gate — decides *when* a candidate is worth acting on.

The signal pipeline generates candidate setups deterministically. A
``ConfirmationGate`` decides the **execution moment** (the only time Telegram
should fire). The default gate here is mechanical (price crossed the trigger);
a Hermes-backed gate can plug into the same protocol later to supply learned
judgment + confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from trading_engine.core.interfaces import MarketDataProvider
from trading_engine.core.types import Direction, Signal


@dataclass(frozen=True)
class ConfirmationDecision:
    """Result of assessing whether a candidate should fire as an execution alert."""

    confirmed: bool
    confidence: float
    reason_codes: list[str] = field(default_factory=list)


@runtime_checkable
class ConfirmationGate(Protocol):
    """Decides whether a candidate signal has reached its execution moment."""

    async def assess(self, signal: Signal) -> ConfirmationDecision: ...


class PriceCrossConfirmationGate:
    """Confirm when the latest price has crossed the trigger in the signal's
    direction.

    Mechanical default — keeps execution-only alerting working before a
    smarter gate (e.g. AI-judged setup quality) is wired in.
    """

    def __init__(self, market: MarketDataProvider) -> None:
        self._market = market

    async def assess(self, signal: Signal) -> ConfirmationDecision:
        quote = await self._market.get_latest_quote(signal.symbol)
        price = quote.close
        crossed = (
            price >= signal.trigger_price
            if signal.direction is Direction.LONG
            else price <= signal.trigger_price
        )
        if crossed:
            return ConfirmationDecision(
                confirmed=True,
                confidence=signal.confidence,
                reason_codes=[f"price_crossed_trigger@{price:.2f}"],
            )
        return ConfirmationDecision(
            confirmed=False,
            confidence=signal.confidence,
            reason_codes=[f"awaiting_trigger@{price:.2f}"],
        )


class AlwaysOnGate:
    """Test gate: confirms everything. Useful for E2E tests of the alert path."""

    async def assess(self, signal: Signal) -> ConfirmationDecision:
        return ConfirmationDecision(True, signal.confidence, ["always_on"])


__all__ = [
    "AlwaysOnGate",
    "ConfirmationDecision",
    "ConfirmationGate",
    "PriceCrossConfirmationGate",
]
