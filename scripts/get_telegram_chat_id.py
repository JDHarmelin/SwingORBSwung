#!/usr/bin/env python3
"""Discover TELEGRAM_CHAT_ID for .env.

You need a numeric chat id (not your @username). Easiest options:

1. Message @userinfobot on Telegram — it replies with your user id.
   For a private chat with your bot, that number IS your TELEGRAM_CHAT_ID.

2. Open YOUR bot in Telegram (see bot username printed below), tap Start,
   send any text (e.g. hi), then run this script again.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_env() -> None:
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _api(token: str, method: str, *, params: str = "") -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += f"?{params}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read())


def main() -> None:
    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN in .env first.", file=sys.stderr)
        sys.exit(1)

    try:
        me = _api(token, "getMe")
    except urllib.error.HTTPError as e:
        print(f"Invalid bot token (HTTP {e.code}). Regenerate via @BotFather.", file=sys.stderr)
        sys.exit(1)

    bot = me.get("result") or {}
    username = bot.get("username", "?")
    print(f"Bot OK: @{username}")
    print(f"Open in Telegram: https://t.me/{username}")
    print("Then tap Start and send any message.\n")

    # Clear webhook so getUpdates works (common misconfiguration)
    _api(token, "deleteWebhook")

    data = _api(token, "getUpdates", params="limit=20&timeout=0")
    if not data.get("ok"):
        print("Telegram API error:", data, file=sys.stderr)
        sys.exit(1)

    updates = data.get("result") or []
    if not updates:
        print("No messages received by this bot yet.\n")
        print("Try one of these:")
        print(f"  A) https://t.me/{username} → Start → send hi → run this script again")
        print("  B) Message @userinfobot → copy your numeric id into .env:")
        print("     TELEGRAM_CHAT_ID=<that number>")
        print("\nYour @username is NOT used — only the numeric chat id.")
        sys.exit(0)

    seen: set[int] = set()
    for upd in reversed(updates):
        msg = (
            upd.get("message")
            or upd.get("edited_message")
            or upd.get("channel_post")
            or upd.get("my_chat_member", {}).get("chat")
        )
        if not msg or "chat" not in msg:
            continue
        chat = msg["chat"]
        cid = int(chat["id"])
        if cid in seen:
            continue
        seen.add(cid)
        label = chat.get("title") or chat.get("username") or chat.get("first_name", "?")
        ctype = chat.get("type", "?")
        print(f"TELEGRAM_CHAT_ID={cid}  # {ctype}: {label}")

    if seen:
        print("\nPaste one line into .env, then test:")
        print("  python scripts/send_telegram_test.py")


if __name__ == "__main__":
    main()
