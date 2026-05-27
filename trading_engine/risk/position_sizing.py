"""Position sizing helpers.

Alert-only engine — there is no broker integration. These helpers produce a
suggested contract count given a per-trade risk budget so the alert can carry
"suggested ~N contracts" hints.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_engine.core.types import ContractSuggestion, Signal


@dataclass(frozen=True)
class SizingResult:
    contracts: int
    dollar_risk: float
    notes: list[str]


def suggest_size(
    signal: Signal,
    contract: ContractSuggestion | None,
    *,
    account_size_usd: float,
    risk_per_trade_pct: float = 0.5,
    contract_price_estimate: float | None = None,
) -> SizingResult:
    """Suggest a contract count from account size × per-trade risk budget.

    The premium estimate defaults to the distance between trigger and stop as
    a rough proxy when the caller hasn't priced the option.
    """
    notes: list[str] = []
    # Prefer the per-setup numeric risk profile when present — stop distance
    # varies by orders of magnitude across setups so a $-cap per setup-class
    # is more honest than a flat % of account.
    profile = getattr(signal, "risk_profile", None) or {}
    profile_budget = profile.get("max_loss_dollars") if isinstance(profile, dict) else None
    if profile_budget is not None:
        budget = max(0.0, float(profile_budget))
        notes.append(
            f"risk_profile: ${budget:.0f} cap, "
            f"stop_dist={float(profile.get('stop_distance', 0.0)):.2f} "
            f"({profile.get('setup_class', '?')})"
        )
    else:
        budget = max(0.0, account_size_usd * risk_per_trade_pct / 100.0)
    direction = signal.direction
    if contract is None:
        notes.append("no contract — sizing is indicative only")
    per_contract_premium = (
        contract_price_estimate
        if contract_price_estimate is not None
        else max(0.05, abs(signal.trigger_price - signal.stop_price))
    )
    cost_per_contract = per_contract_premium * 100.0  # equity options multiplier
    if cost_per_contract <= 0:
        return SizingResult(contracts=0, dollar_risk=0.0, notes=["non-positive premium"])
    count = int(budget // cost_per_contract)
    if count == 0 and budget > 0:
        notes.append("budget below 1 contract — consider smaller-delta")
    notes.append(
        f"{direction.value}: budget ${budget:.0f}, ~${cost_per_contract:.0f}/contract"
    )
    return SizingResult(contracts=count, dollar_risk=budget, notes=notes)


__all__ = ["SizingResult", "suggest_size"]
