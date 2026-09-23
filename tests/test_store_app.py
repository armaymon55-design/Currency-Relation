"""Store + Flask API on a synthetic universe (no terminal, no cache files)."""
import numpy as np
import pandas as pd
import pytest

from config import G10
from src.data.universe import PairSource, all_pairs
from src.engine.store import DataStore


@pytest.fixture(scope="module")
def store():
    rng = np.random.default_rng(3)
    n = 3000
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    # a common dollar factor plus idiosyncratic noise, so USD pairs relate to DXY
    usd = np.cumsum(rng.normal(0, 0.002, n))
    values = {c: np.exp(np.cumsum(rng.normal(0, 0.001, n)) + (usd if c == "USD" else 0)) for c in G10}
    values = pd.DataFrame(values, index=idx)
    sources = [PairSource(b, q, b + q) for b, q in all_pairs()]
    pairs = pd.DataFrame({s.name: values[s.base] / values[s.quote] for s in sources})
    closes = {"H1": pairs, "H4": pairs.iloc[::4], "D1": pairs.iloc[::24]}
    matrix = pd.DataFrame([
        {"pair": "EURUSD", "index": "DXY", "tf": "H1", "window": 50, "rho": -0.95, "beta": -1.0, "r2": 0.9,
         "sign": "INVERSE", "strength": "strong", "rho_lo": -0.98, "rho_hi": -0.9, "beta_lo": -1.2, "beta_hi": -0.8,
         "typical_abs_rho": 0.94, "rho_normal": True, "beta_normal": True, "health": "HEALTHY",
         "asof": "2025-05-05T05:00:00+00:00"},
        {"pair": "AUDUSD", "index": "AUD-EW", "tf": "H1", "window": 50, "rho": -0.03, "beta": -0.1, "r2": 0.0,
         "sign": "NONE", "strength": "weak", "rho_lo": 0.48, "rho_hi": 0.85, "beta_lo": 0.5, "beta_hi": 1.2,
         "typical_abs_rho": 0.7, "rho_normal": False, "beta_normal": False, "health": "BREAKDOWN",
         "asof": "2025-05-05T05:00:00+00:00"},
    ])
    att = pd.DataFrame([{"pair": "EURUSD", "tf": "H1", "base": "EUR", "quote": "USD", "bars": 24,
                         "move_pct": -0.62, "base_contrib_pct": 0.01, "quote_contrib_pct": -0.63,
                         "base_share": -0.01, "quote_share": 1.01, "residual_pct": 0.0}])
    return DataStore(closes, sources, matrix, att, generated="test")


def test_summary_shape(store):
    s = store.summary("H1", 50)
    assert s["pairs"][0] == "EURUSD" and len(s["pairs"]) == 45 and s["indices"][0] == "DXY"
    assert s["cells"]["EURUSD"]["DXY"]["sign"] == "INVERSE"
    assert s["health_counts"] == {"HEALTHY": 1, "BREAKDOWN": 1}
    assert s["anomalies"][0]["pair"] == "AUDUSD" and s["anomalies"][0]["health"] == "BREAKDOWN"


def test_pair_detail_computes_live_series(store):
    d = store.pair_detail("EURUSD", "DXY", "H1", 50)
    assert d["reading"]["sign"] == "INVERSE" and d["reading"]["rho"] < -0.5
    assert len(d["series"]["rho"]) == 300 and len(d["series"]["t"]) == 300
    assert d["attribution"]["quote_share"] == pytest.approx(1.01)
    own = store.pair_detail("EURUSD", "EUR-EW", "H1", 50)   # own-currency index -> leave-one-out
    assert own["reading"] is not None


def test_whatif(store):
    d = store.whatif("DXY", 1.0, "H1", 50)
    assert d["index"] == "DXY" and d["move_pct"] == 1.0
    eur = next(r for r in d["results"] if r["pair"] == "EURUSD")
    assert eur["implied_pct"] == pytest.approx(-1.0) and eur["reliable"]
    assert d["reliable_count"] == len([r for r in d["results"] if r["reliable"]])
    assert store.whatif("DXY", -2.0, "H1", 50)["results"][0]["implied_pct"] == pytest.approx(2.0)


def test_map_data(store):
    m = store.map_data("H1", 50)
    assert [n["id"] for n in m["nodes"]] == list(G10) and len(m["links"]) == 45
    assert {n["bloc"] for n in m["nodes"]} <= {"dollar", "other"}
    assert next(n for n in m["nodes"] if n["id"] == "USD")["bloc"] == "dollar"
    link = m["links"][0]
    assert {"source", "target", "rho", "rho_lo", "rho_hi", "health"} <= set(link)
    assert sum(len(v) for v in m["blocs"].values()) == 10
    assert store.map_data("H1", 50) is m   # cached


def test_flask_endpoints(store):
    from app.server import create_app
    client = create_app(store).test_client()
    assert client.get("/").status_code == 200
    s = client.get("/api/summary?tf=H1&window=50").get_json()
    assert "cells" in s and s["labels"]["BREAKDOWN"] == "Seesaw broken"
    p = client.get("/api/pair/EURUSD?index=DXY&tf=H1&window=50").get_json()
    assert p["pair"] == "EURUSD" and "series" in p
    m = client.get("/api/map?tf=H1&window=50").get_json()
    assert len(m["nodes"]) == 10 and len(m["links"]) == 45
    w = client.get("/api/whatif?index=DXY&move=1&tf=H1&window=50").get_json()
    assert w["results"][0]["pair"] == "EURUSD"
    assert client.get("/api/whatif?index=DXY&move=99&tf=H1&window=50").status_code == 400
    assert client.get("/api/whatif?index=ZZZ&move=1&tf=H1&window=50").status_code == 404
    assert client.get("/api/summary?tf=M5&window=50").status_code == 400
    assert client.get("/api/pair/XXXYYY?tf=H1&window=50").status_code == 404
