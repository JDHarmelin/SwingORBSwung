"""Execution-confirmation gate — decides *when* a candidate is worth acting on.

This is the seam where Hermes plugs in. SwingORSwung generates candidate setups
deterministically; a ConfirmationGate decides the **execution moment** (the only
time Telegram should fire). The default gate here is mechanical (price crossed
the trigger). A Hermes-backed gate can later implement the same ``assess``
method to supply AI judgment + a learned confidence.
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
    direction. Deterministic placeholder for the Hermes AI gate; keeps the
    execution-only alerting flow working before Hermes is wired in.
    """

    def __init__(self, market: MarketDataProvider) -> None:
        self._market = market

    async def assess(self, signal: Signal) -> ConfirmationDecision:
        quote = await self._market.get_latest_quote(signal.symbol)
        price = quote.close
        if signal.direction == Direction.LONG:
            crossed = price >= signal.trigger_price
        else:
            crossed = price <= signal.trigger_price
        if crossed:
            return ConfirmationDecision(True, signal.confidence, ["price_crossed_trigger"])
        return ConfirmationDecision(False, signal.confidence, ["awaiting_trigger"])
