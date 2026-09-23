"""Build the public, static version of the dashboard from ECB daily rates.

    python -m public.build            # writes public/site/data/*

Same measurement engine as the private platform, three deliberate differences:
daily bars only (the ECB publishes one fix a day), no ICE-formula dollar index (the
name and formula are ICE's; the equal-weight USD basket is ours), and every number is
precomputed into JSON so the site needs no server at all.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import G10, NORMAL_BAND_LOOKBACK, WINDOWS  # noqa: E402
from public.ecb import ATTRIBUTION, fetch_rates, pair_closes  # noqa: E402
from src.data.universe import PairSource, all_pairs  # noqa: E402
from src.engine.attribution import attribute_window  # noqa: E402
from src.engine.health import LABELS  # noqa: E402
from src.engine.relations import latest_relation_arrays, relation_series  # noqa: E402
from src.engine.store import USD_MAJORS, DataStore  # noqa: E402
from src.indices.synthetic import strength, strength_loo  # noqa: E402

SITE = ROOT / "public" / "site"
DATA = SITE / "data"
TF = "D1"
INDICES = [f"{c}-EW" for c in G10]          # no DXY on the public build
SERIES_BARS = 300
CELL_FIELDS = ("sign", "beta", "rho", "r2", "strength", "health", "rho_lo", "rho_hi",
               "beta_lo", "beta_hi", "typical_abs_rho", "beta_normal")


def _clean(v):
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return round(float(v), 4) if math.isfinite(v) else None
    return v


def measure_daily(pairs: pd.DataFrame, sources: list[PairSource]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Latest reading for every pair x basket x window, plus today's attribution."""
    S = strength(pairs)
    S_loo = strength_loo(pairs)
    lookback = NORMAL_BAND_LOOKBACK[TF]
    tail = lookback + max(WINDOWS) + 1
    r_pairs = np.log(pairs).diff().iloc[1:].iloc[-tail:]
    asof = r_pairs.index[-1].isoformat()
    RP = r_pairs.to_numpy(dtype=np.float64)
    pcol = {n: j for j, n in enumerate(r_pairs.columns)}
    r_S = S.diff().iloc[1:].iloc[-tail:]
    RS = r_S.to_numpy(dtype=np.float64)
    scol = {c: j for j, c in enumerate(r_S.columns)}
    RL = {k: v.diff().iloc[1:].iloc[-tail:].to_numpy(dtype=np.float64) for k, v in S_loo.items()}
    rows, att = [], []
    for src in sources:
        rp = RP[:, pcol[src.name]]
        for window in WINDOWS:
            for c in G10:
                if c in (src.base, src.quote):
                    other = src.quote if c == src.base else src.base
                    ri = RL[(c, other)]
                else:
                    ri = RS[:, scol[c]]
                rel = latest_relation_arrays(src.name, f"{c}-EW", TF, rp, ri, window, lookback, asof)
                if rel:
                    rows.append(rel.as_dict())
        a = attribute_window(pairs[src.name], S[src.base], S[src.quote], 1)
        a.update(pair=src.name, tf=TF, base=src.base, quote=src.quote, bars=1)
        att.append(a)
    return pd.DataFrame(rows), pd.DataFrame(att)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def build(rates: pd.DataFrame | None = None, source: str = "test", out: Path = DATA) -> dict:
    if rates is None:
        rates, source = fetch_rates()
    pairs = pair_closes(rates)
    sources = [PairSource(b, q, b + q) for b, q in all_pairs()]
    matrix, att = measure_daily(pairs, sources)
    store = DataStore({TF: pairs}, sources, matrix, att, generated=datetime.now(timezone.utc).isoformat())
    asof = pairs.index[-1]

    meta = {
        "generated": store.generated, "asof": asof.isoformat(), "asof_date": f"{asof:%Y-%m-%d}",
        "timeframe": "daily", "windows": WINDOWS, "indices": INDICES, "labels": LABELS,
        "pairs": [p for p in USD_MAJORS if p in pairs.columns] + sorted(c for c in pairs.columns if c not in USD_MAJORS),
        "history_from": f"{pairs.index[0]:%Y-%m-%d}", "days": int(len(pairs)),
        "source": {"name": "European Central Bank euro reference rates", "detail": source, "attribution": ATTRIBUTION,
                   "url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
                   "cadence": "one fix per working day, published around 16:00 CET"},
    }
    write_json(out / "meta.json", meta)

    for window in WINDOWS:
        s = store.summary(TF, window)
        s["indices"] = INDICES
        s["cells"] = {p: {i: c for i, c in cells.items() if i != "DXY"} for p, cells in s["cells"].items()}
        s["anomalies"] = [a for a in s["anomalies"] if a["index"] != "DXY"]
        s["pairs"] = meta["pairs"]
        write_json(out / f"summary_w{window}.json", s)
        m = store.map_data(TF, window)
        write_json(out / f"map_w{window}.json", m)

    rows = {r["pair"]: {k: _clean(r[k]) for k in ("move_pct", "base_contrib_pct", "quote_contrib_pct", "base_share",
                                                    "quote_share", "residual_pct", "base", "quote")}
            for r in att.to_dict("records")}
    write_json(out / "attribution.json", {"bars": 1, "asof": asof.isoformat(), "rows": rows})

    lookback = NORMAL_BAND_LOOKBACK[TF]
    for src in sources:
        r_pair = np.log(pairs[src.name]).diff()
        entry: dict = {"t": {}, "rho": {}}
        for window in WINDOWS:
            entry["rho"][str(window)] = {}
            for index in INDICES:
                r_index = store.index_returns(TF, src.name, index)
                _, tail = relation_series(src.name, index, TF, r_pair, r_index, window, lookback, SERIES_BARS)
                entry["t"][str(window)] = [t.strftime("%Y-%m-%d") for t in tail.index]
                entry["rho"][str(window)][index] = [_clean(x) for x in tail["rho"]]
        write_json(out / "series" / f"{src.name}.json", entry)

    return {"pairs": len(sources), "rows": int(len(matrix)), "asof": meta["asof_date"], "days": meta["days"], "out": str(out)}


if __name__ == "__main__":
    info = build()
    print(f"built {info['rows']} readings for {info['pairs']} pairs, {info['days']} days to {info['asof']} -> {info['out']}")
