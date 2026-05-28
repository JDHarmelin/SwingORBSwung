"""CachingOptionsDataProvider — per-tick TTL cache around an inner provider.

Wraps any OptionsDataProvider. Within a single tick the same underlying's
chain is fetched multiple times (the scan fetches it, then ManagementService
fetches it again per open signal). yfinance calls are ~0.7s each, so this
caching wrapper dedupes both scan and management fetches within a tick.

The provider instance is shared between SignalService and ManagementService,
so one wrapper dedupes both. The cache key is the ``underlying`` only —
``as_of`` is ignored because the chain is always "current". Default ttl
(180s) is comfortably longer than a tick (~70s) but shorter than the scan
interval (300s), so each new tick refreshes naturally.

Single asyncio loop usage → no locks needed.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from trading_engine.core.interfaces import OptionsDataProvider
from trading_engine.core.types import OptionChain

log = logging.getLogger(__name__)


class CachingOptionsDataProvider:
    """TTL cache (keyed by underlying) around an inner OptionsDataProvider."""

    def __init__(self, inner: OptionsDataProvider, *, ttl_seconds: float = 180.0):
        self._inner = inner
        self._ttl = ttl_seconds
        # underlying -> (chain, monotonic timestamp)
        self._cache: dict[str, tuple[OptionChain, float]] = {}

    async def get_option_chain(
        self, underlying: str, as_of: datetime | None = None
    ) -> OptionChain:
        now = time.monotonic()
        cached = self._cache.get(underlying)
        if cached is not None and (now - cached[1]) < self._ttl:
            log.debug("caching_options: cache hit for %s", underlying)
            return cached[0]
        chain = await self._inner.get_option_chain(underlying, as_of)
        self._cache[underlying] = (chain, now)
        return chain

    def clear(self) -> None:
        """Drop all cached chains (e.g. between ticks if forced)."""
        self._cache.clear()


__all__ = ["CachingOptionsDataProvider"]
