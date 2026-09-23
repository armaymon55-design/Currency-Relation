"""One measurement cycle: fetch (read-only) -> build indices -> measure -> write outputs.

Shared by scripts/run_matrix.py (one shot, with a printed report) and scripts/live.py
(every few minutes, forever). Outputs are written to output/.tmp and then moved into
place one by one, matrix.csv last, so a running dashboard only ever sees complete files.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    G10, HEARTBEAT_FILE, HISTORY_START, MOVE_BARS, NORMAL_BAND_LOOKBACK, OUTPUT_DIR,
    REAL_DXY_SYMBOL, TIMEFRAMES, WINDOWS,
)
from src.data.universe import build_pair_closes, resolve_universe, usd_legs
from src.engine.attribution import attribute_window
from src.engine.relations import latest_relation_arrays
from src.indices.synthetic import dxy_ice, strength, strength_loo, to_index


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- fetch ---------------------------------------------------------------------------
def fetch_all(feed, log=print, start: str = HISTORY_START) -> dict:
    """Pull (incrementally, via the cache) every symbol on every timeframe.

    `feed` is an attached MT5Data. Returns sources, legs, symbols, closes
    ({tf: {symbol: close series}}), usdx, newest ({tf: last bar UTC}) and last_tick.
    """
    start_utc = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    available = feed.symbols()
    sources = resolve_universe(available)
    legs = usd_legs(available)
    symbols = sorted({s.symbol for s in sources if not s.synthetic} | {l.symbol for l in legs.values()})
    n_syn = sum(1 for s in sources if s.synthetic)
    log(f"universe: {len(sources)} pairs, {len(symbols)} broker symbols, {n_syn} crosses built from USD legs")
    feed.select(symbols + [REAL_DXY_SYMBOL])
    closes: dict[str, dict[str, pd.Series]] = {}
    newest: dict[str, str] = {}
    for tf in TIMEFRAMES:
        t0 = time.time()
        closes[tf] = {sym: feed.bars_cached(sym, tf, start_utc)["close"] for sym in symbols}
        last = max(s.index[-1] for s in closes[tf].values())
        newest[tf] = last.isoformat()
        log(f"{tf}: {len(symbols)} symbols up to {last:%Y-%m-%d %H:%M} UTC ({time.time() - t0:.1f}s)")
    usdx = feed.bars_cached(REAL_DXY_SYMBOL, "H1", start_utc)["close"]
    probe = next(s.symbol for s in sources if s.name == "EURUSD")
    last_tick = feed.last_tick_utc(probe).isoformat()
    return {"sources": sources, "legs": legs, "symbols": symbols, "closes": closes,
            "usdx": usdx, "newest": newest, "last_tick": last_tick}


# --- measure -------------------------------------------------------------------------
def dxy_check(dxy_synth: pd.Series, usdx: pd.Series) -> dict:
    both = pd.concat({"synth": dxy_synth, "usdx": usdx}, axis=1).dropna()
    r = np.log(both).diff().dropna()
    ratio = both["usdx"] / both["synth"]
    return {"bars": int(len(r)), "return_corr": float(r["synth"].corr(r["usdx"])),
            "level_ratio_mean": float(ratio.mean()), "level_ratio_sd": float(ratio.std())}


def measure(data: dict, log=print) -> dict:
    """Every pair x index x window x timeframe -> latest reading; plus attribution and
    the per-timeframe close/index frames the dashboard loads."""
    sources, legs, closes = data["sources"], data["legs"], data["closes"]
    results, attributions, frames = [], [], {}
    check = None
    for tf in TIMEFRAMES:
        t0 = time.time()
        pairs = build_pair_closes(sources, legs, closes[tf])
        dxy = dxy_ice(pairs)
        S = strength(pairs)
        S_loo = strength_loo(pairs)
        if tf == "H1":
            check = dxy_check(dxy, data["usdx"])
        lookback = NORMAL_BAND_LOOKBACK[tf]
        # Only the trailing lookback + window bars can influence a reading, so work on
        # that tail as plain numpy arrays (row 0 of a diff is NaN and is dropped).
        tail = lookback + max(WINDOWS) + 1
        r_pairs = np.log(pairs).diff().iloc[1:].iloc[-tail:]
        asof = r_pairs.index[-1].isoformat()
        RP = r_pairs.to_numpy(dtype=np.float64)
        pcol = {name: j for j, name in enumerate(r_pairs.columns)}
        RD = np.log(dxy).diff().iloc[1:].iloc[-tail:].to_numpy(dtype=np.float64)
        r_S = S.diff().iloc[1:].iloc[-tail:]
        RS = r_S.to_numpy(dtype=np.float64)
        scol = {c: j for j, c in enumerate(r_S.columns)}
        RL = {k: v.diff().iloc[1:].iloc[-tail:].to_numpy(dtype=np.float64) for k, v in S_loo.items()}
        for src in sources:
            rp = RP[:, pcol[src.name]]
            for window in WINDOWS:
                rel = latest_relation_arrays(src.name, "DXY", tf, rp, RD, window, lookback, asof)
                if rel:
                    results.append(rel.as_dict())
                for c in G10:
                    if c in (src.base, src.quote):
                        # own currency: index that leaves the counterpart out
                        other = src.quote if c == src.base else src.base
                        ri = RL[(c, other)]
                    else:
                        ri = RS[:, scol[c]]
                    rel = latest_relation_arrays(src.name, f"{c}-EW", tf, rp, ri, window, lookback, asof)
                    if rel:
                        results.append(rel.as_dict())
            a = attribute_window(pairs[src.name], S[src.base], S[src.quote], MOVE_BARS[tf])
            a.update(pair=src.name, tf=tf, base=src.base, quote=src.quote, bars=MOVE_BARS[tf])
            attributions.append(a)
        frames[tf] = {"pairs": pairs, "indices": pd.concat([dxy, to_index(S)], axis=1)}
        log(f"{tf}: measured {len(sources)} pairs x 11 indices x {len(WINDOWS)} windows on {len(pairs)} bars ({time.time() - t0:.1f}s)")
    return {"matrix": pd.DataFrame(results), "attribution": pd.DataFrame(attributions),
            "frames": frames, "dxy_check": check}


# --- write ---------------------------------------------------------------------------
def _atomic_write(path: Path, writer) -> None:
    """writer(tmp_path) writes the file; it is then moved over `path` in one step."""
    tmp_dir = path.parent / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / path.name
    writer(tmp)
    os.replace(tmp, path)


def write_outputs(data: dict, measured: dict, out_dir: Path = OUTPUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    universe = {
        "generated": utcnow().isoformat(),
        "pairs": [{"name": s.name, "base": s.base, "quote": s.quote, "symbol": s.symbol, "inverted": s.inverted}
                  for s in data["sources"]],
        "legs": {c: {"base": l.base, "quote": l.quote, "symbol": l.symbol, "inverted": l.inverted}
                 for c, l in data["legs"].items()},
        "symbols": data["symbols"],
        "newest": data["newest"],
        "dxy_check": measured["dxy_check"],
    }
    _atomic_write(out_dir / "universe.json", lambda p: p.write_text(json.dumps(universe, indent=1), encoding="utf-8"))
    for tf, fr in measured["frames"].items():
        _atomic_write(out_dir / f"pair_closes_{tf}.pkl", lambda p, fr=fr: fr["pairs"].to_pickle(p))
        _atomic_write(out_dir / f"indices_{tf}.csv",
                      lambda p, fr=fr: fr["indices"].to_csv(p, date_format="%Y-%m-%dT%H:%M:%S%z"))
    _atomic_write(out_dir / "attribution.csv", lambda p: measured["attribution"].to_csv(p, index=False))
    # matrix.csv goes last: its mtime is what tells the dashboard a complete new snapshot exists
    _atomic_write(out_dir / "matrix.csv", lambda p: measured["matrix"].to_csv(p, index=False))


# --- heartbeat -----------------------------------------------------------------------
def write_heartbeat(info: dict, path: Path = HEARTBEAT_FILE) -> None:
    _atomic_write(path, lambda p: p.write_text(json.dumps(info, indent=1), encoding="utf-8"))


# Figures that describe the last real measurement rather than the last cycle. A skipped
# cycle (weekend: no new ticks) has none of them, so it inherits them instead of dropping them.
CARRY_FORWARD = ("dxy_check", "rows", "health_counts_h1_w50", "newest_bar_utc")


def merge_heartbeat(prev: dict, info: dict) -> dict:
    """The heartbeat to write: this cycle's status, keeping the last measurement visible."""
    merged = dict(info)
    if info.get("skipped"):
        for field in CARRY_FORWARD:
            if merged.get(field) is None and prev.get(field) is not None:
                merged[field] = prev[field]
        merged["last_success_utc"] = prev.get("last_success_utc") or info.get("last_run_utc")
    else:
        merged["last_success_utc"] = info["last_run_utc"]
    return merged


def read_heartbeat(path: Path = HEARTBEAT_FILE) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- one cycle -----------------------------------------------------------------------
def run_once(log=print, prev_tick: str | None = None, out_dir: Path = OUTPUT_DIR) -> dict:
    """Fetch, measure, write. Returns a summary dict (also used for the heartbeat).

    If `prev_tick` equals the feed's current last tick, the market hasn't moved since
    the last cycle (weekend / holiday): the fetch still runs but the recompute is skipped.
    """
    from src.data.mt5_client import MT5Data  # imported here so tests can import this module without MT5

    t0 = time.time()
    with MT5Data() as feed:
        log(f"MT5 attached: login {feed.login} on {feed.server} ({feed.account_mode} account, read-only)")
        data = fetch_all(feed, log)
        account_mode = feed.account_mode
    market_open = data["last_tick"] != prev_tick
    info = {"last_run_utc": utcnow().isoformat(), "account_mode": account_mode,
            "newest_bar_utc": data["newest"], "last_tick_utc": data["last_tick"],
            "market_open": market_open, "skipped": not market_open}
    if not market_open:
        log("no new ticks since last cycle - market closed, recompute skipped")
        info["elapsed_s"] = round(time.time() - t0, 1)
        return info
    measured = measure(data, log)
    write_outputs(data, measured, out_dir)
    m = measured["matrix"]
    h1 = m[(m["tf"] == "H1") & (m["window"] == 50) & (m["health"] != "NO_LINK")]
    info.update({
        "rows": int(len(m)),
        "health_counts_h1_w50": {k: int(v) for k, v in h1["health"].value_counts().items()},
        "dxy_check": measured["dxy_check"],
        "elapsed_s": round(time.time() - t0, 1),
        "matrix": m, "attribution": measured["attribution"],   # for the one-shot report; not persisted
    })
    log(f"cycle done in {info['elapsed_s']}s: {len(m)} readings written")
    return info
