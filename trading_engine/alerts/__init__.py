"""Alerting layer."""

from trading_engine.alerts.console import ConsoleAlertSink
from trading_engine.alerts.dedupe import AlertDeduper
from trading_engine.alerts.formatter import format_follow_up, format_signal

__all__ = ["AlertDeduper", "ConsoleAlertSink", "format_follow_up", "format_signal"]
