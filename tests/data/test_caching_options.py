"""Tests for CachingOptionsDataProvider (per-tick chain dedupe)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from trading_engine.core.types import OptionChain
from trading_engine.data.caching_options import CachingOptionsDataProvider


class _CountingProvider:
    """Fake inner provider: counts calls per underlying, returns a fresh chain."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    async def get_option_chain(
        self, underlying: str, as_of: datetime | None = None
    ) -> OptionChain:
        self.calls[underlying] = self.calls.get(underlying, 0) + 1
        return OptionChain(
            underlying=underlying, snapshot_at=datetime.now(tz=UTC), contracts=[]
        )


def test_repeated_symbol_within_ttl_fetches_once() -> None:
    inner = _CountingProvider()
    cache = CachingOptionsDataProvider(inner, ttl_seconds=180.0)

    first = asyncio.run(cache.get_option_chain("SPY"))
    second = asyncio.run(cache.get_option_chain("SPY"))

    assert inner.calls["SPY"] == 1
    # Same cached object returned within ttl.
    assert first is second


def test_clear_forces_refetch() -> None:
    inner = _CountingProvider()
    cache = CachingOptionsDataProvider(inner, ttl_seconds=180.0)

    asyncio.run(cache.get_option_chain("SPY"))
    cache.clear()
    asyncio.run(cache.get_option_chain("SPY"))

    assert inner.calls["SPY"] == 2


def test_ttl_expiry_forces_refetch() -> None:
    inner = _CountingProvider()
    cache = CachingOptionsDataProvider(inner, ttl_seconds=0.0)

    asyncio.run(cache.get_option_chain("SPY"))
    asyncio.run(cache.get_option_chain("SPY"))

    # ttl=0 -> every call is stale -> always re-fetch.
    assert inner.calls["SPY"] == 2


def test_different_symbols_fetch_separately() -> None:
    inner = _CountingProvider()
    cache = CachingOptionsDataProvider(inner, ttl_seconds=180.0)

    asyncio.run(cache.get_option_chain("SPY"))
    asyncio.run(cache.get_option_chain("QQQ"))

    assert inner.calls == {"SPY": 1, "QQQ": 1}
