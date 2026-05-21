"""Telegram alert sink — @SwingORBSwung_bot only."""

from __future__ import annotations

import asyncio
import logging

from telegram import Bot
from telegram.error import TelegramError

from trading_engine.alerts.telegram_config import (
    REQUIRED_BOT_USERNAME,
    load_telegram_credentials,
    verify_bot_username,
)

logger = logging.getLogger(__name__)


class TelegramAlertSink:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        *,
        max_retries: int = 3,
        skip_bot_verify: bool = False,
    ) -> None:
        if token is None or chat_id is None:
            file_token, file_chat = load_telegram_credentials()
            token = token or file_token
            chat_id = chat_id or file_chat
        if not token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required in .env")
        if not skip_bot_verify:
            username = verify_bot_username(token)
            logger.info("telegram bot verified: @%s", username)
        self._token = token
        self._chat_id = str(chat_id)
        self._max_retries = max_retries
        self._bot_username = REQUIRED_BOT_USERNAME

    async def send(self, message: str, *, dedupe_key: str) -> None:
        bot = Bot(token=self._token)
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                await bot.send_message(chat_id=self._chat_id, text=message)
                logger.info(
                    "telegram sent via @%s to chat %s dedupe_key=%s",
                    self._bot_username,
                    self._chat_id,
                    dedupe_key,
                )
                return
            except TelegramError as e:
                last_err = e
                await asyncio.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"Telegram send failed: {last_err}")
