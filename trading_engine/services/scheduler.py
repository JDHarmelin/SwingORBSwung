"""Scan scheduler — premarket + intraday loops."""

from __future__ import annotations

import asyncio
import logging

from trading_engine.services.signal_service import SignalService

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        signal_service: SignalService,
        *,
        intraday_interval_sec: int = 300,
    ) -> None:
        self._svc = signal_service
        self._interval = intraday_interval_sec
        self._running = False

    async def run(self, symbols: list[str] | None = None) -> None:
        self._running = True
        logger.info("scheduler started interval=%ss", self._interval)
        while self._running:
            candidates = await self._svc.scan_once(symbols, alert_candidates=False)
            confirmed = await self._svc.confirm_and_alert()
            tracked = await self._svc.track_outcomes()
            logger.info(
                "tick candidates=%s confirmed=%s outcomes_logged=%s",
                len(candidates),
                len(confirmed),
                len(tracked),
            )
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        self._running = False

    async def scan_once(self, symbols: list[str] | None = None) -> list[str]:
        return await self._svc.scan_once(symbols)
