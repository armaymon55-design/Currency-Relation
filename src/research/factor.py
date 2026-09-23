"""Forward-predictability testing for the dollar factor.

The rule this module exists to enforce: a predictor is measured at time t and the target
is the return from t to t+h. Nothing at or after t+1 may touch the predictor, and the
overlap created by h > 1 must be paid for in the standard error — otherwise a t-statistic
is inflated several times over, which is how contemporaneous relationships get mistaken
for forecasts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# The nine legs that price every other G10 currency against the dollar.
USD_LEGS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "USDSEK", "USDNOK"]
G10_SIZE = 10


def dollar_factor(legs: pd.DataFrame) -> pd.Series:
    """Equal-weight log strength of the dollar: mean of ln(USD/other) over the G10.

    Same definition as the platform's USD-EW index (divided by N, not N-1, so that
    pair returns split exactly into the two currencies' strength changes).
    """
    log_usd_per = []
    for name in USD_LEGS:
        base = name[:3]
        col = np.log(legs[name])
        log_usd_per.append(col if base == "USD" else -col)   # want ln(USD/other) in every case
    return pd.concat(log_usd_per, axis=1).sum(axis=1).div(G10_SIZE).rename("dollar_factor")


def forward_return(x: pd.Series, h: int) -> pd.Series:
    """Return from t to t+h, aligned at t. The last h observations are NaN by construction."""
    return x.shift(-h) - x


def predictors(x: pd.Series) -> pd.DataFrame:
    """Everything here is known at t: only past values are used."""
    out = pd.DataFrame(index=x.index)
    out["reversal_1d"] = -(x - x.shift(1))
    for k in (5, 20, 60):
        out[f"momentum_{k}d"] = x - x.shift(k)
    out["distance_200d"] = x - x.rolling(200).mean()
    out["volatility_20d"] = (x - x.shift(1)).rolling(20).std()
    return out


def newey_west_t(y: np.ndarray, x: np.ndarray, lags: int) -> tuple[float, float]:
    """Slope and its Newey-West t-statistic for y = a + b*x, robust to the overlap in y.

    At lags=0 this is the White (HC0) estimator, so it differs slightly from a classical
    OLS t even without overlap; no small-sample correction is applied.
    """
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ (X.T @ y)
    resid = y - X @ beta
    u = X * resid[:, None]
    S = u.T @ u
    for lag in range(1, lags + 1):                      # Bartlett kernel
        w = 1.0 - lag / (lags + 1.0)
        G = u[lag:].T @ u[:-lag]
        S += w * (G + G.T)
    cov = xtx_inv @ S @ xtx_inv
    se = float(np.sqrt(max(cov[1, 1], 0.0)))
    return float(beta[1]), (float(beta[1] / se) if se > 0 else float("nan"))


def non_overlapping_t(y: pd.Series, x: pd.Series, h: int) -> tuple[float, int]:
    """The same slope on every h-th observation only, so the samples cannot overlap."""
    ys, xs = y.iloc[::h].to_numpy(), x.iloc[::h].to_numpy()
    if len(ys) < 12:
        return float("nan"), len(ys)
    _, t = newey_west_t(ys, xs, lags=0)
    return t, len(ys)


def test_predictor(x: pd.Series, pred: pd.Series, h: int) -> dict:
    """One predictor, one horizon: information coefficient and honest t-statistics."""
    y = forward_return(x, h)
    df = pd.concat({"y": y, "x": pred}, axis=1).dropna()
    if len(df) < 100:
        return {"n": len(df), "ic": np.nan, "slope": np.nan, "t_nw": np.nan,
                "t_nonoverlap": np.nan, "n_nonoverlap": 0}
    xs = (df["x"] - df["x"].mean()) / df["x"].std()      # standardised: slope reads per 1 sd
    slope, t_nw = newey_west_t(df["y"].to_numpy(), xs.to_numpy(), lags=h)
    t_no, n_no = non_overlapping_t(df["y"], xs, h)
    return {"n": len(df), "ic": float(df["y"].corr(df["x"], method="spearman")),
            "slope": slope, "t_nw": t_nw, "t_nonoverlap": t_no, "n_nonoverlap": n_no}


def sweep(x: pd.Series, horizons=(1, 5, 20), period: str = "all") -> pd.DataFrame:
    preds = predictors(x)
    rows = []
    for name in preds.columns:
        for h in horizons:
            rows.append({"predictor": name, "horizon": h, "period": period,
                         **test_predictor(x, preds[name], h)})
    return pd.DataFrame(rows)
