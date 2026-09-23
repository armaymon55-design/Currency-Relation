"""Stage 1 of the predictive research: is the dollar factor predictable from its own past?

    python scripts/research_factor.py

Every other predictor (rate differentials, positioning) has to beat this baseline, so it
is tested first and on its own. Daily bars back to 2006, split into a study period and a
sealed period the rules were never chosen on.

Outputs: output/research/factor_predictability.{csv,txt}
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import OUTPUT_DIR  # noqa: E402
from src.data.mt5_client import MT5Data  # noqa: E402
from src.data.universe import resolve_symbol  # noqa: E402
from src.research.factor import USD_LEGS, dollar_factor, sweep  # noqa: E402

RESEARCH_DIR = OUTPUT_DIR / "research"
LEGS_CACHE = RESEARCH_DIR / "usd_legs_D1.pkl"
START = "2006-01-01"
SEALED_FROM = "2019-01-01"     # the study period ends here; everything after is untouched
HORIZONS = (1, 5, 20)
REPORT: list[str] = []


def log(msg: str = "") -> None:
    print(msg, flush=True)
    REPORT.append(msg)


def load_legs(refresh: bool = False) -> pd.DataFrame:
    if LEGS_CACHE.exists() and not refresh:
        return pd.read_pickle(LEGS_CACHE)
    start = datetime.fromisoformat(START).replace(tzinfo=timezone.utc)
    cols = {}
    with MT5Data() as feed:
        log(f"MT5 attached: login {feed.login} ({feed.account_mode} account, read-only)")
        available = feed.symbols()
        wanted = {name: resolve_symbol(name[:3], name[3:], available) for name in USD_LEGS}
        feed.select([s.symbol for s in wanted.values()])
        for name, src in wanted.items():
            bars = feed.bars(src.symbol, "D1", start)["close"]
            cols[name] = (1.0 / bars) if src.inverted else bars
            log(f"  {name}: {len(bars)} daily bars from {bars.index[0]:%Y-%m-%d}")
    legs = pd.concat(cols, axis=1).dropna()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    legs.to_pickle(LEGS_CACHE)
    return legs


def show(table: pd.DataFrame, title: str) -> None:
    log()
    log(f"=== {title} ===")
    log(f"{'predictor':<16}{'h':>3}{'n':>7}{'IC':>8}{'slope/sd':>11}{'t (NW)':>9}{'t (no-ovl)':>12}{'n(no-ovl)':>11}")
    for _, r in table.iterrows():
        log(f"{r['predictor']:<16}{r['horizon']:>3}{r['n']:>7}{r['ic']:>8.3f}"
            f"{r['slope'] * 100:>10.3f}%{r['t_nw']:>9.2f}{r['t_nonoverlap']:>12.2f}{r['n_nonoverlap']:>11}")


def main() -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    legs = load_legs()
    factor = dollar_factor(legs)
    log(f"dollar factor: {len(factor)} daily observations, {factor.index[0]:%Y-%m-%d} to {factor.index[-1]:%Y-%m-%d}")
    moves = factor.diff().dropna()
    log(f"daily move: sd {moves.std() * 100:.3f}%, annualised {moves.std() * np.sqrt(252) * 100:.1f}%")

    study = factor[factor.index < SEALED_FROM]
    sealed = factor[factor.index >= SEALED_FROM]
    log(f"study period {study.index[0]:%Y-%m-%d} to {study.index[-1]:%Y-%m-%d} ({len(study)} days); "
        f"sealed period {sealed.index[0]:%Y-%m-%d} to {sealed.index[-1]:%Y-%m-%d} ({len(sealed)} days)")

    tables = [sweep(study, HORIZONS, "study"), sweep(sealed, HORIZONS, "sealed"), sweep(factor, HORIZONS, "all")]
    for table, title in zip(tables, ["STUDY period (2006 to 2018)", "SEALED period (2019 to now)", "WHOLE sample"]):
        show(table, title)

    out = pd.concat(tables, ignore_index=True)
    out.to_csv(RESEARCH_DIR / "factor_predictability.csv", index=False)

    log()
    log("=== verdict ===")
    cells = len(tables[0])
    log(f"{cells} predictor x horizon cells per period. Testing that many at the 5% level means "
        f"roughly {0.05 * cells:.1f} cells cross |t| = 2 by chance alone, so a lone 2.1 means nothing.")
    study_t, sealed_t = tables[0].set_index(["predictor", "horizon"]), tables[1].set_index(["predictor", "horizon"])
    survivors = []
    for k in study_t.index:
        s, o = study_t.loc[k], sealed_t.loc[k]
        if abs(s["t_nw"]) >= 2 and abs(o["t_nw"]) >= 2 and np.sign(s["slope"]) == np.sign(o["slope"]):
            survivors.append((k, s, o))
    if survivors:
        log(f"{len(survivors)} cell(s) reached |t| >= 2 in BOTH periods with the same sign:")
        for (pred, h), s, o in survivors:
            log(f"  {pred} at h={h}: study t {s['t_nw']:+.2f} (slope {s['slope'] * 100:+.3f}%), "
                f"sealed t {o['t_nw']:+.2f} (slope {o['slope'] * 100:+.3f}%)")
        log("Next: re-check with a walk-forward before treating any of these as real.")
    else:
        log("NOTHING survived: no predictor reached |t| >= 2 in both the study and the sealed period "
            "with a consistent sign. The dollar factor's own past does not forecast its future at these "
            "horizons - which is the expected result, and the baseline any external predictor must beat.")
    (RESEARCH_DIR / "factor_predictability.txt").write_text("\n".join(REPORT), encoding="utf-8")
    log()
    log(f"wrote {RESEARCH_DIR / 'factor_predictability.csv'} and .txt")


if __name__ == "__main__":
    main()
