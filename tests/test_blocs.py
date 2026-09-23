import numpy as np
import pandas as pd

from src.engine.blocs import bloc_names, split_blocs

A = ["USD", "CAD", "AUD", "NZD", "JPY"]
B = ["EUR", "GBP", "CHF", "SEK", "NOK"]


def test_two_bloc_structure_is_recovered():
    rng = np.random.default_rng(7)
    n = 2000
    f = rng.normal(0, 1, n)
    cols = {c: f + rng.normal(0, 0.8, n) for c in A}
    cols.update({c: -f + rng.normal(0, 0.8, n) for c in B})
    corr = pd.DataFrame(cols).corr()
    blocs = split_blocs(corr)
    assert all(blocs[c] == "dollar" for c in A)
    assert all(blocs[c] == "other" for c in B)
    assert bloc_names(blocs) == {"dollar": "dollar bloc", "other": "European bloc"}


def test_high_beta_naming():
    blocs = {c: "dollar" for c in ["USD", "EUR", "GBP", "JPY", "CHF", "CAD"]}
    blocs.update({c: "other" for c in ["AUD", "NZD", "SEK", "NOK"]})
    assert bloc_names(blocs) == {"dollar": "core bloc", "other": "high-beta bloc"}
