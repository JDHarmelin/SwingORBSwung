"""Setup detector tests."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_engine.core.types import Direction, MarketRegime, RegimeType, Timeframe
from trading_engine.core.types import SymbolScore as SS
from trading_engine.setups.base import SetupContext
from trading_engine.setups.compression_break import CompressionBreakSetup
from trading_engine.setups.ema_continuation import EmaContinuationSetup
from trading_engine.setups.registry import all_setups
from trading_engine.setups.relative_weakness import RelativeWeaknessSetup
from trading_engine.testing.synthetic import (
    clean_uptrend_series,
    compression_then_breakout_series,
    pullback_to_8ema_series,
)


def _score(sym: str, composite: float = 0.7) -> SS:
    return SS(
        timestamp=datetime.now(tz=UTC),
        symbol=sym,
        direction_bucket=Direction.LONG,
        rs_score=0.7,
        sector_score=0.6,
        structure_score=0.6,
        trend_score=0.7,
        volume_score=0.5,
        catalyst_score=0.0,
        composite_score=composite,
    )


def _ctx(sym: str, series, regime: RegimeType = RegimeType.LONG_BIAS) -> SetupContext:
    return SetupContext(
        symbol=sym,
        candles={Timeframe.D1.value: series},
        regime=MarketRegime(
            timestamp=datetime.now(tz=UTC),
            regime=regime,
            confidence=0.8,
            notes=[],
        ),
        symbol_score=_score(sym),
    )


def test_registry_has_six() -> None:
    assert len(all_setups()) == 6


def test_ema_fires_on_pb8() -> None:
    det = EmaContinuationSetup()
    signals = det.detect(_ctx("PB8", pullback_to_8ema_series("PB8")))
    assert len(signals) >= 1


def test_compression_on_flag() -> None:
    det = CompressionBreakSetup()
    signals = det.detect(_ctx("FLAG", compression_then_breakout_series("FLAG")))
    assert len(signals) >= 1


def test_relative_weakness_blocked_long_regime() -> None:
    det = RelativeWeaknessSetup()
    s = det.detect(_ctx("BRKD", clean_uptrend_series("BRKD"), regime=RegimeType.LONG_BIAS))
    assert len(s) == 0


def test_relative_weakness_short_regime() -> None:
    det = RelativeWeaknessSetup()
    from trading_engine.testing.synthetic import breakdown_series

    score = _score("BRKD", composite=0.3)
    score = SS(**{**score.model_dump(), "rs_score": 0.2, "composite_score": 0.3})
    ctx = SetupContext(
        symbol="BRKD",
        candles={Timeframe.D1.value: breakdown_series("BRKD")},
        regime=MarketRegime(
            timestamp=datetime.now(tz=UTC),
            regime=RegimeType.SHORT_BIAS,
            confidence=0.8,
            notes=[],
        ),
        symbol_score=score,
    )
    signals = det.detect(ctx)
    assert len(signals) >= 1
    assert signals[0].direction == Direction.SHORT
