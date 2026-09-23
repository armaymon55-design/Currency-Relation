"""The G10 universe: pair naming convention, broker-symbol resolution, synthetic crosses."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

import numpy as np
import pandas as pd

from config import BASE_PRIORITY, G10, SYMBOL_SUFFIX_PREFERENCE


def conventional_pair(a: str, b: str) -> tuple[str, str]:
    """(base, quote) in market convention: ('EUR','USD'), ('USD','JPY'), ('NOK','SEK')."""
    return (a, b) if BASE_PRIORITY.index(a) < BASE_PRIORITY.index(b) else (b, a)


def all_pairs(currencies: Iterable[str] = G10) -> list[tuple[str, str]]:
    return [conventional_pair(a, b) for a, b in combinations(list(currencies), 2)]


@dataclass(frozen=True)
class PairSource:
    base: str
    quote: str
    symbol: str | None          # broker symbol that prices this pair; None = built from USD legs
    inverted: bool = False      # broker symbol is quoted quote/base

    @property
    def name(self) -> str:
        return f"{self.base}{self.quote}"

    @property
    def synthetic(self) -> bool:
        return self.symbol is None


def resolve_symbol(base: str, quote: str, available: set[str]) -> PairSource:
    for suffix in SYMBOL_SUFFIX_PREFERENCE:
        if f"{base}{quote}{suffix}" in available:
            return PairSource(base, quote, f"{base}{quote}{suffix}")
        if f"{quote}{base}{suffix}" in available:
            return PairSource(base, quote, f"{quote}{base}{suffix}", inverted=True)
    return PairSource(base, quote, None)


def resolve_universe(available: set[str], currencies: Iterable[str] = G10) -> list[PairSource]:
    return [resolve_symbol(b, q, available) for b, q in all_pairs(currencies)]


def usd_legs(available: set[str], currencies: Iterable[str] = G10) -> dict[str, PairSource]:
    """For each non-USD currency, the broker symbol that prices it against USD."""
    legs = {}
    for c in currencies:
        if c == "USD":
            continue
        b, q = conventional_pair(c, "USD")
        legs[c] = resolve_symbol(b, q, available)
    return legs


def oriented_close(src: PairSource, symbol_close: dict[str, pd.Series]) -> pd.Series:
    """Close series in base/quote orientation for a broker-quoted pair."""
    s = symbol_close[src.symbol]
    return (1.0 / s) if src.inverted else s


def usd_value(currency: str, legs: dict[str, PairSource], symbol_close: dict[str, pd.Series]):
    """Value of one unit of `currency` in USD (scalar 1.0 for USD itself)."""
    if currency == "USD":
        return 1.0
    leg = legs[currency]
    px = oriented_close(leg, symbol_close)          # base/quote orientation
    return px if leg.base == currency else 1.0 / px  # EUR/USD stays; USD/JPY -> 1/px


def build_pair_closes(
    sources: list[PairSource],
    legs: dict[str, PairSource],
    symbol_close: dict[str, pd.Series],
    ffill_limit: int = 3,
) -> pd.DataFrame:
    """One column per pair (base/quote orientation), aligned on a common UTC index.

    Broker-quoted pairs come straight from their symbol; missing crosses are built as
    value(base in USD) / value(quote in USD) from the USD legs.
    """
    cols = {}
    for src in sources:
        if src.synthetic:
            cols[src.name] = usd_value(src.base, legs, symbol_close) / usd_value(src.quote, legs, symbol_close)
        else:
            cols[src.name] = oriented_close(src, symbol_close)
    df = pd.concat(cols, axis=1).sort_index()
    df = df.ffill(limit=ffill_limit).dropna()
    return df.astype(np.float64)
