"""Setup F — index tactical (SPY/QQQ day-trade)."""

from __future__ import annotations

from trading_engine.core.types import Direction, SetupType, Signal, Timeframe
from trading_engine.features.indicators import opening_range, vwap_position
from trading_engine.setups.base import SetupContext, _new_signal, regime_allows_long

_INDEX_SYMBOLS = {"SPY", "QQQ", "SPX", "IWM"}


class IndexTacticalSetup:
    setup_type = SetupType.F_INDEX_TACTICAL
    explanation = "Index ORB / VWAP reclaim — day-trade only."

    def detect(self, context: SetupContext) -> list[Signal]:
        if context.symbol not in _INDEX_SYMBOLS:
            return []
        if not regime_allows_long(context.regime):
            return []
        intraday = context.candles.get(Timeframe.M5.value)
        if not intraday:
            return []
        orb = opening_range(intraday, bars=6)
        if orb is None:
            return []
        high, low = orb
        close = float(intraday.to_dataframe()["close"].iloc[-1])
        if vwap_position(intraday) != "above" or close <= high:
            return []
        return [
            _new_signal(
                context,
                self.setup_type,
                Direction.LONG,
                trigger=high,
                stop=low,
                rationale=self.explanation,
                reason_codes=["index_orb_reclaim"],
                confidence=0.65,
            )
        ]
