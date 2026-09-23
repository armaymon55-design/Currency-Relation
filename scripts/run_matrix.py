"""One-shot measurement with a printed report (the live updater runs the same cycle on a loop).

    python scripts/run_matrix.py

Outputs (in output/): matrix.csv, attribution.csv, indices_<tf>.csv, pair_closes_<tf>.pkl,
universe.json, report.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DEFAULT_WINDOW, MOVE_BARS, OUTPUT_DIR  # noqa: E402
from src.pipeline import run_once  # noqa: E402

REPORT: list[str] = []


def log(msg: str = "") -> None:
    print(msg, flush=True)
    REPORT.append(msg)


def report(matrix: pd.DataFrame, att: pd.DataFrame, tf: str = "H1", window: int = DEFAULT_WINDOW) -> None:
    m = matrix[(matrix["tf"] == tf) & (matrix["window"] == window)]
    log()
    log(f"=== {tf}, window {window}: USD pairs vs DXY ===")
    usd = m[(m["index"] == "DXY") & m["pair"].str.contains("USD")]
    for _, r in usd.iterrows():
        log(f"  {r['pair']:7s} {r['sign']:8s} beta {r['beta']:+.2f}x  rho {r['rho']:+.2f}  R2 {r['r2']:.2f}  "
            f"normal rho [{r['rho_lo']:+.2f}, {r['rho_hi']:+.2f}]  {r['health']}")

    log()
    log(f"=== {tf}, window {window}: each pair vs its own two currencies (index ex-counterpart) ===")
    for pair in sorted(m["pair"].unique()):
        base, quote = pair[:3], pair[3:]
        cells = []
        for c in (base, quote):
            r = m[(m["pair"] == pair) & (m["index"] == f"{c}-EW")]
            if len(r):
                r = r.iloc[0]
                cells.append(f"{c}: {r['sign']:7s} beta {r['beta']:+.2f} rho {r['rho']:+.2f} {r['health']}")
        log(f"  {pair:7s} | " + " | ".join(cells))

    log()
    real = m[m["health"] != "NO_LINK"]
    log(f"=== Health counts ({tf} w{window}, real links only): {real['health'].value_counts().to_dict()} ===")
    anomalies = real[real["health"].str.startswith("WARNING") | (real["health"] == "BREAKDOWN")].copy()
    if len(anomalies):
        anomalies["dev"] = np.where(anomalies["rho"] > anomalies["rho_hi"],
                                    anomalies["rho"] - anomalies["rho_hi"],
                                    anomalies["rho_lo"] - anomalies["rho"])
        anomalies = anomalies.sort_values(["health", "dev"], ascending=[True, False]).head(15)
        log("Top anomalies (rho outside its normal band):")
        for _, r in anomalies.iterrows():
            log(f"  {r['health']:13s} {r['pair']:7s} vs {r['index']:7s} rho {r['rho']:+.2f} "
                f"(normal [{r['rho_lo']:+.2f}, {r['rho_hi']:+.2f}], typical |rho| {r['typical_abs_rho']:.2f})")

    log()
    log(f"=== Attribution - last {MOVE_BARS[tf]} {tf} bars, USD pairs ===")
    a = att[(att["tf"] == tf) & att["pair"].str.contains("USD")]
    for _, r in a.iterrows():
        log(f"  {r['pair']:7s} {r['move_pct']:+.2f}% = {r['base']} {r['base_contrib_pct']:+.2f} ({r['base_share']:.0%}) "
            f"/ {r['quote']} {r['quote_contrib_pct']:+.2f} ({r['quote_share']:.0%})  residual {r['residual_pct']:+.3f}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    info = run_once(log=log)
    c = info["dxy_check"]
    log(f"DXY check (H1, {c['bars']} overlapping bars): return correlation {c['return_corr']:.3f}; "
        f"USDX/synthetic level ratio mean {c['level_ratio_mean']:.4f} sd {c['level_ratio_sd']:.4f} (futures basis)")
    report(info["matrix"], info["attribution"])
    log()
    log(f"Wrote {OUTPUT_DIR / 'matrix.csv'} ({info['rows']} rows) and companions in {info['elapsed_s']}s")
    (OUTPUT_DIR / "report.txt").write_text("\n".join(REPORT), encoding="utf-8")


if __name__ == "__main__":
    main()
