"""Position follow-up service (spec §10).

Iterates open signals, prices the suggested option from the chain, and fires
the next batch of management events (trim, BE move, stop, expiry risk).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from trading_engine.alerts.formatter import event_dedupe_key, format_event
from trading_engine.core.interfaces import (
    AlertSink,
    OptionsDataProvider,
    Repository,
)
from trading_engine.core.types import (
    ContractSuggestion,
    OptionChain,
    OptionContract,
    OptionType,
    SignalEvent,
)
from trading_engine.risk.trade_management import (
    ManagementUpdate,
    apply_event,
    follow_up_events,
)

log = logging.getLogger(__name__)

_EXPIRY_WARN_DAYS = 7


def _match_contract(chain: OptionChain, c: ContractSuggestion) -> OptionContract | None:
    want_type = OptionType.CALL if c.direction == "long_call" else OptionType.PUT
    for x in chain.contracts:
        if x.type is want_type and x.expiry == c.expiry and abs(x.strike - c.strike) < 1e-6:
            return x
    return None


class ManagementService:
    def __init__(
        self,
        *,
        options_data: OptionsDataProvider,
        repo: Repository,
        alerts: AlertSink,
        entry_price_lookup: dict[str, float] | None = None,
    ) -> None:
        self.options_data = options_data
        self.repo = repo
        self.alerts = alerts
        # entry prices are not modelled by mock chains; alert engine is paper.
        # caller may seed an entry_price_lookup keyed by signal_id.
        self.entry_price_lookup = entry_price_lookup or {}

    async def tick(self, now: datetime) -> list[SignalEvent]:
        emitted: list[SignalEvent] = []
        open_signals = await self.repo.open_signals()
        for signal in open_signals:
            if signal.contract is None:
                continue
            chain = await self.options_data.get_option_chain(signal.symbol, as_of=now)
            matched = _match_contract(chain, signal.contract)
            if matched is None:
                continue
            entry = self.entry_price_lookup.get(signal.signal_id, matched.mid)
            update = ManagementUpdate(
                signal=signal,
                timestamp=now,
                option_entry_price=entry,
                option_current_price=matched.mid,
            )
            seen = {e.event_type for e in await self.repo.list_signal_events(signal.signal_id)}
            new_events = follow_up_events(update, seen)
            if (
                signal.contract is not None
                and (signal.contract.expiry - now.date()) <= timedelta(days=_EXPIRY_WARN_DAYS)
                and "expiry_risk" not in seen
            ):
                new_events.append(
                    SignalEvent(
                        signal_id=signal.signal_id,
                        event_timestamp=now,
                        event_type="expiry_risk",
                        event_payload={
                            "days_to_expiry": (signal.contract.expiry - now.date()).days
                        },
                    )
                )
            for event in new_events:
                await self.repo.append_signal_event(event)
                await self.repo.save_signal(apply_event(signal, event))
                await self.alerts.send(
                    format_event(event, signal), dedupe_key=event_dedupe_key(event)
                )
                emitted.append(event)
        return emitted


__all__ = ["ManagementService"]
