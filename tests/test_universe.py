import numpy as np
import pandas as pd

from src.data.universe import (all_pairs, build_pair_closes, conventional_pair, resolve_symbol,
                               resolve_universe, usd_legs)


def test_conventional_orientation():
    assert conventional_pair("USD", "EUR") == ("EUR", "USD")
    assert conventional_pair("JPY", "USD") == ("USD", "JPY")
    assert conventional_pair("SEK", "NOK") == ("NOK", "SEK")
    assert conventional_pair("JPY", "CHF") == ("CHF", "JPY")


def test_45_pairs():
    assert len(all_pairs()) == 45


def test_resolution_prefers_m_hash_then_plain_then_inverted():
    available = {"EURUSDm#", "EURUSD", "USDSEK", "JPYCHF"}
    assert resolve_symbol("EUR", "USD", available).symbol == "EURUSDm#"
    assert resolve_symbol("USD", "SEK", available).symbol == "USDSEK"
    inv = resolve_symbol("CHF", "JPY", available)
    assert inv.symbol == "JPYCHF" and inv.inverted
    assert resolve_symbol("CHF", "SEK", available).synthetic


def test_synthetic_cross_from_usd_legs():
    idx = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
    available = {"EURUSD", "USDSEK", "USDCHF"}
    symbol_close = {
        "EURUSD": pd.Series([1.10, 1.10, 1.10], index=idx),
        "USDSEK": pd.Series([10.0, 10.0, 10.0], index=idx),
        "USDCHF": pd.Series([0.90, 0.90, 0.90], index=idx),
    }
    sources = resolve_universe(available, ["USD", "EUR", "CHF", "SEK"])
    legs = usd_legs(available, ["USD", "EUR", "CHF", "SEK"])
    closes = build_pair_closes(sources, legs, symbol_close)
    assert set(closes.columns) == {"EURUSD", "USDCHF", "USDSEK", "EURCHF", "EURSEK", "CHFSEK"}
    assert np.isclose(closes["CHFSEK"].iloc[0], (1 / 0.90) / (1 / 10.0))   # 11.11
    assert np.isclose(closes["EURCHF"].iloc[0], 1.10 * 0.90)                # 0.99
    assert np.isclose(closes["EURSEK"].iloc[0], 1.10 * 10.0)                # 11.0
