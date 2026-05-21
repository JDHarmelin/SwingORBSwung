"""Follow-up management for open signals."""

from __future__ import annotations

import logging

from trading_engine.alerts.formatter import format_follow_up
from trading_engine.core.interfaces import AlertSink, Repository
from trading_engine.core.types import SignalStatus
from trading_engine.risk.trade_management import evaluate_management

logger = logging.getLogger(__name__)


class FollowUpService:
    def __init__(self, repo: Repository, alerts: AlertSink) -> None:
        self._repo = repo
        self._alerts = alerts

    async def evaluate_open(self, *, option_gain_pct: float) -> list[str]:
        """Check open signals and emit follow-up events."""
        emitted: list[str] = []
        for signal in await self._repo.open_signals():
            event = evaluate_management(signal, option_gain_pct=option_gain_pct)
            if event is None:
                continue
            await self._repo.append_signal_event(event)
            if event.event_type == "triggered":
                signal.status = SignalStatus.TRIGGERED
            elif event.event_type == "trim1":
                signal.status = SignalStatus.TRIMMED
            elif event.event_type == "stop_hit":
                signal.status = SignalStatus.STOPPED
            elif event.event_type == "runner_exit":
                signal.status = SignalStatus.CLOSED
            await self._repo.save_signal(signal)
            msg = format_follow_up(event, symbol=signal.symbol)
            await self._alerts.send(msg, dedupe_key=f"{signal.signal_id}:{event.event_type}")
            emitted.append(event.event_type)
        return emitted
