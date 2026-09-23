"""One-time Telegram setup: find the chat to message, save it, send a test message.

    python scripts/telegram_setup.py

Needs TELEGRAM_BOT_TOKEN in .env and one message sent to the bot from your Telegram
account (so it is allowed to reply). Prints no secrets.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.alerts.telegram import call, find_chat, load_env, save_env_value, send  # noqa: E402


def main() -> None:
    env = load_env()
    if not env.get("TELEGRAM_BOT_TOKEN"):
        print("No TELEGRAM_BOT_TOKEN in .env - paste the @BotFather token there first.")
        raise SystemExit(1)
    me = call("getMe")
    print(f"bot: @{me.get('username')} ({me.get('first_name')})")

    chat_id = env.get("TELEGRAM_CHAT_ID")
    if chat_id:
        print(f"chat already configured: {chat_id}")
    else:
        found = find_chat()
        if not found:
            print(f"No messages yet. Open Telegram, send @{me.get('username')} any message, then run this again.")
            raise SystemExit(1)
        chat_id, name = found
        save_env_value("TELEGRAM_CHAT_ID", chat_id)
        print(f"chat found and saved: {chat_id} ({name})")

    send("Currency relations: alerts are connected. You will get a message when a "
         "relationship breaks, recovers, or the whole board turns into one trade.")
    print("test message sent - check Telegram")


if __name__ == "__main__":
    main()
