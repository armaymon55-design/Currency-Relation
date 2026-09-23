"""Live updater: re-measure every REFRESH_MINUTES, forever. Read-only against MT5.

    python scripts/live.py            # loop
    python scripts/live.py --once     # a single cycle (same as run_matrix.py without the report)

One failed cycle is logged and retried next round; the loop never exits on its own.
Progress goes to the console and to output/live.log (rotating), and every cycle writes
output/heartbeat.json, which the dashboard's live indicator reads.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    ALERT_ERROR_COOLDOWN_MINUTES, ALERT_TF, ALERT_WINDOW, ALERTS_ENABLED, LIVE_LOG_FILE,
    OUTPUT_DIR, REFRESH_MINUTES,
)
from src.alerts import rules  # noqa: E402
from src.alerts.telegram import find_chat, load_env, save_env_value, send  # noqa: E402
from src.pipeline import merge_heartbeat, read_heartbeat, run_once, write_heartbeat  # noqa: E402


def make_logger() -> logging.Logger:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("live")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S")
        fh = RotatingFileHandler(LIVE_LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


def claim_chat(log) -> None:
    """Telegram forbids a bot from opening a conversation, so we wait for the first message
    and adopt that chat automatically — no setup command needed once the user says hello."""
    try:
        found = find_chat()
    except Exception as exc:  # noqa: BLE001 - offline or rate-limited: try again next cycle
        log.info(f"waiting for a first Telegram message ({exc})")
        return
    if not found:
        return
    chat_id, name = found
    save_env_value("TELEGRAM_CHAT_ID", chat_id)
    send("Currency relations: alerts are connected. You will hear from me when a relationship "
         "breaks, when it recovers, and when the whole board turns into one dollar trade. "
         "Silence means everything is behaving normally.")
    log.info(f"telegram chat adopted and saved ({name})")


def alerts_ready(log=None) -> bool:
    env = load_env()
    if not (ALERTS_ENABLED and env.get("TELEGRAM_BOT_TOKEN")):
        return False
    if not env.get("TELEGRAM_CHAT_ID") and log is not None:
        claim_chat(log)
        env = load_env()
    return bool(env.get("TELEGRAM_CHAT_ID"))


def run_alerts(log, matrix) -> None:
    """Compare this snapshot with the last one and message anything that changed."""
    state = rules.load_state()
    events, new_state = rules.evaluate(matrix, ALERT_TF, ALERT_WINDOW, state)
    if events:
        asof = matrix[(matrix["tf"] == ALERT_TF) & (matrix["window"] == ALERT_WINDOW)]["asof"].max()
        text = rules.format_message(events, ALERT_TF, ALERT_WINDOW, asof)
        send(text)
        log.info(f"alert sent: {', '.join(e['kind'] for e in events)}")
    elif not state:
        log.info("alert state seeded (first run stays quiet)")
    rules.save_state(new_state)


def alert_error_once(log, message: str) -> None:
    """Report a failing updater, at most once an hour, so a persistent fault is not spam."""
    state = rules.load_state()
    last = state.get("error_sent")
    if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < ALERT_ERROR_COOLDOWN_MINUTES * 60:
        return
    try:
        send(f"[updater problem] The currency relations updater hit an error and is retrying:\n{message}")
        state["error_sent"] = datetime.now(timezone.utc).isoformat()
        rules.save_state(state)
    except Exception as exc:  # noqa: BLE001 - never let alerting break the loop
        log.error(f"could not send the error alert: {exc}")


def cycle(log, prev_tick: str | None, runs: int) -> str | None:
    """One cycle with the heartbeat written either way. Returns the last tick seen."""
    try:
        info = run_once(log=log.info, prev_tick=prev_tick)
        matrix = info.pop("matrix", None)
        info.pop("attribution", None)
        if matrix is not None and alerts_ready(log):
            try:
                run_alerts(log, matrix)
            except Exception as exc:  # noqa: BLE001 - a delivery failure must not lose the cycle
                log.error(f"alerting failed: {exc}")
        hb = read_heartbeat() or {}
        info.update({"status": "ok", "error": None, "runs": runs})
        write_heartbeat(merge_heartbeat(hb, info))
        return info["last_tick_utc"]
    except Exception as exc:  # noqa: BLE001 - the loop must survive anything
        log.error(f"cycle failed: {exc}")
        log.error(traceback.format_exc())
        hb = read_heartbeat() or {}
        hb.update({"last_run_utc": datetime.now(timezone.utc).isoformat(), "status": "error",
                   "error": f"{type(exc).__name__}: {exc}", "runs": runs})
        write_heartbeat(hb)
        if alerts_ready(log):
            alert_error_once(log, f"{type(exc).__name__}: {exc}")
        return prev_tick


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="run one cycle and exit")
    ap.add_argument("--minutes", type=float, default=REFRESH_MINUTES, help="minutes between cycles")
    args = ap.parse_args()
    log = make_logger()
    log.info(f"live updater starting (every {args.minutes:g} min, read-only)")
    prev_tick, runs = None, 0
    while True:
        runs += 1
        t0 = time.time()
        prev_tick = cycle(log, prev_tick, runs)
        if args.once:
            break
        wait = max(30.0, args.minutes * 60 - (time.time() - t0))
        log.info(f"next cycle in {wait / 60:.1f} min")
        time.sleep(wait)


if __name__ == "__main__":
    main()
