import math

import numpy as np
import pandas as pd

from src.engine.attribution import attribute_move
from src.engine.health import health_state
from src.engine.relations import classify_sign, classify_strength, latest_relation, rolling_relations


def _series(n=3000, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    r_i = pd.Series(rng.normal(0, 0.001, n), index=idx)
    r_p = -1.4 * r_i + pd.Series(rng.normal(0, 0.0002, n), index=idx)
    r_noise = pd.Series(rng.normal(0, 0.001, n), index=idx)
    return r_i, r_p, r_noise


def test_inverse_relationship_recovered():
    r_i, r_p, _ = _series()
    rel = latest_relation("PAIR", "IDX", "H1", r_p, r_i, window=50, lookback=1000)
    assert rel is not None
    assert -1.7 < rel.beta < -1.1
    assert rel.rho < -0.9 and rel.sign == "INVERSE" and rel.strength == "strong"
    assert rel.health == "HEALTHY"


def test_no_relationship_is_none():
    r_i, _, r_noise = _series()
    rel = latest_relation("PAIR", "IDX", "H1", r_noise, r_i, window=50, lookback=1000)
    assert rel.sign == "NONE" and rel.health == "NO_LINK"


def test_rolling_columns():
    r_i, r_p, _ = _series(n=300)
    out = rolling_relations(r_p, r_i, 50)
    assert list(out.columns) == ["rho", "beta", "r2"] and len(out) == 251


def test_rolling_matches_pandas():
    r_i, r_p, _ = _series(n=400, seed=9)
    out = rolling_relations(r_p, r_i, 50)
    ref_rho = r_p.rolling(50).corr(r_i).dropna()
    ref_beta = (r_p.rolling(50).cov(r_i) / r_i.rolling(50).var()).dropna()
    assert np.allclose(out["rho"].to_numpy(), ref_rho.to_numpy(), atol=1e-9)
    assert np.allclose(out["beta"].to_numpy(), ref_beta.to_numpy(), atol=1e-9)
    assert out.index.equals(ref_rho.index)


def test_classifiers():
    assert classify_sign(0.5) == "DIRECT" and classify_sign(-0.5) == "INVERSE" and classify_sign(0.1) == "NONE"
    assert classify_strength(0.8) == "strong" and classify_strength(0.5) == "moderate" and classify_strength(0.2) == "weak"


def test_health_states():
    assert health_state(-0.9, -0.95, -0.7, 0.85) == "HEALTHY"
    assert health_state(-0.6, -0.95, -0.7, 0.85) == "WARNING_LOOSE"    # usually inverse, now weaker
    assert health_state(-0.98, -0.95, -0.7, 0.85) == "WARNING_TIGHT"   # usually inverse, now stronger
    assert health_state(0.95, 0.5, 0.85, 0.7) == "WARNING_TIGHT"       # usually direct, now stronger
    assert health_state(0.42, 0.5, 0.85, 0.7) == "WARNING_LOOSE"       # usually direct, now weaker
    assert health_state(-0.2, -0.95, -0.7, 0.85) == "BREAKDOWN"
    assert health_state(0.1, -0.3, 0.3, 0.15) == "NO_LINK"


def test_attribution_shares_sum_to_one():
    a = attribute_move(pair_logret=-0.0062, base_logret=-0.0014, quote_logret=0.0048)
    assert math.isclose(a["base_share"] + a["quote_share"], 1.0)
    assert math.isclose(a["base_contrib_pct"] + a["quote_contrib_pct"], -0.62, abs_tol=1e-9)
    assert abs(a["residual_pct"]) < 1e-9
    assert a["quote_share"] > 0.7  # the dollar did most of the work
