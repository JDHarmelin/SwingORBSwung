"""Alerts: formatter + sinks (spec §9, §10)."""

from trading_engine.alerts.formatter import (
    dedupe_key,
    event_dedupe_key,
    format_event,
    format_signal,
)
from trading_engine.alerts.sinks import (
    ConsoleAlertSink,
    InMemoryAlertSink,
    TelegramAlertSink,
)

__all__ = [
    "ConsoleAlertSink",
    "InMemoryAlertSink",
    "TelegramAlertSink",
    "dedupe_key",
    "event_dedupe_key",
    "format_event",
    "format_signal",
]
