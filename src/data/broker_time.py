"""Convert MT5 server timestamps to UTC and back.

MT5 hands back bar times as the broker's wall-clock time labelled as if it were UTC.
XM's clock is New York wall time + 7 h (GMT+2 in winter, GMT+3 in summer), so the
correction is a per-timestamp offset that follows US daylight saving, not a fixed shift.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import BROKER_HOURS_AHEAD_OF_ANCHOR, BROKER_TZ_ANCHOR


def _anchor_offset_hours(utc_naive: pd.DatetimeIndex) -> np.ndarray:
    """UTC offset of the anchor zone (-5 or -4 for New York) at each UTC instant."""
    local = utc_naive.tz_localize("UTC").tz_convert(BROKER_TZ_ANCHOR).tz_localize(None)
    return ((local - utc_naive) / pd.Timedelta(hours=1)).to_numpy()


def server_offset_hours(utc_naive: pd.DatetimeIndex) -> np.ndarray:
    """How far ahead of UTC the server clock is at each UTC instant (+2 or +3)."""
    return BROKER_HOURS_AHEAD_OF_ANCHOR + _anchor_offset_hours(utc_naive)


def server_to_utc(server_seconds) -> pd.DatetimeIndex:
    """Server-labelled epoch seconds (as returned by MT5) -> tz-aware UTC index."""
    wall = pd.DatetimeIndex(pd.to_datetime(np.asarray(server_seconds, dtype="int64"), unit="s"))
    # The DST state only matters to within a few hours of the switch, so evaluating it
    # at the wall time itself (as if the server were UTC) picks the right offset.
    offset = server_offset_hours(wall)
    return (wall - pd.to_timedelta(offset, unit="h")).tz_localize("UTC")


def utc_to_server(ts_utc: datetime | pd.Timestamp) -> datetime:
    """UTC instant -> the datetime MT5 range queries expect: server wall time, tagged UTC."""
    ts = pd.Timestamp(ts_utc)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    naive = pd.DatetimeIndex([ts.tz_localize(None)])
    offset = float(server_offset_hours(naive)[0])
    return (naive[0] + pd.Timedelta(hours=offset)).to_pydatetime().replace(tzinfo=timezone.utc)
