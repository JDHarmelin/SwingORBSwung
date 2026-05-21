"""Risk classification — spec §8."""

from __future__ import annotations

from trading_engine.core.types import RiskClass, SetupType, Signal


def classify_risk(signal: Signal) -> RiskClass:
    if signal.setup_type == SetupType.F_INDEX_TACTICAL:
        return RiskClass.STANDARD
    if signal.confidence >= 0.85 and len(signal.reason_codes) >= 3:
        return RiskClass.A_PLUS
    if signal.confidence < 0.55:
        return RiskClass.LOTTO
    if signal.direction.value == "short" and signal.setup_type.value.startswith("E"):
        return RiskClass.HEDGE
    return RiskClass.STANDARD
