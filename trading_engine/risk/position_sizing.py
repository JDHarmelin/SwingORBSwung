"""Suggested position sizing — research only."""

from __future__ import annotations

from dataclasses import dataclass

from trading_engine.core.types import Signal


@dataclass(frozen=True)
class SizeSuggestion:
    suggested_risk_pct: float
    max_contracts: int
    notes: str


def suggest_size(
    signal: Signal,
    *,
    account_risk_pct: float = 1.0,
    account_value: float = 100_000.0,
) -> SizeSuggestion:
    stop_dist = abs(signal.trigger_price - signal.stop_price) / signal.trigger_price
    if stop_dist <= 0:
        stop_dist = 0.02
    risk_dollars = account_value * (account_risk_pct / 100.0)
    per_share_risk = signal.trigger_price * stop_dist
    contracts = max(1, int(risk_dollars / (per_share_risk * 100)))
    return SizeSuggestion(
        suggested_risk_pct=account_risk_pct,
        max_contracts=contracts,
        notes="Suggestion only — not a trade instruction.",
    )
