"""Setup D — compression / flag break."""

from __future__ import annotations

from trading_engine.core.types import Direction, SetupType, Signal, Timeframe
from trading_engine.features.compression import compute_structure_score, trendline_break
from trading_engine.setups.base import SetupContext, _new_signal, regime_allows_long


class CompressionBreakSetup:
    setup_type = SetupType.D_COMPRESSION_BREAK
    explanation = "Compression break with volume expansion."

    def detect(self, context: SetupContext) -> list[Signal]:
        if not regime_allows_long(context.regime):
            return []
        daily = context.candles.get(Timeframe.D1.value)
        if not daily:
            return []
        struct = compute_structure_score(daily)
        if not (struct.compression_detected or trendline_break(daily)):
            return []
        close = float(daily.to_dataframe()["close"].iloc[-1])
        stop = close * 0.96
        return [
            _new_signal(
                context,
                self.setup_type,
                Direction.LONG,
                trigger=close,
                stop=stop,
                rationale=self.explanation,
                reason_codes=struct.reason_codes,
                confidence=0.78,
            )
        ]
