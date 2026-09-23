"""Rolling relationship between a pair's returns and an index's returns:
which way (sign), how much (beta), how reliable (rho, R2), and is that normal."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from config import LINK_THRESHOLD, NORMAL_BAND_PCT, STRONG_THRESHOLD
from src.engine.health import health_state


def _rolling_sum(x: np.ndarray, window: int) -> np.ndarray:
    c = np.cumsum(np.concatenate(([0.0], x)))
    return c[window:] - c[:-window]


def rolling_stats(p: np.ndarray, i: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Rolling sample correlation and beta (cov / var of the index) from cumulative sums —
    the same numbers pandas' rolling corr/cov/var give, without the per-call overhead.
    Inputs must be aligned and NaN-free; outputs have len(p) - window + 1 values."""
    n = float(window)
    sp, si = _rolling_sum(p, window), _rolling_sum(i, window)
    spp, sii, spi = _rolling_sum(p * p, window), _rolling_sum(i * i, window), _rolling_sum(p * i, window)
    cov = (spi - sp * si / n) / (n - 1)
    var_p = (spp - sp * sp / n) / (n - 1)
    var_i = (sii - si * si / n) / (n - 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        rho = cov / np.sqrt(var_p * var_i)
        beta = cov / var_i
    return rho, beta


def rolling_relations(r_pair: pd.Series, r_index: pd.Series, window: int) -> pd.DataFrame:
    """Per bar, over the trailing `window` bars: rho, beta (% pair per 1% index), r2."""
    df = pd.concat({"p": r_pair, "i": r_index}, axis=1).dropna()
    if len(df) < window:
        return pd.DataFrame(columns=["rho", "beta", "r2"], index=df.index[:0])
    rho, beta = rolling_stats(df["p"].to_numpy(dtype=np.float64), df["i"].to_numpy(dtype=np.float64), window)
    out = pd.DataFrame({"rho": rho, "beta": beta, "r2": rho ** 2}, index=df.index[window - 1:])
    return out.dropna()


def classify_sign(rho: float, link: float = LINK_THRESHOLD) -> str:
    if rho >= link:
        return "DIRECT"
    if rho <= -link:
        return "INVERSE"
    return "NONE"


def classify_strength(abs_rho: float, link: float = LINK_THRESHOLD, strong: float = STRONG_THRESHOLD) -> str:
    if abs_rho >= strong:
        return "strong"
    if abs_rho >= link:
        return "moderate"
    return "weak"


@dataclass
class Relation:
    pair: str
    index: str
    tf: str
    window: int
    rho: float
    beta: float
    r2: float
    sign: str
    strength: str
    rho_lo: float
    rho_hi: float
    beta_lo: float
    beta_hi: float
    typical_abs_rho: float
    rho_normal: bool
    beta_normal: bool
    health: str
    asof: str

    def as_dict(self) -> dict:
        return asdict(self)


def _tail(s: pd.Series, n: int) -> pd.Series:
    return s.iloc[-n:] if len(s) > n else s


def latest_relation_arrays(pair: str, index: str, tf: str, p: np.ndarray, i: np.ndarray,
                           window: int, lookback: int, asof: str) -> Relation | None:
    """Fast path for the measurement loop: aligned numpy return arrays in, Relation out.
    Rows where either side is NaN are dropped jointly, as the pandas path does."""
    bad = np.isnan(p) | np.isnan(i)
    if bad.any():
        p, i = p[~bad], i[~bad]
    if len(p) < window + 10:
        return None
    rho, beta = rolling_stats(p, i, window)
    ok = ~(np.isnan(rho) | np.isnan(beta))
    rho, beta = rho[ok], beta[ok]
    if len(rho) < window + 10:
        return None
    hist_rho = rho[max(0, len(rho) - 1 - lookback):-1]
    hist_beta = beta[max(0, len(beta) - 1 - lookback):-1]
    lo, hi = (q / 100 for q in NORMAL_BAND_PCT)
    rho_lo, rho_hi = (float(v) for v in np.quantile(hist_rho, [lo, hi]))
    beta_lo, beta_hi = (float(v) for v in np.quantile(hist_beta, [lo, hi]))
    typical = float(np.median(np.abs(hist_rho)))
    rho_now, beta_now = float(rho[-1]), float(beta[-1])
    return Relation(
        pair=pair, index=index, tf=tf, window=window,
        rho=rho_now, beta=beta_now, r2=rho_now ** 2,
        sign=classify_sign(rho_now), strength=classify_strength(abs(rho_now)),
        rho_lo=rho_lo, rho_hi=rho_hi, beta_lo=beta_lo, beta_hi=beta_hi,
        typical_abs_rho=typical,
        rho_normal=bool(rho_lo <= rho_now <= rho_hi),
        beta_normal=bool(beta_lo <= beta_now <= beta_hi),
        health=health_state(rho_now, rho_lo, rho_hi, typical),
        asof=asof,
    )


def latest_relation(pair: str, index: str, tf: str, r_pair: pd.Series, r_index: pd.Series,
                    window: int, lookback: int) -> Relation | None:
    """The current reading plus its normal band, from the trailing `lookback` bars.

    Only the last lookback + window bars can influence the result, so the rolling
    statistics are computed on that tail."""
    n = lookback + window + 1
    df = pd.concat({"p": _tail(r_pair, n), "i": _tail(r_index, n)}, axis=1).dropna()
    if df.empty:
        return None
    return latest_relation_arrays(pair, index, tf, df["p"].to_numpy(dtype=np.float64),
                                  df["i"].to_numpy(dtype=np.float64), window, lookback, df.index[-1].isoformat())


def relation_series(pair: str, index: str, tf: str, r_pair: pd.Series, r_index: pd.Series,
                    window: int, lookback: int, last_n: int = 300) -> tuple[Relation | None, pd.DataFrame]:
    """The current reading plus the trailing `last_n` bars of the rolling series (for charts)."""
    n = max(lookback, last_n) + window + 1
    rel = rolling_relations(_tail(r_pair, n), _tail(r_index, n), window)
    return summarise(rel, pair, index, tf, window, lookback), rel.iloc[-last_n:]


def summarise(rel: pd.DataFrame, pair: str, index: str, tf: str, window: int, lookback: int) -> Relation | None:
    if len(rel) < window + 10:
        return None
    now = rel.iloc[-1]
    hist = rel.iloc[max(0, len(rel) - 1 - lookback):-1]
    lo, hi = (p / 100 for p in NORMAL_BAND_PCT)
    rho_lo, rho_hi = float(hist["rho"].quantile(lo)), float(hist["rho"].quantile(hi))
    beta_lo, beta_hi = float(hist["beta"].quantile(lo)), float(hist["beta"].quantile(hi))
    typical = float(hist["rho"].abs().median())
    rho_now, beta_now = float(now["rho"]), float(now["beta"])
    return Relation(
        pair=pair, index=index, tf=tf, window=window,
        rho=rho_now, beta=beta_now, r2=float(now["r2"]),
        sign=classify_sign(rho_now), strength=classify_strength(abs(rho_now)),
        rho_lo=rho_lo, rho_hi=rho_hi, beta_lo=beta_lo, beta_hi=beta_hi,
        typical_abs_rho=typical,
        rho_normal=bool(rho_lo <= rho_now <= rho_hi),
        beta_normal=bool(beta_lo <= beta_now <= beta_hi),
        health=health_state(rho_now, rho_lo, rho_hi, typical),
        asof=rel.index[-1].isoformat(),
    )
