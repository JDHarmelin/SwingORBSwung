"""Setup E — Relative weakness breakdown (spec §6 E).

Stock underperforming market/sector loses a key support pivot. Put setup only
when the regime allows shorts.
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


class RelativeWeaknessBreakdown:
    setup_type = SetupType.E_RELATIVE_WEAKNESS
    explanation = "Underperforming name breaks key support — put setup."

    def detect(self, ctx: SetupContext) -> list[Signal]:
        if ctx.regime.regime is RegimeType.NO_TRADE:
            return []
        if not regime_allows(ctx.regime, want_short=True):
            return []

        # Must be relatively weak: negative RS score and/or weak sector.
        rs = ctx.symbol_score.rs_score if ctx.symbol_score else 0.0
        weak = rs < 0 or ctx.sector_composite < 0
        if not weak:
            return []

        trend = trend_score(ctx.daily)
        atr = last_atr(ctx.daily)
        if atr <= 0 or trend.score >= 0:
            return []

        support = recent_swing_low(ctx.daily, exclude_last=1)
        close = last_close(ctx.daily)
        if support is None or close >= support:
            return []  # support must be lost

        stop = (recent_swing_high(ctx.daily) or (close + atr))
        return [
            build_signal(
                ctx,
                setup=self.setup_type,
                direction=Direction.SHORT,
                trigger_price=support,
                stop_price=max(stop, support + 0.25 * atr),
                rationale=(
                    f"{ctx.symbol} is weak vs market (RS {rs:+.2f}) and lost support {support:.2f}."
                ),
                setup_quality=min(1.0, abs(rs) + 0.3),
                reason_codes=["Relative weakness", "Lost key support", *trend.reason_codes[:1]],
            )
        ]


__all__ = ["RelativeWeaknessBreakdown"]
