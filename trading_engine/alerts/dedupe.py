"""Alert deduplication — injectable clock."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class AlertDeduper:
    window: timedelta
    _seen: dict[str, datetime] = field(default_factory=dict)
    _now: Callable[[], datetime] = field(default_factory=lambda: datetime.now)

    def should_send(self, dedupe_key: str) -> bool:
        now = self._now()
        last = self._seen.get(dedupe_key)
        if last is not None and now - last < self.window:
            return False
        self._seen[dedupe_key] = now
        return True

    def reset(self) -> None:
        self._seen.clear()
