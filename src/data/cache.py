"""CSV bar cache shared by the MT5 client (writer) and the dashboard (reader only)."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from config import CACHE_DIR

COLS = ["open", "high", "low", "close", "tick_volume"]


def _stem(symbol: str, tf: str) -> str:
    return f"{re.sub(r'[^A-Za-z0-9_-]', '_', symbol)}_{tf}"


def cache_path(symbol: str, tf: str) -> Path:
    """Bars are kept as pandas pickles (milliseconds to load); older CSV caches still read."""
    return CACHE_DIR / f"{_stem(symbol, tf)}.pkl"


def legacy_csv_path(symbol: str, tf: str) -> Path:
    return CACHE_DIR / f"{_stem(symbol, tf)}.csv"


def empty_bars() -> pd.DataFrame:
    """An empty bar frame that still carries a UTC datetime index, so filters and concat work."""
    return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="time"))


def read_cache(symbol: str, tf: str) -> pd.DataFrame:
    path = cache_path(symbol, tf)
    if path.exists():
        return pd.read_pickle(path)
    csv = legacy_csv_path(symbol, tf)
    if not csv.exists():
        return empty_bars()
    df = pd.read_csv(csv)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("time"), utc=True, format="ISO8601"), name="time")
    return df.astype("float64")


def write_cache(df: pd.DataFrame, symbol: str, tf: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache_path(symbol, tf).with_suffix(".pkl.tmp")
    df.to_pickle(tmp)
    tmp.replace(cache_path(symbol, tf))
