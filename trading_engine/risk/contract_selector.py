"""Contract selection engine (spec §7).

Pick the option contract that best matches the alert's direction, DTE band,
delta target, and liquidity floor. Rejects illiquid contracts outright per
the non-negotiable design rule.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
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


@dataclass
class SelectionDiagnostics:
    """Per-stage funnel counts + a human-readable summary.

    Lets callers (signal_service, alert formatter) explain *why* no
    contract was picked instead of a generic "Awaiting chain". All counts
    refer to the right-sided (CALL or PUT) leg only.
    """

    symbol: str
    chain_size: int = 0
    after_type: int = 0
    after_dte: int = 0
    after_liquidity: int = 0
    after_delta: int = 0
    rejection_reasons: Counter[str] = field(default_factory=Counter)
    dte_window: tuple[int, int] = (0, 0)
    liquidity_floor: tuple[int, int, float] = (0, 0, 0.0)  # oi, vol, spread%

    def short_reason(self) -> str:
        """One-line human summary suitable for an alert footer."""
        if self.chain_size == 0:
            return "provider returned 0 contracts (entitlement / fetch issue)"
        if self.after_type == 0:
            return f"no contracts of requested type in chain of {self.chain_size}"
        if self.after_dte == 0:
            lo, hi = self.dte_window
            return (
                f"no contracts in DTE window [{lo}, {hi}] "
                f"({self.after_type} of correct type)"
            )
        if self.after_liquidity == 0:
            oi, vol, sp = self.liquidity_floor
            top = ", ".join(
                f"{k} ({n})" for k, n in self.rejection_reasons.most_common(2)
            ) or "n/a"
            return (
                f"none passed liquidity floor "
                f"(OI>={oi}, vol>={vol}, spread<={sp}%); top rejects: {top}"
            )
        if self.after_delta == 0:
            return f"no contracts with delta populated ({self.after_liquidity} otherwise OK)"
        return "no contract selected"


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

    Backwards-compatible wrapper around :func:`select_contract_with_diagnostics`
    that drops the diagnostics. Prefer the diagnostics variant in new code so
    operators can see *why* nothing was picked.
    """
    suggestion, _ = select_contract_with_diagnostics(
        chain,
        direction=direction,
        as_of=as_of,
        contract_cfg=contract_cfg,
        liquidity=liquidity,
        risk_class=risk_class,
        day_trade=day_trade,
    )
    return suggestion


def select_contract_with_diagnostics(
    chain: OptionChain,
    *,
    direction: Direction,
    as_of: date,
    contract_cfg: ContractConfig,
    liquidity: LiquidityConfig,
    risk_class: RiskClass = RiskClass.STANDARD,
    day_trade: bool = False,
) -> tuple[ContractSuggestion | None, SelectionDiagnostics]:
    """Like :func:`select_contract` but also returns a funnel summary.

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

    diag = SelectionDiagnostics(
        symbol=chain.underlying,
        chain_size=len(chain.contracts),
        dte_window=(dte_min, dte_max),
        liquidity_floor=(
            liquidity.min_option_open_interest,
            liquidity.min_option_volume,
            liquidity.max_option_bid_ask_spread_pct,
        ),
    )

    candidates: list[OptionContract] = []
    for c in chain.contracts:
        if c.type is not want_type:
            continue
        diag.after_type += 1
        dte = (c.expiry - as_of).days
        if not (dte_min <= dte <= dte_max):
            diag.rejection_reasons["dte_out_of_window"] += 1
            continue
        diag.after_dte += 1
        ok, reasons = _passes_liquidity(c, liquidity)
        if not ok:
            for r in reasons:
                # Bucket on the leading metric name (OI / vol / spread).
                key = r.split()[0] if r else "unknown"
                diag.rejection_reasons[key] += 1
            continue
        diag.after_liquidity += 1
        if c.delta is None:
            diag.rejection_reasons["delta_missing"] += 1
            continue
        diag.after_delta += 1
        candidates.append(c)

    if not candidates:
        return None, diag

    candidates.sort(key=lambda x: abs((x.delta or 0.0) - target_delta))
    best = candidates[0]
    suggestion = ContractSuggestion(
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
    return suggestion, diag


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
    "SelectionDiagnostics",
    "list_rejections",
    "select_contract",
    "select_contract_with_diagnostics",
]
