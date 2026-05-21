#!/usr/bin/env python3
"""Send one test alert via @SwingORBSwung_bot to the chat in .env only."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_engine.alerts.telegram import TelegramAlertSink  # noqa: E402
from trading_engine.alerts.telegram_config import (  # noqa: E402
    load_telegram_credentials,
    verify_bot_username,
)


async def main() -> None:
    token, chat_id = load_telegram_credentials()
    username = verify_bot_username(token)
    print(f"Using bot: @{username}")
    print(f"Sending to chat id: {chat_id}")
    sink = TelegramAlertSink(token=token, chat_id=chat_id, skip_bot_verify=True)
    await sink.send(
        f"Test from @{username} — if you see this in the wrong bot, check .env.",
        dedupe_key="setup-test",
    )
    print("Sent.")


if __name__ == "__main__":
    asyncio.run(main())
