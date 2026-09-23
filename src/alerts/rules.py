"""What is worth a message, and how it reads.

Alerts fire on *changes* between cycles, never on a standing condition, so a quiet market
is a quiet phone. The first run only seeds the state (otherwise every existing breakdown
would arrive at once). Everything found in one cycle goes out as a single message.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import ALERT_STATE_FILE, ONE_TRADE_OFF, ONE_TRADE_ON
from src.engine.store import USD_MAJORS

WARNINGS = ("WARNING_TIGHT", "WARNING_LOOSE")


def key(pair: str, index: str) -> str:
    return f"{pair}|{index}"


def index_label(index: str) -> str:
    return "DXY" if index == "DXY" else index.replace("-EW", " index")


def pair_label(pair: str) -> str:
    return f"{pair[:3]}/{pair[3:]}"


def watched(matrix: pd.DataFrame, tf: str, window: int) -> dict[str, dict]:
    """Cells worth watching: every pair against DXY and against its own two currencies."""
    m = matrix[(matrix["tf"] == tf) & (matrix["window"] == window)]
    out = {}
    for r in m.to_dict("records"):
        base, quote = r["pair"][:3], r["pair"][3:]
        if r["index"] in ("DXY", f"{base}-EW", f"{quote}-EW"):
            out[key(r["pair"], r["index"])] = r
    return out


def one_trade_count(matrix: pd.DataFrame, tf: str, window: int) -> int:
    """How many USD majors are tighter than normal against DXY — i.e. one dollar trade."""
    m = matrix[(matrix["tf"] == tf) & (matrix["window"] == window) & (matrix["index"] == "DXY")
               & matrix["pair"].isin(USD_MAJORS)]
    return int((m["health"] == "WARNING_TIGHT").sum())


def load_state(path: Path = ALERT_STATE_FILE) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict, path: Path = ALERT_STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


def evaluate(matrix: pd.DataFrame, tf: str, window: int, state: dict) -> tuple[list[dict], dict]:
    """Events since the last cycle, plus the state to carry forward."""
    rows = watched(matrix, tf, window)
    prev_health = (state.get("states") or {})
    events: list[dict] = []
    first_run = not prev_health

    for k, r in rows.items():
        was, now = prev_health.get(k), r["health"]
        if first_run or was is None or was == now:
            continue
        if now == "BREAKDOWN" and was in ("HEALTHY",) + WARNINGS:
            events.append({"kind": "broken", **r})
        elif was == "BREAKDOWN" and now == "HEALTHY":
            events.append({"kind": "recovered", **r})

    count = one_trade_count(matrix, tf, window)
    was_one_trade = bool(state.get("one_trade"))
    one_trade = was_one_trade
    if not was_one_trade and count >= ONE_TRADE_ON:
        one_trade = True
        if not first_run:
            events.append({"kind": "one_trade_on", "count": count})
    elif was_one_trade and count <= ONE_TRADE_OFF:
        one_trade = False
        if not first_run:
            events.append({"kind": "one_trade_off", "count": count})

    new_state = {
        "states": {k: r["health"] for k, r in rows.items()},
        "one_trade": one_trade,
        "one_trade_count": count,
        "updated": datetime.now(timezone.utc).isoformat(),
        "error_sent": state.get("error_sent"),
    }
    return events, new_state


def _line(e: dict) -> str:
    who = f"{pair_label(e['pair'])} vs {index_label(e['index'])}"
    if e["kind"] == "broken":
        return (f"{who} — correlation {e['rho']:+.2f}, normally {e['rho_lo']:+.2f} to {e['rho_hi']:+.2f} "
                f"(typical strength {e['typical_abs_rho']:.2f}). It is trading on its other leg.")
    return (f"{who} — correlation {e['rho']:+.2f}, back inside its normal "
            f"{e['rho_lo']:+.2f} to {e['rho_hi']:+.2f}.")


def format_message(events: list[dict], tf: str, window: int, asof: str) -> str:
    broken = [e for e in events if e["kind"] == "broken"]
    recovered = [e for e in events if e["kind"] == "recovered"]
    parts: list[str] = []
    if broken:
        parts.append(f"[broken] Seesaw broken ({len(broken)})\n" + "\n".join(_line(e) for e in broken))
    if recovered:
        parts.append(f"[recovered] Back to normal ({len(recovered)})\n" + "\n".join(_line(e) for e in recovered))
    for e in events:
        if e["kind"] == "one_trade_on":
            parts.append(f"[one trade] {e['count']} of the USD majors are tighter than normal against DXY — "
                         "the board is one dollar trade right now, so these pairs are not separate bets.")
        elif e["kind"] == "one_trade_off":
            parts.append(f"[spread out] Only {e['count']} USD majors still tighter than normal — "
                         "pairs are moving on their own drivers again.")
    when = asof.replace("T", " ")[:16] if asof else "?"
    parts.append(f"{tf} · {window}-bar window · latest bar {when} UTC")
    return "\n\n".join(parts)
