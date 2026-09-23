"""The predictability machinery must not be able to cheat: no lookahead, no inflated t."""
import numpy as np
import pandas as pd

from src.research.factor import (USD_LEGS, dollar_factor, forward_return, newey_west_t,
                                 predictors, sweep)


def _walk(n=1500, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-01", periods=n, freq="B", tz="UTC")
    return pd.Series(np.cumsum(rng.normal(0, 0.004, n)), index=idx)


def test_dollar_factor_matches_the_platform_definition():
    idx = pd.date_range("2020-01-01", periods=5, freq="D", tz="UTC")
    legs = pd.DataFrame({name: np.full(5, 2.0) for name in USD_LEGS}, index=idx)
    # every rate at 2.0: ln(USD/other) is +ln2 for the five USDXXX legs, -ln2 for the four XXXUSD
    expected = (5 * np.log(2) - 4 * np.log(2)) / 10
    assert np.allclose(dollar_factor(legs), expected)
    legs2 = legs.copy()
    legs2["EURUSD"] = 2.2                                  # euro up -> dollar factor down
    assert dollar_factor(legs2).iloc[0] < dollar_factor(legs).iloc[0]


def test_forward_return_looks_forward_only():
    x = pd.Series([0.0, 1.0, 3.0, 6.0], index=pd.date_range("2020-01-01", periods=4, tz="UTC"))
    f = forward_return(x, 1)
    assert list(f[:-1]) == [1.0, 2.0, 3.0] and np.isnan(f.iloc[-1])


def test_predictors_use_no_future_information():
    x = _walk()
    p = predictors(x)
    cut = 900
    truncated = predictors(x.iloc[:cut])
    for col in p.columns:                                   # same values whether or not the future exists
        a, b = p[col].iloc[:cut].dropna(), truncated[col].dropna()
        assert np.allclose(a.loc[b.index], b, equal_nan=True)


def test_newey_west_at_zero_lags_is_the_white_estimator():
    """With no overlap the sandwich collapses to heteroskedasticity-robust (HC0) errors."""
    rng = np.random.default_rng(3)
    x = rng.normal(size=500)
    y = 0.3 * x + rng.normal(size=500)
    slope, t = newey_west_t(y, x, lags=0)

    X = np.column_stack([np.ones(500), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    xtx_inv = np.linalg.pinv(X.T @ X)
    u = X * resid[:, None]
    hc0_se = np.sqrt((xtx_inv @ (u.T @ u) @ xtx_inv)[1, 1])
    assert np.isclose(slope, beta[1])
    assert np.isclose(t, beta[1] / hc0_se)

    ols_se = np.sqrt((resid @ resid) / (500 - 2) * xtx_inv[1, 1])   # classical, for scale only
    assert abs(t - beta[1] / ols_se) < 0.1 * abs(beta[1] / ols_se)


def test_overlap_deflates_the_t_statistic():
    """On a random walk, the overlapping t must be smaller than the naive one."""
    x = _walk(2000, seed=7)
    y = forward_return(x, 20)
    p = predictors(x)["momentum_20d"]
    df = pd.concat({"y": y, "x": p}, axis=1).dropna()
    xs = ((df["x"] - df["x"].mean()) / df["x"].std()).to_numpy()
    _, t_naive = newey_west_t(df["y"].to_numpy(), xs, lags=0)
    _, t_nw = newey_west_t(df["y"].to_numpy(), xs, lags=20)
    assert abs(t_nw) < abs(t_naive)


def test_sweep_shape_and_null_behaviour():
    out = sweep(_walk(1200, seed=11), horizons=(1, 5))
    assert len(out) == 12 and set(out["horizon"]) == {1, 5}
    assert out["n"].min() > 100
    assert (out["t_nw"].abs() < 4).all()                    # pure noise: nothing should look spectacular
