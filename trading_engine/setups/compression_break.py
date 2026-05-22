"""Setup D — Compression / wedge / flag break (spec §6 D).

Range contraction followed by an expansion candle that breaks the coil's local
high (low) on volume. Reuses the Wave 1 structure primitives.
"""

from __future__ import annotations

from trading_engine.core.types import Direction, RegimeType, SetupType, Signal
from trading_engine.features.compression import (
    range_contraction_ratio,
    structure_score,
    trendline_break,
)
from trading_engine.features.volume import volume_expansion_score
from trading_engine.scanners.market_regime import regime_allows
from trading_engine.setups.base import SetupContext, build_signal
from trading_engine.setups.levels import (
    last_atr,
    last_close,
    recent_swing_high,
    recent_swing_low,
)


class CompressionBreak:
    setup_type = SetupType.D_COMPRESSION_BREAK
    explanation = "Break of a compressed range / wedge / flag with expanding volume."

    def detect(self, ctx: SetupContext) -> list[Signal]:
        if ctx.regime.regime is RegimeType.NO_TRADE:
            return []
        ratio = range_contraction_ratio(ctx.daily)
        vol = volume_expansion_score(ctx.daily)
        atr = last_atr(ctx.daily)
        if atr <= 0:
            return []
        # Require prior compression and a volume-confirmed expansion now.
        compressed = ratio == ratio and ratio < 0.9  # not NaN and contracted
        if not compressed or vol.score <= 0:
            return []

        struct = structure_score(ctx.daily)
        tb = trendline_break(ctx.daily)
        close = last_close(ctx.daily)

        # Long: breaking up out of the coil.
        if (
            struct.breakout_distance_pct == struct.breakout_distance_pct
            and close > 0
            and regime_allows(ctx.regime, want_short=False)
            and (struct.breakout_distance_pct > -0.5 or (tb is not None and tb.direction == "up"))
        ):
            level = recent_swing_high(ctx.daily) or close
            stop = (recent_swing_low(ctx.daily) or (close - atr))
            return [
                build_signal(
                    ctx,
                    setup=self.setup_type,
                    direction=Direction.LONG,
                    trigger_price=level,
                    stop_price=min(stop, level - 0.25 * atr),
                    rationale=f"{ctx.symbol} broke out of compression (ATR ratio {ratio:.2f}).",
                    setup_quality=min(1.0, (1.0 - ratio) + vol.score * 0.3),
                    reason_codes=["Compression break + volume", *vol.reason_codes[:1]],
                )
            ]

        # Short: breaking down out of the coil.
        if tb is not None and tb.direction == "down" and regime_allows(ctx.regime, want_short=True):
            level = recent_swing_low(ctx.daily) or close
            stop = (recent_swing_high(ctx.daily) or (close + atr))
            return [
                build_signal(
                    ctx,
                    setup=self.setup_type,
                    direction=Direction.SHORT,
                    trigger_price=level,
                    stop_price=max(stop, level + 0.25 * atr),
                    rationale=f"{ctx.symbol} broke down out of compression (ATR ratio {ratio:.2f}).",
                    setup_quality=min(1.0, (1.0 - ratio) + vol.score * 0.3),
                    reason_codes=["Compression breakdown + volume", *vol.reason_codes[:1]],
                )
            ]
        return []


__all__ = ["CompressionBreak"]
