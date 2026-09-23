"""Split a pair's move into its two legs: how much was the base currency, how much the quote.

With equal-weight strength indices the identity is exact:
    ln-return(base/quote) = strength_return(base) - strength_return(quote)
so the base contributes +strength_return(base) and the quote contributes -strength_return(quote).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def attribute_move(pair_logret: float, base_logret: float, quote_logret: float, eps: float = 1e-9) -> dict:
    base_contrib = base_logret
    quote_contrib = -quote_logret
    total = base_contrib + quote_contrib
    shares_ok = abs(total) > eps
    return {
        "move_pct": 100 * (math.exp(pair_logret) - 1),
        "base_contrib_pct": 100 * base_contrib,
        "quote_contrib_pct": 100 * quote_contrib,
        "base_share": base_contrib / total if shares_ok else float("nan"),
        "quote_share": quote_contrib / total if shares_ok else float("nan"),
        "residual_pct": 100 * (pair_logret - total),
    }


def attribute_window(pair_close: pd.Series, s_base: pd.Series, s_quote: pd.Series, bars: int) -> dict:
    """Attribution of the move over the last `bars` bars (log strength series in, dict out)."""
    pair_ret = float(np.log(pair_close.iloc[-1] / pair_close.iloc[-1 - bars]))
    b = float(s_base.iloc[-1] - s_base.iloc[-1 - bars])
    q = float(s_quote.iloc[-1] - s_quote.iloc[-1 - bars])
    return attribute_move(pair_ret, b, q)
