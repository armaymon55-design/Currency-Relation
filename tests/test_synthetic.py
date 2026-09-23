import numpy as np
import pandas as pd

from config import G10
from src.data.universe import all_pairs
from src.indices.synthetic import DXY_CONSTANT, dxy_ice, strength, strength_loo


def _pairs_from_currency_values(values: pd.DataFrame) -> pd.DataFrame:
    """Pair closes implied by a table of currency values (price of 1 unit in a numeraire)."""
    return pd.DataFrame({b + q: values[b] / values[q] for b, q in all_pairs()})


def test_dxy_constant_when_all_legs_are_one():
    idx = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    ones = pd.DataFrame(1.0, index=idx, columns=["EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDSEK", "USDCHF"])
    assert np.allclose(dxy_ice(ones), DXY_CONSTANT)


def test_dxy_euro_weight():
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    legs = pd.DataFrame(1.0, index=idx, columns=["EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDSEK", "USDCHF"])
    legs["EURUSD"] = 1.10
    assert np.isclose(dxy_ice(legs).iloc[0], DXY_CONSTANT * 1.10 ** -0.576)


def test_strength_split_is_exact():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC")
    values = pd.DataFrame(np.exp(np.cumsum(rng.normal(0, 0.002, (200, 10)), axis=0)), index=idx, columns=G10)
    pairs = _pairs_from_currency_values(values)
    S = strength(pairs)
    dS = S.diff().dropna()
    r = np.log(pairs).diff().dropna()
    for b, q in all_pairs():
        assert np.allclose(r[b + q], dS[b] - dS[q], atol=1e-12)


def test_loo_excludes_the_counterpart():
    idx = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC")
    values = pd.DataFrame(1.0, index=idx, columns=G10)
    values["EUR"] = np.linspace(1.0, 1.2, 50)          # only the euro moves
    pairs = _pairs_from_currency_values(values)
    loo = strength_loo(pairs)
    assert np.allclose(loo[("USD", "EUR")].diff().dropna(), 0.0)      # USD ex-EUR: flat
    assert (strength(pairs)["USD"].diff().dropna() < 0).all()          # full USD basket: falls
