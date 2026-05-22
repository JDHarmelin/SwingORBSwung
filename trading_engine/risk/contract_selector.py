"""Contract selection engine (spec §7).

Pick the option contract that best matches the alert's direction, DTE band,
delta target, and liquidity floor. Rejects illiquid contracts outright per
the non-negotiable design rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from trading_engine.core.config import ContractConfig, LiquidityConfig
from trading_engine.core.types import (
    ContractSuggestion,
    Direction,
    OptionChain,
    OptionContract,
    OptionType,
    RiskClass,
)

# Classifier output is one of these strings — matches the spec's JSON example.
ContractClassification = Literal["standard_swing", "day", "lotto", "hedge"]


@dataclass(frozen=True)
class ContractRejection:
    contract: OptionContract
    reasons: list[str]


def _spread_pct(c: OptionContract) -> float | None:
    sp = c.spread_pct
    return sp


def _passes_liquidity(c: OptionContract, liq: LiquidityConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if c.open_interest < liq.min_option_open_interest:
        reasons.append(f"OI {c.open_interest} < {liq.min_option_open_interest}")
    if c.volume < liq.min_option_volume:
        reasons.append(f"vol {c.volume} < {liq.min_option_volume}")
    sp = _spread_pct(c)
    if sp is None or sp > liq.max_option_bid_ask_spread_pct:
        reasons.append(
            f"spread {sp if sp is not None else 'n/a'}% > {liq.max_option_bid_ask_spread_pct}%"
        )
    return (not reasons, reasons)


def _classify(
    risk_class: RiskClass, day_trade: bool
) -> ContractClassification:
    if risk_class is RiskClass.HEDGE:
        return "hedge"
    if risk_class is RiskClass.LOTTO:
        return "lotto"
    if day_trade:
        return "day"
    return "standard_swing"


def select_contract(
    chain: OptionChain,
    *,
    direction: Direction,
    as_of: date,
    contract_cfg: ContractConfig,
    liquidity: LiquidityConfig,
    risk_class: RiskClass = RiskClass.STANDARD,
    day_trade: bool = False,
) -> ContractSuggestion | None:
    """Return the best contract for the alert, or ``None`` if nothing qualifies.

    Selection rules (spec §7):
    - Calls for LONG, puts for SHORT.
    - DTE in swing band (14-45) for swings, day band (0-7) for day trades.
    - Delta closest to the midpoint of [delta_target_min, delta_target_max]
      (or, for lotto, closest to ``lotto_delta_max`` from below).
    - Reject contracts failing liquidity (OI, volume, spread).
    """
    want_type = OptionType.CALL if direction is Direction.LONG else OptionType.PUT
    dte_min, dte_max = (
        (contract_cfg.day_dte_min, contract_cfg.day_dte_max)
        if day_trade
        else (contract_cfg.swing_dte_min, contract_cfg.swing_dte_max)
    )

    if risk_class is RiskClass.LOTTO:
        target_delta = contract_cfg.lotto_delta_max
    else:
        target_delta = (contract_cfg.delta_target_min + contract_cfg.delta_target_max) / 2.0
    if direction is Direction.SHORT:
        target_delta = -target_delta

    candidates: list[OptionContract] = []
    for c in chain.contracts:
        if c.type is not want_type:
            continue
        dte = (c.expiry - as_of).days
        if not (dte_min <= dte <= dte_max):
            continue
        ok, _ = _passes_liquidity(c, liquidity)
        if not ok:
            continue
        if c.delta is None:
            continue
        candidates.append(c)

    if not candidates:
        return None

    candidates.sort(key=lambda x: abs((x.delta or 0.0) - target_delta))
    best = candidates[0]
    return ContractSuggestion(
        ticker=best.ticker,
        direction="long_call" if want_type is OptionType.CALL else "long_put",
        expiry=best.expiry,
        strike=best.strike,
        delta=best.delta,
        bid_ask_spread_pct=_spread_pct(best),
        classification=_classify(risk_class, day_trade),
        open_interest=best.open_interest,
        volume=best.volume,
    )


def list_rejections(
    chain: OptionChain, liquidity: LiquidityConfig
) -> list[ContractRejection]:
    """Diagnostic helper: every contract that fails the liquidity floor."""
    rejected: list[ContractRejection] = []
    for c in chain.contracts:
        ok, reasons = _passes_liquidity(c, liquidity)
        if not ok:
            rejected.append(ContractRejection(c, reasons))
    return rejected


__all__ = [
    "ContractClassification",
    "ContractRejection",
    "list_rejections",
    "select_contract",
]
