"""In-memory data for the dashboard: pair closes and indices per timeframe plus the
latest matrix and attribution from step 1. Reads the bar cache and output/ only —
it never touches the terminal."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from config import G10, MOVE_BARS, NORMAL_BAND_LOOKBACK, NORMAL_BAND_PCT, OUTPUT_DIR, TIMEFRAMES
from src.data.cache import read_cache
from src.data.universe import PairSource, build_pair_closes
from src.engine.blocs import bloc_names, split_blocs
from src.engine.health import LABELS, health_state
from src.engine.relations import relation_series
from src.engine.whatif import implied_moves
from src.indices.synthetic import dxy_ice, strength, strength_loo

USD_MAJORS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "USDSEK", "USDNOK"]
INDEX_ORDER = ["DXY"] + [f"{c}-EW" for c in G10]
CELL_FIELDS = ("sign", "beta", "rho", "r2", "strength", "health", "rho_lo", "rho_hi",
               "beta_lo", "beta_hi", "typical_abs_rho")
ANOMALY_FIELDS = ("pair", "index", "health", "rho", "rho_lo", "rho_hi", "typical_abs_rho", "beta")
ATT_FIELDS = ("move_pct", "base_contrib_pct", "quote_contrib_pct", "base_share", "quote_share",
              "residual_pct", "bars")


def _clean(v):
    """numpy scalars -> python, NaN/inf -> None, so the result is JSON-safe."""
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v) if math.isfinite(v) else None
    return v


class DataStore:
    def __init__(self, pair_closes: dict[str, pd.DataFrame], sources: list[PairSource],
                 matrix: pd.DataFrame, attribution: pd.DataFrame, generated: str = ""):
        self.pair_closes = pair_closes
        self.sources = sources
        self.matrix = matrix
        self.att = attribution
        self.generated = generated
        self._idx: dict[str, tuple] = {}
        self._map: dict[tuple[str, int], dict] = {}
        self._output_dir: Path | None = None
        self._mtime: float | None = None

    # --- loading -----------------------------------------------------------------
    @classmethod
    def from_disk(cls, output_dir: Path = OUTPUT_DIR) -> "DataStore":
        uni = json.loads((output_dir / "universe.json").read_text(encoding="utf-8"))
        sources = [PairSource(p["base"], p["quote"], p["symbol"], p["inverted"]) for p in uni["pairs"]]
        legs = {c: PairSource(l["base"], l["quote"], l["symbol"], l["inverted"]) for c, l in uni["legs"].items()}
        closes = {}
        for tf in TIMEFRAMES:
            pickled = output_dir / f"pair_closes_{tf}.pkl"
            if pickled.exists():
                closes[tf] = pd.read_pickle(pickled)          # written by run_matrix.py, ~50 ms
            else:                                             # fallback: rebuild from the bar cache
                symbol_close = {sym: read_cache(sym, tf)["close"] for sym in uni["symbols"]}
                closes[tf] = build_pair_closes(sources, legs, symbol_close)
        matrix = pd.read_csv(output_dir / "matrix.csv")
        att = pd.read_csv(output_dir / "attribution.csv")
        store = cls(closes, sources, matrix, att, uni.get("generated", ""))
        store._output_dir = output_dir
        store._mtime = (output_dir / "matrix.csv").stat().st_mtime
        return store

    def maybe_reload(self) -> None:
        """Pick up a fresh run_matrix.py output without restarting the server."""
        if self._output_dir is None:
            return
        mtime = (self._output_dir / "matrix.csv").stat().st_mtime
        if mtime != self._mtime:
            fresh = DataStore.from_disk(self._output_dir)
            self.__dict__.update(fresh.__dict__)

    # --- helpers -----------------------------------------------------------------
    def indices(self, tf: str) -> tuple:
        if tf not in self._idx:
            pairs = self.pair_closes[tf]
            self._idx[tf] = (dxy_ice(pairs), strength(pairs), strength_loo(pairs))
        return self._idx[tf]

    def pair_order(self) -> list[str]:
        names = [s.name for s in self.sources]
        return [p for p in USD_MAJORS if p in names] + sorted(n for n in names if n not in USD_MAJORS)

    def source(self, pair: str) -> PairSource:
        return next(s for s in self.sources if s.name == pair)

    def index_returns(self, tf: str, pair: str, index: str) -> pd.Series:
        dxy, S, S_loo = self.indices(tf)
        if index == "DXY":
            return np.log(dxy).diff()
        c = index.replace("-EW", "")
        src = self.source(pair)
        if c in (src.base, src.quote):
            other = src.quote if c == src.base else src.base
            return S_loo[(c, other)].diff()
        return S[c].diff()

    # --- API payloads --------------------------------------------------------------
    def summary(self, tf: str, window: int) -> dict:
        m = self.matrix[(self.matrix["tf"] == tf) & (self.matrix["window"] == window)]
        cells: dict[str, dict] = {}
        for r in m.to_dict("records"):
            cells.setdefault(r["pair"], {})[r["index"]] = {k: _clean(r[k]) for k in CELL_FIELDS}
        real = m[m["health"] != "NO_LINK"]
        counts = {k: int(v) for k, v in real["health"].value_counts().items()}
        anomalies = real[real["health"].str.startswith("WARNING") | (real["health"] == "BREAKDOWN")].copy()
        rows = []
        if len(anomalies):
            anomalies["dev"] = np.where(anomalies["rho"] > anomalies["rho_hi"],
                                        anomalies["rho"] - anomalies["rho_hi"],
                                        anomalies["rho_lo"] - anomalies["rho"])
            anomalies["rank"] = anomalies["health"].map({"BREAKDOWN": 0, "WARNING_LOOSE": 1, "WARNING_TIGHT": 2})
            anomalies = anomalies.sort_values(["rank", "dev"], ascending=[True, False]).head(20)
            rows = [{k: _clean(r[k]) for k in ANOMALY_FIELDS} for r in anomalies.to_dict("records")]
        return {
            "tf": tf, "window": window,
            "asof": m["asof"].max() if len(m) else None,
            "generated": self.generated,
            "pairs": self.pair_order(), "indices": INDEX_ORDER,
            "cells": cells, "health_counts": counts, "labels": LABELS, "anomalies": rows,
        }

    def pair_detail(self, pair: str, index: str, tf: str, window: int, last_n: int = 300) -> dict:
        pairs = self.pair_closes[tf]
        src = self.source(pair)
        r_pair = np.log(pairs[pair]).diff()
        r_index = self.index_returns(tf, pair, index)
        rel, tail = relation_series(pair, index, tf, r_pair, r_index, window, NORMAL_BAND_LOOKBACK[tf], last_n)
        a = self.att[(self.att["pair"] == pair) & (self.att["tf"] == tf)]
        att = {k: _clean(a.iloc[0][k]) for k in ATT_FIELDS} if len(a) else None
        return {
            "pair": pair, "base": src.base, "quote": src.quote, "index": index, "tf": tf, "window": window,
            "reading": {k: _clean(v) for k, v in rel.as_dict().items()} if rel else None,
            "label": LABELS.get(rel.health) if rel else None,
            "series": {
                "t": [t.isoformat() for t in tail.index],
                "rho": [_clean(x) for x in tail["rho"]],
                "beta": [_clean(x) for x in tail["beta"]],
            },
            "attribution": att,
            "last_close": _clean(pairs[pair].iloc[-1]),
            "last_time": pairs.index[-1].isoformat(),
        }

    def whatif(self, index: str, move_pct: float, tf: str, window: int) -> dict:
        """If `index` moves `move_pct`%, what each pair's current ratio implies."""
        m = self.matrix
        rows = m[(m["tf"] == tf) & (m["window"] == window) & (m["index"] == index)]
        results = implied_moves(rows, move_pct)
        return {
            "index": index, "move_pct": move_pct, "tf": tf, "window": window,
            "asof": rows["asof"].max() if len(rows) else None,
            "reliable_count": sum(1 for r in results if r["reliable"]),
            "results": results, "labels": LABELS,
        }

    def map_data(self, tf: str, window: int) -> dict:
        """Currency-level view for the 3D map: 10 nodes (strength over the last MOVE_BARS
        bars) and 45 links (correlation between two currencies' strength indices over the
        window, with the link's own normal band and health). Cached per tf/window."""
        key = (tf, window)
        if key in self._map:
            return self._map[key]
        _, S, _ = self.indices(tf)
        r = S.diff().dropna()
        bars = MOVE_BARS[tf]
        strength_now = (S.iloc[-1] - S.iloc[-1 - bars]) * 100
        lookback = NORMAL_BAND_LOOKBACK[tf]
        # blocs are structure, so they come from the long lookback; links are current
        blocs = split_blocs(r.iloc[-lookback:].corr())
        names = bloc_names(blocs)
        lo_p, hi_p = (p / 100 for p in NORMAL_BAND_PCT)
        nodes = [{"id": c, "strength_pct": _clean(strength_now[c]), "bloc": blocs[c], "bloc_name": names[blocs[c]]}
                 for c in G10]
        links = []
        for i, a in enumerate(G10):
            for b in G10[i + 1:]:
                rolling = r[a].rolling(window).corr(r[b]).dropna()
                if len(rolling) < window + 10:
                    continue
                rho_now = float(rolling.iloc[-1])
                hist = rolling.iloc[max(0, len(rolling) - 1 - lookback):-1]
                lo, hi = float(hist.quantile(lo_p)), float(hist.quantile(hi_p))
                typical = float(hist.abs().median())
                links.append({
                    "source": a, "target": b, "rho": _clean(rho_now), "rho_lo": lo, "rho_hi": hi,
                    "typical_abs_rho": typical, "health": health_state(rho_now, lo, hi, typical),
                })
        out = {
            "tf": tf, "window": window, "bars": bars, "asof": r.index[-1].isoformat(),
            "bloc_basis": f"last {min(lookback, len(r))} {tf} bars",
            "nodes": nodes, "links": links, "labels": LABELS,
            "blocs": {names[k]: [c for c in G10 if blocs[c] == k] for k in ("dollar", "other")},
        }
        self._map[key] = out
        return out
