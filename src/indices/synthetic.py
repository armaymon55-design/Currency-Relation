"""Currency indices built from the pairs themselves.

* `dxy_ice`   — the published ICE dollar-index formula (six legs, fixed weights).
* `strength`  — equal-weight log strength per currency: the mean of ln(c/k) over all N
                currencies in the universe (the c/c term is zero), i.e. the currency's
                log value minus the universe average. That makes the split exact:
                ln-return(A/B) == strength_return(A) - strength_return(B).
                (Averaging over the other N-1 only would scale the difference by N/(N-1).)
* `strength_loo` — the same, leaving one counterpart out. Used when relating a pair to
                its own currency's index, so the pair isn't compared with a basket that
                already contains it.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from config import G10
from src.data.universe import conventional_pair

DXY_CONSTANT = 50.14348112
DXY_WEIGHTS = {
    "EURUSD": -0.576, "USDJPY": 0.136, "GBPUSD": -0.119,
    "USDCAD": 0.091, "USDSEK": 0.042, "USDCHF": 0.036,
}


def dxy_ice(pair_close: pd.DataFrame) -> pd.Series:
    """ICE DXY from the six legs: 50.14348112 * EURUSD^-0.576 * USDJPY^0.136 * ..."""
    log_level = pd.Series(np.log(DXY_CONSTANT), index=pair_close.index)
    for pair, w in DXY_WEIGHTS.items():
        log_level = log_level + w * np.log(pair_close[pair])
    return np.exp(log_level).rename("DXY")


def _log_rate(logp: pd.DataFrame, c: str, k: str) -> pd.Series:
    """ln(c/k) from whichever orientation the pair is quoted in."""
    b, q = conventional_pair(c, k)
    col = logp[b + q]
    return col if b == c else -col


def strength(pair_close: pd.DataFrame, currencies: Iterable[str] = G10) -> pd.DataFrame:
    """Equal-weight log strength, one column per currency."""
    currencies = list(currencies)
    n = len(currencies)
    logp = np.log(pair_close)
    out = {}
    for c in currencies:
        legs = [_log_rate(logp, c, k) for k in currencies if k != c]
        out[c] = pd.concat(legs, axis=1).sum(axis=1) / n
    return pd.DataFrame(out)


def strength_loo(pair_close: pd.DataFrame, currencies: Iterable[str] = G10) -> dict[tuple[str, str], pd.Series]:
    """Leave-one-out strengths: key (c, excluded) -> strength of c measured in the universe
    without `excluded` (same definition as `strength`, on N-1 currencies)."""
    currencies = list(currencies)
    n = len(currencies) - 1
    logp = np.log(pair_close)
    out = {}
    for c in currencies:
        for ex in currencies:
            if ex == c:
                continue
            legs = [_log_rate(logp, c, k) for k in currencies if k not in (c, ex)]
            out[(c, ex)] = pd.concat(legs, axis=1).sum(axis=1) / n
    return out


def to_index(strength_log: pd.DataFrame | pd.Series, base: float = 100.0):
    """Turn a log-strength series into an index that starts at `base`."""
    return base * np.exp(strength_log - strength_log.iloc[0])
