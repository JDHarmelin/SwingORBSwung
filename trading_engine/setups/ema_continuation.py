"""Setup C — 8 EMA continuation (spec §6 C).

Strong uptrend pulls back to the 8 EMA, holds, and resumes. Mirror for shorts
(pullback up to the 8 EMA in a downtrend).
"""

from __future__ import annotations

import numpy as np

from trading_engine.core.types import Direction, RegimeType, SetupType, Signal
from trading_engine.features.trend import trend_score
from trading_engine.scanners.market_regime import regime_allows
from trading_engine.setups.base import SetupContext, build_signal
from trading_engine.setups.levels import (
    ema_value,
    highest_high,
    last_atr,
    last_close,
    lowest_low,
)


class EmaContinuation:
    setup_type = SetupType.C_EMA_CONTINUATION
    explanation = "Pullback to the 8 EMA in a trend that then resumes."

    def detect(self, ctx: SetupContext) -> list[Signal]:
        if ctx.regime.regime is RegimeType.NO_TRADE:
            return []
        trend = trend_score(ctx.daily)
        atr = last_atr(ctx.daily)
        ema8 = ema_value(ctx.daily, 8)
        ema50 = ema_value(ctx.daily, 50)
        if atr <= 0 or np.isnan(ema8) or np.isnan(ema50):
            return []
        close = last_close(ctx.daily)
        near_ema = abs(close - ema8) <= 1.2 * atr

        # Long continuation: longer-term up, price pulled back to the 8 EMA.
        if (
            trend.direction.value != "downtrend"
            and ema8 > ema50
            and near_ema
            and close >= ema8 - 0.5 * atr
            and regime_allows(ctx.regime, want_short=False)
        ):
            trigger = highest_high(ctx.daily, lookback=5, exclude_last=0)
            stop = min(ema8 - atr, lowest_low(ctx.daily, lookback=5, exclude_last=0))
            return [
                build_signal(
                    ctx,
                    setup=self.setup_type,
                    direction=Direction.LONG,
                    trigger_price=trigger,
                    stop_price=stop,
                    rationale=f"{ctx.symbol} pulled back to the 8 EMA ({ema8:.2f}) and is resuming.",
                    setup_quality=0.65,
                    reason_codes=["Pullback to 8 EMA in uptrend", *trend.reason_codes[:1]],
                    confidence_components={
                        "trend_score": float(trend.score),
                        "ema_stack": float(ema8 - ema50),
                        "distance_to_ema_atr": float(abs(close - ema8) / atr),
                    },
                )
            ]

        # Short continuation (mirror).
        if (
            trend.direction.value != "uptrend"
            and ema8 < ema50
            and near_ema
            and close <= ema8 + 0.5 * atr
            and regime_allows(ctx.regime, want_short=True)
        ):
            trigger = lowest_low(ctx.daily, lookback=5, exclude_last=0)
            stop = max(ema8 + atr, highest_high(ctx.daily, lookback=5, exclude_last=0))
            return [
                build_signal(
                    ctx,
                    setup=self.setup_type,
                    direction=Direction.SHORT,
                    trigger_price=trigger,
                    stop_price=stop,
                    rationale=f"{ctx.symbol} bounced to the 8 EMA ({ema8:.2f}) in a downtrend.",
                    setup_quality=0.6,
                    reason_codes=["Pullback to 8 EMA in downtrend", *trend.reason_codes[:1]],
                    confidence_components={
                        "trend_score": float(trend.score),
                        "ema_stack": float(ema8 - ema50),
                        "distance_to_ema_atr": float(abs(close - ema8) / atr),
                    },
                )
            ]
        return []


__all__ = ["EmaContinuation"]
