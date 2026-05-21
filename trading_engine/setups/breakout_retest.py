"""Setup B — breakout retest."""

from __future__ import annotations

from trading_engine.core.types import Direction, SetupType, Signal, Timeframe
from trading_engine.setups.base import SetupContext, _new_signal, regime_allows_long


class BreakoutRetestSetup:
    setup_type = SetupType.B_BREAKOUT_RETEST
    explanation = "Retest of prior breakout level with reclaim."

    def detect(self, context: SetupContext) -> list[Signal]:
        if not regime_allows_long(context.regime):
            return []
        daily = context.candles.get(Timeframe.D1.value)
        if not daily or len(daily.candles) < 5:
            return []
        df = daily.to_dataframe()
        resistance = float(df["high"].iloc[-6:-2].max())
        low = float(df["low"].iloc[-1])
        close = float(df["close"].iloc[-1])
        if low > resistance * 0.995 or close <= resistance:
            return []
        return [
            _new_signal(
                context,
                self.setup_type,
                Direction.LONG,
                trigger=resistance,
                stop=low * 0.99,
                rationale=self.explanation,
                reason_codes=["breakout_retest_hold"],
                confidence=0.7,
            )
        ]
