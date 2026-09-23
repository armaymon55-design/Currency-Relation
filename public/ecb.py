"""Daily G10 rates from the European Central Bank's euro reference rates.

Published every working day around 16:00 CET, reusable under the ECB's open policy, and
served as one file with the whole history since 1999. Rates are units of currency per
1 EUR, so every pair is a ratio of two columns: A/B = rate[B] / rate[A] (EUR = 1).
"""
from __future__ import annotations

import io
import json
import urllib.request
import zipfile

import numpy as np
import pandas as pd

from config import G10
from src.data.universe import all_pairs

ECB_HIST_ZIP = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
FRANKFURTER = "https://api.frankfurter.dev/v1/1999-01-04..?base=EUR&symbols={symbols}"
NON_EUR = [c for c in G10 if c != "EUR"]
ATTRIBUTION = "Euro foreign exchange reference rates, European Central Bank (ECB), reused under the ECB's open data policy"


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "currency-relations/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_ecb() -> pd.DataFrame:
    """The ECB history file: one row per business day, one column per currency (per EUR)."""
    raw = _get(ECB_HIST_ZIP)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        csv = z.read(name)
    df = pd.read_csv(io.BytesIO(csv), na_values=["N/A"])
    df.columns = [c.strip() for c in df.columns]
    df = df[["Date"] + NON_EUR]
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    return df.set_index("Date").sort_index().astype("float64")


def fetch_frankfurter() -> pd.DataFrame:
    """Fallback: the same ECB rates through the Frankfurter API (no key, no limit)."""
    body = json.loads(_get(FRANKFURTER.format(symbols=",".join(NON_EUR))).decode("utf-8"))
    df = pd.DataFrame.from_dict(body["rates"], orient="index")
    df.index = pd.to_datetime(df.index, utc=True)
    return df.reindex(columns=NON_EUR).sort_index().astype("float64")


def fetch_rates() -> tuple[pd.DataFrame, str]:
    try:
        return fetch_ecb(), "ecb.europa.eu (eurofxref-hist)"
    except Exception as exc:  # noqa: BLE001 - try the mirror before giving up
        print(f"ECB file failed ({exc}); trying Frankfurter", flush=True)
        return fetch_frankfurter(), "api.frankfurter.dev (ECB rates)"


def pair_closes(rates: pd.DataFrame) -> pd.DataFrame:
    """All 45 G10 pairs in market orientation from the EUR-based table."""
    rates = rates.dropna(how="any").copy()
    rates["EUR"] = 1.0
    cols = {b + q: rates[q] / rates[b] for b, q in all_pairs()}
    out = pd.DataFrame(cols, index=rates.index)
    out.index.name = "time"
    return out.astype(np.float64)
