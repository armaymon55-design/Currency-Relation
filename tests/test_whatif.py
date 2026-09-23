import pandas as pd

from src.engine.whatif import implied_moves


def _rows():
    return pd.DataFrame([
        {"pair": "EURUSD", "beta": -1.0, "rho": -0.95, "r2": 0.90, "strength": "strong",
         "health": "HEALTHY", "beta_lo": -1.2, "beta_hi": -0.8, "beta_normal": True},
        {"pair": "USDSEK", "beta": 1.7, "rho": 0.92, "r2": 0.85, "strength": "strong",
         "health": "WARNING_TIGHT", "beta_lo": 1.3, "beta_hi": 1.9, "beta_normal": False},
        {"pair": "EURGBP", "beta": 0.05, "rho": 0.06, "r2": 0.00, "strength": "weak",
         "health": "NO_LINK", "beta_lo": -0.3, "beta_hi": 0.3, "beta_normal": True},
    ])


def test_implied_scales_with_the_move_and_sorts_by_impact():
    out = implied_moves(_rows(), 1.0)
    assert [r["pair"] for r in out] == ["USDSEK", "EURUSD", "EURGBP"]   # biggest first, no-link last
    assert out[1]["implied_pct"] == -1.0 and out[0]["implied_pct"] == 1.7
    assert out[0]["reliable"] and not out[2]["reliable"]
    half = implied_moves(_rows(), 0.5)
    assert half[1]["implied_pct"] == -0.5


def test_band_ends_stay_ordered_for_a_negative_move():
    out = implied_moves(_rows(), -2.0)
    eur = next(r for r in out if r["pair"] == "EURUSD")
    assert eur["implied_pct"] == 2.0
    assert eur["implied_lo"] == 1.6 and eur["implied_hi"] == 2.4   # -1.2*-2 .. -0.8*-2, ordered
    assert eur["implied_lo"] <= eur["implied_pct"] <= eur["implied_hi"]
