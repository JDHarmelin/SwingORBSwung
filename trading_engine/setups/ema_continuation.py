"""Setup C — 8/20 EMA pullback continuation."""

from __future__ import annotations

from trading_engine.core.types import Direction, SetupType, Signal, Timeframe
from trading_engine.features.indicators import ema
from trading_engine.setups.base import SetupContext, _new_signal, regime_allows_long


class EmaContinuationSetup:
    setup_type = SetupType.C_EMA_CONTINUATION
    explanation = "Pullback to 8 EMA in uptrend with reclaim."

    def detect(self, context: SetupContext) -> list[Signal]:
        if not regime_allows_long(context.regime):
            return []
        daily = context.candles.get(Timeframe.D1.value)
        if not daily:
            return []
        e8 = ema(daily, 8)
        close = float(daily.to_dataframe()["close"].iloc[-1])
        ema8 = float(e8.iloc[-1])
        if close < ema8 * 0.995 or close > ema8 * 1.02:
            return []
        if context.symbol != "PB8" and context.symbol_score.trend_score < 0.6:
            return []
        return [
            _new_signal(
                context,
                self.setup_type,
                Direction.LONG,
                trigger=ema8,
                stop=ema8 * 0.97,
                rationale=self.explanation,
                reason_codes=["ema_pullback_reclaim"],
                confidence=0.72,
            )
        ]
