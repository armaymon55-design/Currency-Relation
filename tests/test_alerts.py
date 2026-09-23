"""Alert rules and .env handling — no network, no terminal."""
import pandas as pd

from src.alerts.rules import evaluate, format_message, one_trade_count, watched
from src.alerts.telegram import _scrub, load_env, save_env_value

TF, WINDOW = "H1", 50


def _row(pair, index, health, rho=-0.9, lo=-0.95, hi=-0.7, typical=0.85):
    return {"pair": pair, "index": index, "tf": TF, "window": WINDOW, "health": health,
            "rho": rho, "rho_lo": lo, "rho_hi": hi, "typical_abs_rho": typical, "beta": -1.0,
            "asof": "2026-09-19T00:00:00+00:00"}


def _matrix(**health):
    rows = [
        _row("EURUSD", "DXY", health.get("eurusd_dxy", "HEALTHY")),
        _row("AUDUSD", "AUD-EW", health.get("audusd_aud", "HEALTHY"), rho=0.7, lo=0.48, hi=0.85, typical=0.70),
        _row("EURUSD", "JPY-EW", health.get("eurusd_jpy", "HEALTHY")),   # not a watched cell
    ]
    for p in ["GBPUSD", "USDJPY", "USDCHF", "USDCAD", "NZDUSD", "USDSEK", "USDNOK"]:
        rows.append(_row(p, "DXY", health.get("majors", "HEALTHY")))
    return pd.DataFrame(rows)


def test_watched_cells_are_dxy_and_the_pairs_own_currencies():
    w = watched(_matrix(), TF, WINDOW)
    assert "EURUSD|DXY" in w and "AUDUSD|AUD-EW" in w
    assert "EURUSD|JPY-EW" not in w          # a third currency's index is not watched


def test_first_run_seeds_quietly_then_reports_changes():
    events, state = evaluate(_matrix(), TF, WINDOW, {})
    assert events == [] and state["states"]["EURUSD|DXY"] == "HEALTHY"

    events, state = evaluate(_matrix(audusd_aud="BREAKDOWN"), TF, WINDOW, state)
    assert [e["kind"] for e in events] == ["broken"] and events[0]["pair"] == "AUDUSD"

    events, state = evaluate(_matrix(audusd_aud="BREAKDOWN"), TF, WINDOW, state)
    assert events == []                      # unchanged: no repeat message

    events, state = evaluate(_matrix(), TF, WINDOW, state)
    assert [e["kind"] for e in events] == ["recovered"]


def test_one_trade_board_has_hysteresis():
    _, state = evaluate(_matrix(), TF, WINDOW, {})
    events, state = evaluate(_matrix(majors="WARNING_TIGHT", eurusd_dxy="WARNING_TIGHT"), TF, WINDOW, state)
    assert any(e["kind"] == "one_trade_on" for e in events) and state["one_trade"]
    # still elevated but below the "on" line: no second message, and it stays on
    events, state = evaluate(_matrix(majors="WARNING_TIGHT"), TF, WINDOW, state)
    assert events == [] and state["one_trade"]
    events, state = evaluate(_matrix(), TF, WINDOW, state)
    assert any(e["kind"] == "one_trade_off" for e in events) and not state["one_trade"]


def test_one_trade_count():
    assert one_trade_count(_matrix(majors="WARNING_TIGHT"), TF, WINDOW) == 7


def test_message_reads_in_plain_english():
    _, state = evaluate(_matrix(), TF, WINDOW, {})
    events, _ = evaluate(_matrix(audusd_aud="BREAKDOWN"), TF, WINDOW, state)
    msg = format_message(events, TF, WINDOW, "2026-09-19T00:00:00+00:00")
    assert "AUD/USD vs AUD index" in msg and "Seesaw broken (1)" in msg
    assert "50-bar window" in msg and "2026-09-19 00:00 UTC" in msg


def test_env_roundtrip_and_token_scrubbing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# comment\nTELEGRAM_BOT_TOKEN=abc123\nEMPTY=\n", encoding="utf-8")
    env = load_env(p)
    assert env["TELEGRAM_BOT_TOKEN"] == "abc123" and "EMPTY" not in env
    save_env_value("TELEGRAM_CHAT_ID", "555", p)
    save_env_value("TELEGRAM_BOT_TOKEN", "xyz789", p)
    env = load_env(p)
    assert env == {"TELEGRAM_BOT_TOKEN": "xyz789", "TELEGRAM_CHAT_ID": "555"}
    assert "abc123" not in _scrub("failed for https://api.telegram.org/botabc123/x", "abc123")
