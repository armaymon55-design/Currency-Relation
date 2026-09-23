"""The public build on a synthetic ECB-shaped table: pairs, measurement, JSON layout."""
import json

import numpy as np
import pandas as pd

from config import G10
from public.build import build
from public.ecb import NON_EUR, pair_closes


def _ecb_like(n=900, seed=2):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-03", periods=n, freq="B", tz="UTC")
    base = {"USD": 1.1, "JPY": 160.0, "GBP": 0.85, "CHF": 0.95, "CAD": 1.48, "AUD": 1.65, "NZD": 1.8, "SEK": 11.2, "NOK": 11.6}
    df = pd.DataFrame({c: base[c] * np.exp(np.cumsum(rng.normal(0, 0.004, n))) for c in NON_EUR}, index=idx)
    df.iloc[10, 2] = np.nan            # an ECB holiday gap for one currency
    return df


def test_pairs_from_eur_legs():
    rates = _ecb_like(20)
    p = pair_closes(rates)
    assert p.shape[1] == 45 and len(p) == 19          # the NaN row is dropped
    row = rates.dropna().iloc[0]
    assert np.isclose(p["EURUSD"].iloc[0], row["USD"])
    assert np.isclose(p["USDJPY"].iloc[0], row["JPY"] / row["USD"])
    assert np.isclose(p["NOKSEK"].iloc[0], row["SEK"] / row["NOK"])
    assert np.isclose(p["GBPUSD"].iloc[0], row["USD"] / row["GBP"])


def test_build_writes_the_static_layout(tmp_path):
    info = build(_ecb_like(), source="synthetic", out=tmp_path)
    assert info["pairs"] == 45 and info["rows"] > 0
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert "DXY" not in meta["indices"] and len(meta["indices"]) == 10
    assert meta["source"]["name"].startswith("European Central Bank")
    s = json.loads((tmp_path / "summary_w50.json").read_text(encoding="utf-8"))
    assert "DXY" not in s["cells"]["EURUSD"] and s["cells"]["EURUSD"]["USD-EW"]["sign"] == "INVERSE"
    assert set(s["health_counts"]) <= {"HEALTHY", "WARNING_TIGHT", "WARNING_LOOSE", "BREAKDOWN"}
    m = json.loads((tmp_path / "map_w50.json").read_text(encoding="utf-8"))
    assert len(m["nodes"]) == 10 and len(m["links"]) == 45
    att = json.loads((tmp_path / "attribution.json").read_text(encoding="utf-8"))
    assert att["rows"]["EURUSD"]["base"] == "EUR" and att["bars"] == 1
    ser = json.loads((tmp_path / "series" / "EURUSD.json").read_text(encoding="utf-8"))
    assert set(ser["rho"]["50"]) == set(meta["indices"])
    assert len(ser["rho"]["50"]["USD-EW"]) == len(ser["t"]["50"]) <= 300
    assert not list(tmp_path.glob("**/*.tmp"))        # nothing half-written
