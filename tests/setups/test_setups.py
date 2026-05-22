"""Setup detector behaviour on crafted triggers + non-trigger fixtures."""

from __future__ import annotations

from trading_engine.core.types import Direction, SetupType
from trading_engine.setups import ALL_DETECTORS
from trading_engine.setups.base import SetupContext
from trading_engine.setups.breakout_continuation import BreakoutContinuation
from trading_engine.setups.breakout_retest import BreakoutRetest
from trading_engine.setups.compression_break import CompressionBreak
from trading_engine.setups.ema_continuation import EmaContinuation
from trading_engine.setups.index_tactical import IndexTactical
from trading_engine.setups.levels import (
    ema_value,
    last_atr,
    last_close,
    recent_swing_high,
)
from trading_engine.setups.relative_weakness import RelativeWeaknessBreakdown

from .conftest import AS_OF, append_bar, make_symbol_score


def test_registry_has_all_six_setups() -> None:
    types = {d.setup_type for d in ALL_DETECTORS}
    assert types == set(SetupType)
    assert len(ALL_DETECTORS) == 6


def test_breakout_continuation_fires_long(pullback_daily, long_regime) -> None:
    # pullback fixture has a real prior peak (swing high) we can break.
    base = pullback_daily
    level = recent_swing_high(base, exclude_last=1)
    assert level is not None
    series = append_bar(
        base, open_=level, high=level * 1.04, low=level * 0.999,
        close=level * 1.03, volume=4_000_000,
    )
    ctx = SetupContext(symbol="PB8", as_of=AS_OF, daily=series, regime=long_regime)
    signals = BreakoutContinuation().detect(ctx)
    assert len(signals) == 1
    assert signals[0].direction is Direction.LONG
    assert signals[0].setup_type is SetupType.A_BREAKOUT_CONTINUATION
    assert signals[0].trigger_price > 0
    assert signals[0].stop_price < signals[0].trigger_price


def test_breakout_continuation_no_signal_without_volume(chop_daily, long_regime) -> None:
    c = last_close(chop_daily)
    series = append_bar(chop_daily, open_=c, high=c, low=c, close=c, volume=1.0)
    ctx = SetupContext(symbol="CHOP", as_of=AS_OF, daily=series, regime=long_regime)
    assert BreakoutContinuation().detect(ctx) == []


def test_breakout_continuation_blocked_in_no_trade(pullback_daily, no_trade_regime) -> None:
    level = recent_swing_high(pullback_daily, exclude_last=1)
    assert level is not None
    series = append_bar(
        pullback_daily, open_=level, high=level * 1.04, low=level * 0.999,
        close=level * 1.03, volume=4_000_000,
    )
    ctx = SetupContext(symbol="PB8", as_of=AS_OF, daily=series, regime=no_trade_regime)
    assert BreakoutContinuation().detect(ctx) == []


def test_breakout_retest_fires_on_reclaim(pullback_daily, long_regime) -> None:
    base = pullback_daily
    level = recent_swing_high(base, exclude_last=3)
    assert level is not None
    atr = last_atr(base)
    # Three bars: retest near the level, then reclaim well above.
    c0 = last_close(base)
    s = append_bar(base, open_=c0, high=c0, low=level + 0.1 * atr,
                   close=level + 0.5 * atr, volume=1_200_000)
    s = append_bar(s, open_=level + 0.5 * atr, high=level + 0.7 * atr, low=level,
                   close=level + 0.3 * atr, volume=1_000_000)
    s = append_bar(s, open_=level + 0.3 * atr, high=level + 2.5 * atr, low=level + 0.2 * atr,
                   close=level + 2.0 * atr, volume=2_000_000)
    ctx = SetupContext(symbol="PB8", as_of=AS_OF, daily=s, regime=long_regime)
    signals = BreakoutRetest().detect(ctx)
    assert len(signals) == 1
    assert signals[0].setup_type is SetupType.B_BREAKOUT_RETEST
    assert signals[0].direction is Direction.LONG


def test_ema_continuation_fires_on_pullback(uptrend_daily, long_regime) -> None:
    base = uptrend_daily
    ema8 = ema_value(base, 8)
    atr = last_atr(base)
    c = last_close(base)
    series = append_bar(base, open_=c, high=c, low=ema8 - 0.2 * atr, close=ema8, volume=1_000_000)
    ctx = SetupContext(symbol="UPTRD", as_of=AS_OF, daily=series, regime=long_regime)
    signals = EmaContinuation().detect(ctx)
    assert len(signals) == 1
    assert signals[0].setup_type is SetupType.C_EMA_CONTINUATION
    assert signals[0].direction is Direction.LONG


def test_compression_break_fires_long(uptrend_daily, long_regime) -> None:
    base = uptrend_daily
    c = last_close(base)
    # Six tight coil bars to contract ATR, then a volume breakout.
    s = base
    for _ in range(6):
        s = append_bar(s, open_=c, high=c + 0.05, low=c - 0.05, close=c, volume=900_000)
    s = append_bar(s, open_=c, high=c * 1.03, low=c, close=c * 1.028, volume=4_000_000)
    ctx = SetupContext(symbol="UPTRD", as_of=AS_OF, daily=s, regime=long_regime)
    signals = CompressionBreak().detect(ctx)
    assert len(signals) == 1
    assert signals[0].setup_type is SetupType.D_COMPRESSION_BREAK
    assert signals[0].direction is Direction.LONG


def test_relative_weakness_fires_short(breakdown_daily, short_regime) -> None:
    ctx = SetupContext(
        symbol="BRKD",
        as_of=AS_OF,
        daily=breakdown_daily,
        regime=short_regime,
        symbol_score=make_symbol_score("BRKD", rs=-0.5, composite=-0.5),
        sector_composite=-0.3,
    )
    signals = RelativeWeaknessBreakdown().detect(ctx)
    assert len(signals) == 1
    assert signals[0].setup_type is SetupType.E_RELATIVE_WEAKNESS
    assert signals[0].direction is Direction.SHORT
    assert signals[0].stop_price > signals[0].trigger_price


def test_relative_weakness_needs_short_regime(breakdown_daily, long_regime) -> None:
    ctx = SetupContext(
        symbol="BRKD",
        as_of=AS_OF,
        daily=breakdown_daily,
        regime=long_regime,
        symbol_score=make_symbol_score("BRKD", rs=-0.5, composite=-0.5),
    )
    assert RelativeWeaknessBreakdown().detect(ctx) == []


def test_index_tactical_fires_long(uptrend_5m, long_regime) -> None:
    ctx = SetupContext(
        symbol="SPY",
        as_of=AS_OF,
        daily=uptrend_5m,  # unused by F but required
        intraday=uptrend_5m,
        regime=long_regime,
        is_index=True,
    )
    signals = IndexTactical().detect(ctx)
    assert len(signals) == 1
    assert signals[0].setup_type is SetupType.F_INDEX_TACTICAL
    assert "day_trade" in signals[0].reason_codes


def test_index_tactical_skips_non_index(uptrend_5m, long_regime) -> None:
    ctx = SetupContext(
        symbol="AAPL",
        as_of=AS_OF,
        daily=uptrend_5m,
        intraday=uptrend_5m,
        regime=long_regime,
        is_index=False,
    )
    assert IndexTactical().detect(ctx) == []
