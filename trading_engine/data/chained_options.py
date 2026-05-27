"""ChainedOptionsDataProvider — try multiple chain sources in order.

Returns the first non-empty OptionChain. Logs which source served so the
contract diagnostics can attribute failures correctly. Designed so a
primary (entitled) provider can be backed by a delayed/secondary source.
"""

from __future__ import annotations

import logging
from datetime import datetime

from trading_engine.core.interfaces import OptionsDataProvider
from trading_engine.core.types import OptionChain

log = logging.getLogger(__name__)


class ChainedOptionsDataProvider:
    """Try providers in order; return the first chain that has contracts."""

    def __init__(self, providers: list[OptionsDataProvider], *, names: list[str] | None = None):
        if not providers:
            raise ValueError("ChainedOptionsDataProvider requires at least one provider")
        self._providers = providers
        self._names = names or [type(p).__name__ for p in providers]
        if len(self._names) != len(self._providers):
            raise ValueError("names length must match providers length")

    async def get_option_chain(
        self, underlying: str, as_of: datetime | None = None
    ) -> OptionChain:
        last_chain: OptionChain | None = None
        for name, provider in zip(self._names, self._providers, strict=True):
            try:
                chain = await provider.get_option_chain(underlying, as_of)
            except Exception as exc:  # noqa: BLE001 — fall through to next source
                log.warning("chained_options: %s raised for %s: %s", name, underlying, exc)
                continue
            last_chain = chain
            if chain.contracts:
                log.info(
                    "chained_options: %s served %s (%d contracts)",
                    name,
                    underlying,
                    len(chain.contracts),
                )
                return chain
            log.info("chained_options: %s returned empty chain for %s", name, underlying)
        # All providers exhausted — return the last empty chain (or build one).
        if last_chain is not None:
            return last_chain
        return OptionChain(underlying=underlying, as_of=as_of or datetime.utcnow(), contracts=[])


__all__ = ["ChainedOptionsDataProvider"]
