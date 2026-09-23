"""Scenario arithmetic: if an index moves X%, what does each pair's measured ratio imply?

This is conditional, not a forecast. It says "when this index has moved 1%, this pair has
historically moved beta%", so every row carries how reliable that relationship is right
now (correlation, share explained) and the range implied by the ratio's own normal band.
"""
from __future__ import annotations

import math

import pandas as pd

from config import LINK_THRESHOLD

FIELDS = ("pair", "beta", "rho", "r2", "strength", "health", "beta_lo", "beta_hi", "beta_normal")


def _finite(v: float) -> float | None:
    return float(v) if v is not None and math.isfinite(v) else None


def implied_moves(rows: pd.DataFrame, move_pct: float, link: float = LINK_THRESHOLD) -> list[dict]:
    """One row per pair, most-affected first; pairs with no reliable link sink to the bottom.

    `rows` is the matrix slice for a single index/timeframe/window.
    """
    out = []
    for r in rows.to_dict("records"):
        beta = _finite(r["beta"])
        if beta is None:
            continue
        ends = sorted((r["beta_lo"] * move_pct, r["beta_hi"] * move_pct))
        reliable = r["health"] != "NO_LINK" and abs(r["rho"]) >= link
        out.append({
            "pair": r["pair"],
            "beta": beta,
            "implied_pct": beta * move_pct,
            "implied_lo": _finite(ends[0]),
            "implied_hi": _finite(ends[1]),
            "rho": _finite(r["rho"]),
            "r2": _finite(r["r2"]),
            "strength": r["strength"],
            "health": r["health"],
            "beta_normal": bool(r["beta_normal"]),
            "reliable": bool(reliable),
        })
    out.sort(key=lambda d: (not d["reliable"], -abs(d["implied_pct"])))
    return out
