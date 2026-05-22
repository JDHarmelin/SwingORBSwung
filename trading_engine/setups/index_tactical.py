"""Setup F — Index tactical (spec §6 F).

SPY/QQQ-style intraday opening-range break / reclaim. Day-trade alerts only;
requires an intraday series and an index context.
"""

from __future__ import annotations

from trading_engine.core.types import Direction, RegimeType, SetupType, Signal
from trading_engine.features.indicators import above_vwap, opening_range
from trading_engine.scanners.market_regime import regime_allows
from trading_engine.setups.base import SetupContext, build_signal


class IndexTactical:
    setup_type = SetupType.F_INDEX_TACTICAL
    explanation = "Intraday opening-range break / VWAP reclaim on an index (day trade)."

    def detect(self, ctx: SetupContext) -> list[Signal]:
        if not ctx.is_index or ctx.intraday is None:
            return []
        if ctx.regime.regime is RegimeType.NO_TRADE:
            return []

        try:
            orange = opening_range(ctx.intraday, minutes=15)
        except ValueError:
            return []
        df = ctx.intraday.to_dataframe()
        close = float(df["close"].iloc[-1])
        last_above_vwap = bool(above_vwap(ctx.intraday).iloc[-1])

        # Long ORB breakout with VWAP support.
        if close > orange.high and last_above_vwap and regime_allows(ctx.regime, want_short=False):
            return [
                build_signal(
                    ctx,
                    setup=self.setup_type,
                    direction=Direction.LONG,
                    trigger_price=orange.high,
                    stop_price=orange.low,
                    rationale=f"{ctx.symbol} broke the opening range high {orange.high:.2f} above VWAP.",
                    setup_quality=0.55,
                    reason_codes=["Opening-range breakout", "Above VWAP", "day_trade"],
                )
            ]

        # Short ORB breakdown below VWAP.
        if close < orange.low and not last_above_vwap and regime_allows(ctx.regime, want_short=True):
            return [
                build_signal(
                    ctx,
                    setup=self.setup_type,
                    direction=Direction.SHORT,
                    trigger_price=orange.low,
                    stop_price=orange.high,
                    rationale=f"{ctx.symbol} broke the opening range low {orange.low:.2f} below VWAP.",
                    setup_quality=0.55,
                    reason_codes=["Opening-range breakdown", "Below VWAP", "day_trade"],
                )
            ]
        return []


__all__ = ["IndexTactical"]
