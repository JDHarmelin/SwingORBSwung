"""Reusable test fixtures.

Exposes synthetic-candle generators and a sample option chain so any wave
can build/test against realistic shapes without API keys. Importable from
both tests and runtime code (e.g. the mock data adapter).
"""

from trading_engine.testing.synthetic import (  # noqa: F401
    breakdown_series,
    choppy_series,
    clean_uptrend_series,
    compression_then_breakout_series,
    pullback_to_8ema_series,
    sample_option_chain,
    sample_sector_etf_series,
    sample_universe,
)
