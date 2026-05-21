"""Setup E — relative weakness breakdown (short)."""

from __future__ import annotations

from trading_engine.core.types import Direction, SetupType, Signal, Timeframe
from trading_engine.setups.base import SetupContext, _new_signal, regime_allows_short


class RelativeWeaknessSetup:
    setup_type = SetupType.E_RELATIVE_WEAKNESS
    explanation = "Underperformance breakdown — short when regime allows."

    def detect(self, context: SetupContext) -> list[Signal]:
        if not regime_allows_short(context.regime):
            return []
        if context.symbol_score.rs_score > 0.45:
            return []
        daily = context.candles.get(Timeframe.D1.value)
        if not daily:
            return []
        df = daily.to_dataframe()
        support = float(df["low"].iloc[-15:-3].min()) if len(df) > 15 else float(df["low"].iloc[:-1].min())
        close = float(df["close"].iloc[-1])
        if close > support * 1.002:
            return []
        return [
            _new_signal(
                context,
                self.setup_type,
                Direction.SHORT,
                trigger=support,
                stop=close * 1.03,
                rationale=self.explanation,
                reason_codes=["relative_weakness_break"],
                confidence=0.7,
            )
        ]
