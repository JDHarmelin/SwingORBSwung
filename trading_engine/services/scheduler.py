"""Simple scheduler.

Runs the signal pipeline at premarket once, then loops the management tick
every ``interval`` seconds during the session. Production deploys can swap
this for cron / systemd timers; the lifecycle here is enough for research.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from trading_engine.services.management_service import ManagementService
from trading_engine.services.signal_service import SignalService

log = logging.getLogger(__name__)


async def run_once(
    signal_service: SignalService,
    management_service: ManagementService,
    *,
    as_of: datetime | None = None,
) -> int:
    """Run one premarket scan + one management tick. Returns signal count."""
    when = as_of or datetime.now(tz=UTC)
    result = await signal_service.run_pipeline(when)
    log.info("pipeline emitted %d signals", len(result.signals))
    events = await management_service.tick(when)
    log.info("management tick emitted %d events", len(events))
    return len(result.signals)


async def run_loop(
    signal_service: SignalService,
    management_service: ManagementService,
    *,
    interval_seconds: int = 300,
    iterations: int | None = None,
) -> None:
    """Loop the management tick. ``iterations`` is for tests; None = forever."""
    await signal_service.run_pipeline(datetime.now(tz=UTC))
    i = 0
    while iterations is None or i < iterations:
        await management_service.tick(datetime.now(tz=UTC))
        i += 1
        if iterations is not None and i >= iterations:
            break
        await asyncio.sleep(interval_seconds)


__all__ = ["run_loop", "run_once"]
