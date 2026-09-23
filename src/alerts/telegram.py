"""Telegram delivery.

The bot token lives in .env (gitignored) or the environment and is never logged: every
error message is scrubbed before it leaves this module, because Telegram's API puts the
token in the URL and urllib repeats the URL in exceptions.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from config import ROOT

ENV_FILE = ROOT / ".env"
API = "https://api.telegram.org/bot{token}/{method}"
KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Values from .env, with real environment variables taking precedence."""
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if v.strip():
                out[k.strip()] = v.strip()
    for k in KEYS:
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


def save_env_value(key: str, value: str, path: Path = ENV_FILE) -> None:
    """Set or replace one key in .env, leaving the rest of the file alone."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for idx, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[idx] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scrub(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


def call(method: str, params: dict | None = None, token: str | None = None, timeout: int = 20) -> dict:
    """One Telegram API call. Raises RuntimeError with the token scrubbed out."""
    token = token or load_env().get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("no TELEGRAM_BOT_TOKEN in .env or the environment")
    url = API.format(token=token, method=method)
    data = urllib.parse.urlencode(params or {}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:                      # 401/403/429 etc.
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(_scrub(f"telegram {method} failed: HTTP {exc.code} {detail}", token)) from None
    except Exception as exc:                                    # noqa: BLE001 - network, DNS, timeout
        raise RuntimeError(_scrub(f"telegram {method} failed: {type(exc).__name__}: {exc}", token)) from None
    if not body.get("ok"):
        raise RuntimeError(_scrub(f"telegram {method} refused: {body.get('description')}", token))
    return body["result"]


def send(text: str, token: str | None = None, chat_id: str | None = None) -> None:
    env = load_env()
    chat_id = chat_id or env.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise RuntimeError("no TELEGRAM_CHAT_ID yet - run scripts/telegram_setup.py")
    call("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"},
         token=token or env.get("TELEGRAM_BOT_TOKEN"))


def find_chat(token: str | None = None) -> tuple[str, str] | None:
    """The chat of whoever last messaged the bot: (chat_id, display name)."""
    for update in reversed(call("getUpdates", {"limit": 20}, token=token)):
        msg = update.get("message") or update.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            name = " ".join(p for p in (chat.get("first_name"), chat.get("last_name")) if p) or chat.get("title", "")
            return str(chat["id"]), name or chat.get("username", "")
    return None
