"""Scheduler — the execution-only tick.

A tick is: ``expire stale → generate candidates → confirm + alert → track
outcomes``. Production deploys can swap this for cron / systemd timers; this
lifecycle is enough for research and for the management follow-up loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from trading_engine.services.confirmation import ConfirmationGate
from trading_engine.services.management_service import ManagementService
from trading_engine.services.signal_service import SignalService

log = logging.getLogger(__name__)


@dataclass
class TickResult:
    expired: list[str] = field(default_factory=list)
    candidates_generated: int = 0
    alerted: int = 0
    outcomes_recorded: list[str] = field(default_factory=list)
    mgmt_events: int = 0


async def run_tick(
    signal_service: SignalService,
    management_service: ManagementService,
    gate: ConfirmationGate,
    *,
    as_of: datetime | None = None,
) -> TickResult:
    """One iteration of the execution-only flow."""
    when = as_of or datetime.now(tz=UTC)
    result = TickResult()
    result.expired = await signal_service.expire_stale_candidates()
    pipeline = await signal_service.run_pipeline(when)
    result.candidates_generated = len(pipeline.candidates)
    alerted = await signal_service.confirm_and_alert(gate)
    result.alerted = len(alerted)
    result.outcomes_recorded = await signal_service.track_outcomes(when)
    mgmt_events = await management_service.tick(when)
    result.mgmt_events = len(mgmt_events)
    log.info(
        "tick: expired=%d candidates=%d alerted=%d outcomes=%d mgmt=%d",
        len(result.expired),
        result.candidates_generated,
        result.alerted,
        len(result.outcomes_recorded),
        result.mgmt_events,
    )
    return result


async def run_loop(
    signal_service: SignalService,
    management_service: ManagementService,
    gate: ConfirmationGate,
    *,
    interval_seconds: int = 300,
    iterations: int | None = None,
) -> None:
    """Loop ``run_tick`` indefinitely (or for ``iterations`` for tests)."""
    i = 0
    while iterations is None or i < iterations:
        await run_tick(signal_service, management_service, gate)
        i += 1
        if iterations is not None and i >= iterations:
            break
        await asyncio.sleep(interval_seconds)


__all__ = ["TickResult", "run_loop", "run_tick"]
