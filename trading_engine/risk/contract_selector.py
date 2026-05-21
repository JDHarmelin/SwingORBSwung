"""Contract selection — spec §7."""

from __future__ import annotations

from trading_engine.core.config import AppConfig, load_app_config
from trading_engine.core.types import (
    ContractSuggestion,
    Direction,
    OptionChain,
    OptionType,
    SetupType,
    Signal,
)


def _direction_label(signal: Signal, opt_type: OptionType) -> str:
    if signal.direction == Direction.LONG:
        return "long_call" if opt_type == OptionType.CALL else "long_put"
    return "short_put" if opt_type == OptionType.PUT else "short_call"


def select_contract(
    signal: Signal,
    chain: OptionChain,
    *,
    config: AppConfig | None = None,
    day_trade: bool = False,
) -> ContractSuggestion | None:
    config = config or load_app_config()
    cc = config.settings.contract
    liq = config.settings.liquidity
    today = chain.snapshot_at.date()
    opt_type = OptionType.CALL if signal.direction == Direction.LONG else OptionType.PUT

    candidates = []
    for c in chain.contracts:
        if c.type != opt_type:
            continue
        dte = (c.expiry - today).days
        if day_trade or signal.setup_type == SetupType.F_INDEX_TACTICAL:
            if not (cc.day_dte_min <= dte <= cc.day_dte_max):
                continue
        else:
            if not (cc.swing_dte_min <= dte <= cc.swing_dte_max):
                continue
        if c.open_interest < liq.min_option_open_interest:
            continue
        if c.volume < liq.min_option_volume:
            continue
        spread = c.spread_pct
        if spread is None or spread > cc.reject_if_spread_pct_above:
            continue
        delta = abs(c.delta or 0)
        if not (cc.delta_target_min <= delta <= cc.delta_target_max):
            continue
        candidates.append(c)

    if not candidates:
        return None

    best = min(candidates, key=lambda c: abs(abs(c.delta or 0) - 0.375))
    spread = best.spread_pct
    return ContractSuggestion(
        ticker=best.ticker,
        direction=_direction_label(signal, opt_type),
        expiry=best.expiry,
        strike=best.strike,
        delta=best.delta,
        bid_ask_spread_pct=spread,
        classification="standard_swing" if not day_trade else "day",
        open_interest=best.open_interest,
        volume=best.volume,
    )
