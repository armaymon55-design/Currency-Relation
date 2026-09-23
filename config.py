"""Project configuration. No secrets live here: the MT5 password stays inside the
terminal, which supplies it when we attach by login number + server."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = ROOT / "data_cache"


def _dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    values[k.strip()] = v.strip()
    return values


_FILE_ENV = _dotenv(ROOT / ".env")


def env(key: str, default: str = "") -> str:
    """Real environment first, then .env, then the default. Never a committed secret."""
    return os.environ.get(key) or _FILE_ENV.get(key, default)


# --- data feed -----------------------------------------------------------------
# Account details live in .env (gitignored), never in this file: the repository is public.
MT5_TERMINAL = env("MT5_TERMINAL", r"C:\Program Files\XM MT5\terminal64.exe")
MT5_LOGIN = int(env("MT5_LOGIN") or 0)
MT5_SERVER = env("MT5_SERVER")

# XM's server clock is GMT+2 in winter / GMT+3 in summer, switching with US daylight
# saving so the daily bar closes at 17:00 New York. Same rule, stated exactly:
# server time = New York wall time + 7 h.
BROKER_TZ_ANCHOR = "America/New_York"
BROKER_HOURS_AHEAD_OF_ANCHOR = 7

# Broker symbol naming: try EURUSDm# first, then EURUSD.
SYMBOL_SUFFIX_PREFERENCE = ["m#", ""]
REAL_DXY_SYMBOL = "USDX-DEC26"  # ICE dollar-index futures CFD, used only to verify the synthetic DXY

# --- universe ------------------------------------------------------------------
G10 = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK"]
# Market convention for which currency is quoted first: EUR/USD, USD/JPY, CHF/JPY, NOK/SEK ...
BASE_PRIORITY = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY"]

# --- measurement ---------------------------------------------------------------
HISTORY_START = "2019-01-01"
TIMEFRAMES = ["H1", "H4", "D1"]
WINDOWS = [20, 50, 100]
DEFAULT_WINDOW = 50
# Bars used to define what is "normal" for a pair x index (~2 trading years).
NORMAL_BAND_LOOKBACK = {"H1": 12000, "H4": 3000, "D1": 500}
NORMAL_BAND_PCT = (10, 90)
LINK_THRESHOLD = 0.4    # |rho| below this = no real relationship
STRONG_THRESHOLD = 0.7  # |rho| above this = strong
# "Today's move" for the attribution readout, in bars of each timeframe.
MOVE_BARS = {"H1": 24, "H4": 6, "D1": 1}

# --- live updater --------------------------------------------------------------
REFRESH_MINUTES = 5          # re-measure this often while the market is open
STALE_MINUTES = 20           # dashboard warns when the last successful update is older than this
HEARTBEAT_FILE = OUTPUT_DIR / "heartbeat.json"
LIVE_LOG_FILE = OUTPUT_DIR / "live.log"

# --- alerts ---------------------------------------------------------------------
ALERTS_ENABLED = True
ALERT_TF = "H1"              # alerts watch one timeframe/window; the dashboard still shows all
ALERT_WINDOW = 50
ALERT_STATE_FILE = OUTPUT_DIR / "alert_state.json"
# "the whole board is one trade": USD majors tighter than normal against DXY.
# Two thresholds so a reading hovering on the line cannot flap on and off.
ONE_TRADE_ON = 7
ONE_TRADE_OFF = 4
ALERT_ERROR_COOLDOWN_MINUTES = 60
