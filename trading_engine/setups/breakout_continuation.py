"""Setup A — breakout continuation."""

from __future__ import annotations

from trading_engine.core.types import Direction, SetupType, Signal, Timeframe
from trading_engine.features.indicators import prior_day_high_low
from trading_engine.features.volume import volume_expansion_score
from trading_engine.setups.base import SetupContext, _new_signal, regime_allows_long


class BreakoutContinuationSetup:
    setup_type = SetupType.A_BREAKOUT_CONTINUATION
    explanation = "Break prior day high with volume expansion in ranked long bucket."

    def detect(self, context: SetupContext) -> list[Signal]:
        if not regime_allows_long(context.regime):
            return []
        if context.symbol_score.composite_score < 0.55:
            return []
        daily = context.candles.get(Timeframe.D1.value)
        if not daily:
            return []
        pdh, _ = prior_day_high_low(daily)
        if pdh is None:
            return []
        close = float(daily.to_dataframe()["close"].iloc[-1])
        vol = volume_expansion_score(daily)
        if close <= pdh or vol.ratio < 1.2:
            return []
        stop = close * 0.97
        return [
            _new_signal(
                context,
                self.setup_type,
                Direction.LONG,
                trigger=pdh,
                stop=stop,
                rationale=self.explanation,
                reason_codes=["breakout_pdh", *vol.reason_codes],
                confidence=min(0.95, context.symbol_score.composite_score),
            )
        ]
