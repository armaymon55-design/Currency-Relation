"""The measurement cycle on a synthetic universe, with no terminal: measure -> write -> heartbeat."""
import json

import numpy as np
import pandas as pd

from config import G10, TIMEFRAMES
from src.data.universe import PairSource, all_pairs, usd_legs
from src.indices.synthetic import dxy_ice
from src.pipeline import (_atomic_write, measure, merge_heartbeat, read_heartbeat, write_heartbeat,
                          write_outputs)


def _synthetic_data(n=1500, seed=5):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    usd = np.cumsum(rng.normal(0, 0.002, n))
    values = pd.DataFrame({c: np.exp(np.cumsum(rng.normal(0, 0.001, n)) + (usd if c == "USD" else 0)) for c in G10}, index=idx)
    sources = [PairSource(b, q, b + q) for b, q in all_pairs()]
    symbols = [s.symbol for s in sources]
    closes_h1 = {s.symbol: values[s.base] / values[s.quote] for s in sources}
    closes = {tf: closes_h1 for tf in TIMEFRAMES}
    pairs = pd.DataFrame(closes_h1)
    usdx = dxy_ice(pairs) * 0.998
    return {"sources": sources, "legs": usd_legs(set(symbols)), "symbols": symbols, "closes": closes,
            "usdx": usdx, "newest": {tf: idx[-1].isoformat() for tf in TIMEFRAMES}, "last_tick": idx[-1].isoformat()}


def test_measure_and_write_outputs(tmp_path):
    data = _synthetic_data()
    measured = measure(data, log=lambda *_: None)
    m = measured["matrix"]
    assert set(m["tf"]) == set(TIMEFRAMES) and set(m["window"]) == {20, 50, 100}
    eu = m[(m["pair"] == "EURUSD") & (m["index"] == "DXY") & (m["tf"] == "H1") & (m["window"] == 50)].iloc[0]
    assert eu["sign"] == "INVERSE" and eu["rho"] < -0.8
    assert measured["dxy_check"]["return_corr"] > 0.99
    write_outputs(data, measured, tmp_path)
    for name in ["matrix.csv", "attribution.csv", "universe.json", "pair_closes_H1.pkl", "indices_D1.csv"]:
        assert (tmp_path / name).exists()
    assert not list((tmp_path / ".tmp").iterdir())            # nothing left half-written
    uni = json.loads((tmp_path / "universe.json").read_text(encoding="utf-8"))
    assert len(uni["pairs"]) == 45 and uni["newest"]["H1"] == data["newest"]["H1"]
    assert len(pd.read_pickle(tmp_path / "pair_closes_H1.pkl").columns) == 45


def test_skipped_cycle_keeps_the_last_measurement_visible():
    measured = {"last_run_utc": "2026-09-19T10:00:00+00:00", "skipped": False, "rows": 4455,
                "dxy_check": {"return_corr": 0.987}, "health_counts_h1_w50": {"HEALTHY": 62},
                "newest_bar_utc": {"H1": "2026-09-19T09:00:00+00:00"}}
    first = merge_heartbeat({}, measured)
    assert first["last_success_utc"] == measured["last_run_utc"]

    skipped = merge_heartbeat(first, {"last_run_utc": "2026-09-19T10:05:00+00:00", "skipped": True,
                                      "market_open": False})
    assert skipped["dxy_check"] == {"return_corr": 0.987}      # carried, not dropped
    assert skipped["rows"] == 4455 and skipped["health_counts_h1_w50"] == {"HEALTHY": 62}
    assert skipped["last_run_utc"] == "2026-09-19T10:05:00+00:00"
    assert skipped["last_success_utc"] == "2026-09-19T10:00:00+00:00"   # still the real one

    again = merge_heartbeat(skipped, {"last_run_utc": "2026-09-19T10:10:00+00:00", "skipped": True})
    assert again["dxy_check"] == {"return_corr": 0.987}        # survives a run of skipped cycles
    assert again["last_success_utc"] == "2026-09-19T10:00:00+00:00"

    fresh = merge_heartbeat(again, {"last_run_utc": "2026-09-19T10:15:00+00:00", "skipped": False,
                                    "rows": 4455, "dxy_check": {"return_corr": 0.986}})
    assert fresh["dxy_check"] == {"return_corr": 0.986}        # a real cycle overwrites
    assert fresh["last_success_utc"] == "2026-09-19T10:15:00+00:00"


def test_heartbeat_roundtrip(tmp_path):
    path = tmp_path / "heartbeat.json"
    assert read_heartbeat(path) is None
    write_heartbeat({"status": "ok", "runs": 3, "last_success_utc": "2026-09-17T01:00:00+00:00"}, path)
    assert read_heartbeat(path)["runs"] == 3
    _atomic_write(path, lambda p: p.write_text("not json", encoding="utf-8"))
    assert read_heartbeat(path) is None                        # corrupt file never crashes the reader
