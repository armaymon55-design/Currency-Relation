"""Read-only MetaTrader 5 data client.

This module can only read prices. It contains no order, position or deal calls, and
tests/test_readonly.py fails if any are ever added. The MT5 password is never handled:
we attach by login number + server and the terminal supplies its saved credentials.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import MetaTrader5 as mt5

from config import MT5_LOGIN, MT5_SERVER, MT5_TERMINAL
from src.data.broker_time import server_to_utc, utc_to_server
from src.data.cache import COLS, empty_bars, read_cache, write_cache

TF = {"H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
TF_HOURS = {"H1": 1, "H4": 4, "D1": 24}
ACCOUNT_MODES = {0: "demo", 1: "contest", 2: "real"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_empty = empty_bars


class MT5Data:
    """Context manager around a terminal session: `with MT5Data() as feed: feed.bars(...)`."""

    def __init__(self, terminal: str = MT5_TERMINAL, login: int = MT5_LOGIN, server: str = MT5_SERVER):
        self.terminal, self.login, self.server = terminal, login, server
        self.account_mode = "unknown"

    def __enter__(self) -> "MT5Data":
        if not self.login or not self.server:
            raise ConnectionError(
                "no MT5 account configured - put MT5_LOGIN and MT5_SERVER in .env "
                "(see .env.example). The public ECB build does not need them."
            )
        if not mt5.initialize(self.terminal, login=self.login, server=self.server):
            raise ConnectionError(f"MT5 initialize failed: {mt5.last_error()}")
        info = mt5.account_info()
        if info is None or info.login != self.login:
            mt5.shutdown()
            raise ConnectionError(f"attached to the wrong account (wanted {self.login})")
        self.account_mode = ACCOUNT_MODES.get(info.trade_mode, "unknown")
        return self

    def __exit__(self, *exc) -> None:
        mt5.shutdown()

    # --- discovery ---------------------------------------------------------------
    def symbols(self) -> set[str]:
        return {s.name for s in mt5.symbols_get()}

    def select(self, symbols) -> None:
        """Put symbols in Market Watch; the terminal only syncs history for selected ones."""
        for s in symbols:
            if not mt5.symbol_select(s, True):
                raise ValueError(f"cannot select {s}: {mt5.last_error()}")

    def last_tick_utc(self, symbol: str) -> pd.Timestamp:
        info = mt5.symbol_info(symbol)
        return server_to_utc([int(info.time)])[0]

    # --- bars --------------------------------------------------------------------
    def _fetch(self, symbol: str, tf: str, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
        rates = mt5.copy_rates_range(symbol, TF[tf], utc_to_server(start_utc), utc_to_server(end_utc))
        if rates is None or len(rates) == 0:
            return _empty()
        df = pd.DataFrame(rates)
        df.index = server_to_utc(df["time"].to_numpy())
        df.index.name = "time"
        return df[COLS]

    def bars(self, symbol: str, tf: str, start_utc: datetime, end_utc: datetime | None = None,
             retries: int = 6, pause: float = 1.5) -> pd.DataFrame:
        """All bars with open time in [start, end], UTC index, fetched in yearly chunks.

        The terminal loads history lazily after a symbol is selected, so the first read
        can come back months stale. We re-read until the newest bar is recent (allowing a
        weekend) and two consecutive reads return the same number of bars.
        """
        end_utc = end_utc or _utcnow() + timedelta(days=1)
        stale_limit = _utcnow() - timedelta(hours=max(3 * TF_HOURS[tf], 72))
        # a long range is a first-time history download: also require two reads to agree,
        # because the terminal streams older bars in after the newest ones. A short tail
        # request (the live updater) is complete as soon as the newest bar is recent.
        long_range = (_utcnow() - start_utc) > timedelta(days=30)
        prev_len, df = -1, _empty()
        for attempt in range(retries):
            chunks, lo = [], start_utc
            while lo < end_utc:
                hi = min(lo + timedelta(days=366), end_utc)
                chunks.append(self._fetch(symbol, tf, lo, hi))
                lo = hi
            df = pd.concat(chunks)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            fresh = (not df.empty) and df.index[-1] >= pd.Timestamp(stale_limit)
            if fresh and (not long_range or len(df) == prev_len):
                break
            prev_len = len(df)
            time.sleep(pause)
        df = df[(df.index >= pd.Timestamp(start_utc)) & (df.index <= pd.Timestamp(end_utc))]
        return df.astype("float64")  # concat with an empty placeholder leaves object dtype behind

    def bars_cached(self, symbol: str, tf: str, start_utc: datetime) -> pd.DataFrame:
        """Like bars(), but keeps a CSV per symbol/timeframe and only fetches the new tail."""
        cached = read_cache(symbol, tf)
        fetch_from = start_utc if cached.empty else (cached.index[-1] - timedelta(hours=3 * TF_HOURS[tf])).to_pydatetime()
        fetch_from = max(fetch_from, start_utc)
        fresh = self.bars(symbol, tf, fetch_from)
        df = pd.concat([cached[cached.index < pd.Timestamp(fetch_from)], fresh])
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[df.index >= pd.Timestamp(start_utc)].astype("float64")
        write_cache(df, symbol, tf)
        return df
