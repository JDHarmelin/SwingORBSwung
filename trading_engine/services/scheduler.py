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
from trading_engine.services.market_hours import is_us_market_open
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
    market_hours_only: bool = False,
) -> TickResult:
    """One iteration of the execution-only flow.

    When ``market_hours_only`` is set and the US market is closed at ``when``,
    the scan + alert steps are skipped (no firing on stale prices) but expiry,
    outcome tracking, and management still run so the learning log and open
    positions stay current after hours.
    """
    when = as_of or datetime.now(tz=UTC)
    result = TickResult()
    result.expired = await signal_service.expire_stale_candidates()
    market_closed = market_hours_only and not is_us_market_open(when)
    if market_closed:
        log.info("tick: market closed — skipping scan/alert")
        result.candidates_generated = 0
        result.alerted = 0
    else:
        pipeline = await signal_service.run_pipeline(when)
        result.candidates_generated = len(pipeline.candidates)
        alerted = await signal_service.confirm_and_alert(gate)
        result.alerted = len(alerted)
    # When the market is closed AND no signal needs advancing, skip the
    # outcome/management leg — they would otherwise fan out OHLCV + chain
    # fetches per symbol for zero output.
    if market_closed and not await signal_service.has_open_work():
        log.info("tick: market closed + no open work — skipping outcomes/mgmt")
        result.outcomes_recorded = []
        result.mgmt_events = 0
    else:
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
    market_hours_only: bool = False,
) -> None:
    """Loop ``run_tick`` indefinitely (or for ``iterations`` for tests)."""
    i = 0
    while iterations is None or i < iterations:
        await run_tick(
            signal_service,
            management_service,
            gate,
            market_hours_only=market_hours_only,
        )
        i += 1
        if iterations is not None and i >= iterations:
            break
        await asyncio.sleep(interval_seconds)


__all__ = ["TickResult", "run_loop", "run_tick"]
