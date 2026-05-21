"""Console alert sink for local dev."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ConsoleAlertSink:
    async def send(self, message: str, *, dedupe_key: str) -> None:
        print(f"[ALERT {dedupe_key}]\n{message}\n")
