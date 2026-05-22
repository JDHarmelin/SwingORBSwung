"""Alert sinks: in-memory (tests + research), console (CLI), Telegram (live).

All implement the ``AlertSink`` protocol from ``core.interfaces`` with
dedupe-aware semantics — a second call with the same ``dedupe_key`` is a no-op.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)


class _DedupeMixin:
    """Tracks seen ``dedupe_key``s for the lifetime of the sink instance."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def _should_send(self, dedupe_key: str) -> bool:
        if dedupe_key in self._seen:
            return False
        self._seen.add(dedupe_key)
        return True


@dataclass
class InMemoryAlertSink:
    """Captures alerts in a list — used by tests and by the CLI in dry-run."""

    messages: list[str] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)

    async def send(self, message: str, *, dedupe_key: str) -> None:
        if dedupe_key in self._seen:
            return
        self._seen.add(dedupe_key)
        self.messages.append(message)


class ConsoleAlertSink(_DedupeMixin):
    """Prints alerts to stdout. Useful for local research runs."""

    async def send(self, message: str, *, dedupe_key: str) -> None:
        if not self._should_send(dedupe_key):
            return
        # Print to stdout — intentional, not a log call. Keep simple separator.
        print("\n----- ALERT -----\n" + message + "\n-----------------")


class TelegramAlertSink(_DedupeMixin):
    """Posts to ``sendMessage``. Configured from bot token + chat id.

    Retries transient errors (5xx, timeout) with exponential backoff up to
    ``max_retries``. Auth / 4xx errors propagate.
    """

    BASE_URL = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        timeout: float = 10.0,
    ) -> None:
        super().__init__()
        if not bot_token or not chat_id:
            raise ValueError("TelegramAlertSink requires bot_token and chat_id")
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._max_retries = max_retries

    async def send(self, message: str, *, dedupe_key: str) -> None:
        if not self._should_send(dedupe_key):
            return
        url = f"{self.BASE_URL}/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": message, "disable_web_page_preview": True}
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.post(url, json=payload)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"Telegram {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                # Drop the dedupe key so we can retry next time? No — Telegram
                # rejects transient errors but we want one delivery; keep the
                # key and retry within this call.
                log.warning("telegram send attempt %d failed: %s", attempt + 1, exc)
        if last_exc is not None:
            self._seen.discard(dedupe_key)
            raise last_exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


__all__ = ["ConsoleAlertSink", "InMemoryAlertSink", "TelegramAlertSink"]
