"""Setup A — Breakout continuation (spec §6 A).

Top-ranked long (or short) name breaks a recent swing high (low) with volume
expansion and positive relative strength, trend already aligned.
"""

from __future__ import annotations

from trading_engine.core.types import Direction, RegimeType, SetupType, Signal
from trading_engine.features.trend import trend_score
from trading_engine.features.volume import volume_expansion_score
from trading_engine.scanners.market_regime import regime_allows
from trading_engine.setups.base import SetupContext, build_signal
from trading_engine.setups.levels import (
    last_atr,
    last_close,
    recent_swing_high,
    recent_swing_low,
)


class BreakoutContinuation:
    setup_type = SetupType.A_BREAKOUT_CONTINUATION
    explanation = "Breakout above prior resistance with volume in a trending name."

    def detect(self, ctx: SetupContext) -> list[Signal]:
        if ctx.regime.regime is RegimeType.NO_TRADE:
            return []
        trend = trend_score(ctx.daily)
        vol = volume_expansion_score(ctx.daily)
        close = last_close(ctx.daily)
        atr = last_atr(ctx.daily)
        if atr <= 0 or vol.score <= 0:
            return []

        # Long breakout.
        if trend.score > 0 and regime_allows(ctx.regime, want_short=False):
            level = recent_swing_high(ctx.daily)
            if level is not None and close > level:
                stop_ref = recent_swing_low(ctx.daily) or (level - atr)
                stop = min(stop_ref, level - 0.25 * atr)
                reasons = ["Breakout > prior swing high", *vol.reason_codes[:1], *trend.reason_codes[:1]]
                return [
                    build_signal(
                        ctx,
                        setup=self.setup_type,
                        direction=Direction.LONG,
                        trigger_price=level,
                        stop_price=stop,
                        rationale=f"{ctx.symbol} broke {level:.2f} on volume in an uptrend.",
                        setup_quality=min(1.0, vol.relative_volume / 2.0),
                        reason_codes=reasons,
                    )
                ]

        # Short breakdown (mirror).
        if trend.score < 0 and regime_allows(ctx.regime, want_short=True):
            level = recent_swing_low(ctx.daily)
            if level is not None and close < level:
                stop_ref = recent_swing_high(ctx.daily) or (level + atr)
                stop = max(stop_ref, level + 0.25 * atr)
                reasons = ["Breakdown < prior swing low", *vol.reason_codes[:1], *trend.reason_codes[:1]]
                return [
                    build_signal(
                        ctx,
                        setup=self.setup_type,
                        direction=Direction.SHORT,
                        trigger_price=level,
                        stop_price=stop,
                        rationale=f"{ctx.symbol} broke down through {level:.2f} on volume.",
                        setup_quality=min(1.0, vol.relative_volume / 2.0),
                        reason_codes=reasons,
                    )
                ]
        return []


__all__ = ["BreakoutContinuation"]
