"""All setup detectors for orchestrator iteration."""

from __future__ import annotations

from trading_engine.setups.base import Setup
from trading_engine.setups.breakout_continuation import BreakoutContinuationSetup
from trading_engine.setups.breakout_retest import BreakoutRetestSetup
from trading_engine.setups.compression_break import CompressionBreakSetup
from trading_engine.setups.ema_continuation import EmaContinuationSetup
from trading_engine.setups.index_tactical import IndexTacticalSetup
from trading_engine.setups.relative_weakness import RelativeWeaknessSetup


def all_setups() -> list[Setup]:
    return [
        BreakoutContinuationSetup(),
        BreakoutRetestSetup(),
        EmaContinuationSetup(),
        CompressionBreakSetup(),
        RelativeWeaknessSetup(),
        IndexTacticalSetup(),
    ]
