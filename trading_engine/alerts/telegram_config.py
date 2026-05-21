"""Telegram credentials — loaded only from the project ``.env`` file.

Ignores stray ``TELEGRAM_*`` variables in the shell so alerts always use the
bot and chat configured in this repo.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

REQUIRED_BOT_USERNAME = "SwingORBSwung_bot"


def _project_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip("'").strip('"')
    return out


def load_telegram_credentials() -> tuple[str, str]:
    """Return (bot_token, chat_id) from ``.env`` only."""
    env = _read_env_file(_project_env_path())
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise ValueError(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env at the repo root."
        )
    return token, chat_id


def verify_bot_username(token: str, *, expected: str = REQUIRED_BOT_USERNAME) -> str:
    """Confirm token belongs to ``@expected``; return username."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read())
    if not data.get("ok"):
        raise ValueError(f"Telegram getMe failed: {data}")
    username = (data.get("result") or {}).get("username", "")
    if username.lower() != expected.lower():
        raise ValueError(
            f"TELEGRAM_BOT_TOKEN is for @{username}, not @{expected}. "
            "Update .env with the correct bot token."
        )
    return username
