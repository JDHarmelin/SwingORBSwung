"""Setup detection engine."""

from trading_engine.setups.base import Setup, SetupContext
from trading_engine.setups.registry import all_setups

__all__ = ["Setup", "SetupContext", "all_setups"]
