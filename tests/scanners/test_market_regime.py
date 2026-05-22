"""Market regime classification."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_engine.core.types import RegimeType, Timeframe
from trading_engine.scanners.market_regime import (
    RegimeInputs,
    classify_regime,
    regime_allows,
)
from trading_engine.testing.synthetic import breakdown_series, clean_uptrend_series

_AS_OF = datetime(2026, 5, 19, 20, 0, tzinfo=UTC)


def test_uptrending_indices_give_long_bias() -> None:
    indices = [
        RegimeInputs("SPY", clean_uptrend_series(symbol="SPY", timeframe=Timeframe.D1)),
        RegimeInputs("QQQ", clean_uptrend_series(symbol="QQQ", timeframe=Timeframe.D1, seed=9)),
    ]
    regime = classify_regime(indices, as_of=_AS_OF)
    assert regime.regime is RegimeType.LONG_BIAS
    assert regime.confidence > 0.5
    assert regime_allows(regime, want_short=False)
    assert not regime_allows(regime, want_short=True)


def test_downtrending_indices_give_short_bias() -> None:
    indices = [
        RegimeInputs("SPY", breakdown_series(symbol="SPY", timeframe=Timeframe.D1)),
        RegimeInputs("QQQ", breakdown_series(symbol="QQQ", timeframe=Timeframe.D1, seed=9)),
    ]
    regime = classify_regime(indices, as_of=_AS_OF)
    assert regime.regime is RegimeType.SHORT_BIAS
    assert regime_allows(regime, want_short=True)


def test_event_window_forces_no_trade() -> None:
    indices = [
        RegimeInputs("SPY", clean_uptrend_series(symbol="SPY", timeframe=Timeframe.D1)),
    ]
    regime = classify_regime(
        indices, as_of=_AS_OF, event_within_hours=2, block_if_event_within_hours=4
    )
    assert regime.regime is RegimeType.NO_TRADE
    assert not regime_allows(regime, want_short=False)
    assert not regime_allows(regime, want_short=True)
