"""Setup B — Breakout retest (spec §6 B).

A prior breakout level is retested and holds: price pulled back toward a broken
swing high and the latest candle reclaims back above it.
"""

from __future__ import annotations

from trading_engine.core.types import Direction, RegimeType, SetupType, Signal
from trading_engine.features.trend import trend_score
from trading_engine.scanners.market_regime import regime_allows
from trading_engine.setups.base import SetupContext, build_signal
from trading_engine.setups.levels import (
    last_atr,
    last_close,
    recent_swing_high,
    recent_swing_low,
)


class BreakoutRetest:
    setup_type = SetupType.B_BREAKOUT_RETEST
    explanation = "Reclaim of a prior breakout level after a successful retest."

    def detect(self, ctx: SetupContext) -> list[Signal]:
        if ctx.regime.regime is RegimeType.NO_TRADE:
            return []
        if not regime_allows(ctx.regime, want_short=False):
            return []
        trend = trend_score(ctx.daily)
        if trend.score <= 0:
            return []
        atr = last_atr(ctx.daily)
        if atr <= 0:
            return []

        df = ctx.daily.to_dataframe()
        close = last_close(ctx.daily)
        level = recent_swing_high(ctx.daily, exclude_last=3)
        if level is None:
            return []

        # Retest signature: in the last few bars price dipped to within ~1 ATR
        # of the level (the retest) and the final close reclaims above it.
        recent_lows = df["low"].iloc[-4:-1]
        retested = bool((recent_lows <= level + 0.5 * atr).any())
        reclaim = close > level
        if not (retested and reclaim):
            return []

        stop = (recent_swing_low(ctx.daily) or (level - atr))
        stop = min(stop, level - 0.25 * atr)
        return [
            build_signal(
                ctx,
                setup=self.setup_type,
                direction=Direction.LONG,
                trigger_price=level,
                stop_price=stop,
                rationale=f"{ctx.symbol} retested {level:.2f} and reclaimed — breakout holding.",
                setup_quality=0.7,
                reason_codes=["Prior breakout retested and reclaimed", *trend.reason_codes[:1]],
            )
        ]


__all__ = ["BreakoutRetest"]
