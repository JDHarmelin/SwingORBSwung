"""Setup detection engine (spec §6).

Each detector is independent and testable; ``ALL_DETECTORS`` and
``EQUITY_DETECTORS`` / ``INDEX_DETECTORS`` are the registries the signal
service iterates over.
"""

from trading_engine.setups.base import (
    SetupContext,
    SetupDetector,
    build_signal,
    make_signal_id,
)
from trading_engine.setups.breakout_continuation import BreakoutContinuation
from trading_engine.setups.breakout_retest import BreakoutRetest
from trading_engine.setups.compression_break import CompressionBreak
from trading_engine.setups.ema_continuation import EmaContinuation
from trading_engine.setups.index_tactical import IndexTactical
from trading_engine.setups.relative_weakness import RelativeWeaknessBreakdown

EQUITY_DETECTORS: list[SetupDetector] = [
    BreakoutContinuation(),
    BreakoutRetest(),
    EmaContinuation(),
    CompressionBreak(),
    RelativeWeaknessBreakdown(),
]

INDEX_DETECTORS: list[SetupDetector] = [
    IndexTactical(),
]

ALL_DETECTORS: list[SetupDetector] = [*EQUITY_DETECTORS, *INDEX_DETECTORS]

__all__ = [
    "ALL_DETECTORS",
    "EQUITY_DETECTORS",
    "INDEX_DETECTORS",
    "BreakoutContinuation",
    "BreakoutRetest",
    "CompressionBreak",
    "EmaContinuation",
    "IndexTactical",
    "RelativeWeaknessBreakdown",
    "SetupContext",
    "SetupDetector",
    "build_signal",
    "make_signal_id",
]
