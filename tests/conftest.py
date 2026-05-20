"""Shared pytest fixtures.

Exposes synthetic OHLCV shapes + a sample option chain so any wave can write
tests against the same realistic inputs.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from trading_engine.core.types import OHLCVSeries, OptionChain, Timeframe
from trading_engine.testing.synthetic import (
    breakdown_series,
    choppy_series,
    clean_uptrend_series,
    compression_then_breakout_series,
    pullback_to_8ema_series,
    sample_option_chain,
    sample_sector_etf_series,
    sample_universe,
)

# ---- Daily series ---------------------------------------------------------


@pytest.fixture
def uptrend_daily() -> OHLCVSeries:
    return clean_uptrend_series(timeframe=Timeframe.D1)


@pytest.fixture
def pullback_daily() -> OHLCVSeries:
    return pullback_to_8ema_series(timeframe=Timeframe.D1)


@pytest.fixture
def compression_daily() -> OHLCVSeries:
    return compression_then_breakout_series(timeframe=Timeframe.D1)


@pytest.fixture
def breakdown_daily() -> OHLCVSeries:
    return breakdown_series(timeframe=Timeframe.D1)


@pytest.fixture
def chop_daily() -> OHLCVSeries:
    return choppy_series(timeframe=Timeframe.D1)


# ---- Intraday (5m) series -------------------------------------------------


@pytest.fixture
def uptrend_5m() -> OHLCVSeries:
    return clean_uptrend_series(timeframe=Timeframe.M5, n=120)


@pytest.fixture
def pullback_5m() -> OHLCVSeries:
    return pullback_to_8ema_series(timeframe=Timeframe.M5, n=120)


@pytest.fixture
def compression_5m() -> OHLCVSeries:
    return compression_then_breakout_series(timeframe=Timeframe.M5, n=120)


@pytest.fixture
def breakdown_5m() -> OHLCVSeries:
    return breakdown_series(timeframe=Timeframe.M5, n=120)


@pytest.fixture
def chop_5m() -> OHLCVSeries:
    return choppy_series(timeframe=Timeframe.M5, n=120)


# ---- Options chain --------------------------------------------------------


@pytest.fixture
def option_chain() -> OptionChain:
    return sample_option_chain()


# ---- Universe + sector ETF ------------------------------------------------


@pytest.fixture
def universe() -> dict:
    return sample_universe()


@pytest.fixture
def sector_etf_series_factory() -> Callable[[str], OHLCVSeries]:
    return lambda etf: sample_sector_etf_series(etf=etf)
