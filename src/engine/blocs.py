"""Split the G10 into two blocs from the data.

The leading eigenvector of the correlation matrix of currency-strength returns has one
sign for the currencies that rise together and the opposite sign for those that fall
when they rise. That dominant "A up, B down" mode is the bloc split the literature
finds (a dollar bloc and a European bloc) — measured here, not assumed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def split_blocs(corr: pd.DataFrame, anchor: str = "USD") -> dict[str, str]:
    """Map each currency to 'dollar' (the bloc containing `anchor`) or 'other'."""
    names = list(corr.index)
    _, vecs = np.linalg.eigh(np.nan_to_num(corr.to_numpy(dtype=float)))
    lead = vecs[:, -1]
    if lead[names.index(anchor)] < 0:
        lead = -lead
    return {c: ("dollar" if lead[i] > 0 else "other") for i, c in enumerate(names)}


def bloc_names(blocs: dict[str, str]) -> dict[str, str]:
    """Human names from membership. On G10 data the dominant split is usually the
    high-beta currencies (AUD, NZD, SEK, NOK) against the rest — name it that way when
    that's what came out, and fall back to dollar / European naming otherwise."""
    dollar = {c for c, b in blocs.items() if b == "dollar"}
    other = {c for c, b in blocs.items() if b == "other"}
    if {"AUD", "NZD"} <= other and "USD" in dollar:
        return {"dollar": "core bloc", "other": "high-beta bloc"}
    return {"dollar": "dollar bloc", "other": "European bloc" if "EUR" in other else "other bloc"}
