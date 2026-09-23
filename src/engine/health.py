"""Three-state health of a pair x index relationship ("is the seesaw working?")."""
from __future__ import annotations

from config import LINK_THRESHOLD

BREAKDOWN_TYPICAL = 0.6  # a relationship must normally be at least this strong to "break"

STATES = ("HEALTHY", "WARNING_TIGHT", "WARNING_LOOSE", "BREAKDOWN", "NO_LINK")
LABELS = {
    "HEALTHY": "Normal for this pair",
    "WARNING_TIGHT": "Tighter than normal",
    "WARNING_LOOSE": "Looser than normal",
    "BREAKDOWN": "Seesaw broken",
    "NO_LINK": "No real link",
}


def health_state(rho_now: float, rho_lo: float, rho_hi: float, typical_abs_rho: float,
                 link: float = LINK_THRESHOLD, strong: float = BREAKDOWN_TYPICAL) -> str:
    """
    NO_LINK       - this pair x index never had a real relationship, so nothing can break.
    BREAKDOWN     - normally strong (median |rho| >= 0.6) but now below the link threshold.
    WARNING_TIGHT - outside its normal band (10th-90th pct of recent history) on the
                    strong side: the two are moving together MORE than usual.
    WARNING_LOOSE - outside the band on the weak side: the relationship is loosening.
    HEALTHY       - inside the band.
    """
    if typical_abs_rho < link:
        return "NO_LINK"
    if abs(rho_now) < link and typical_abs_rho >= strong:
        return "BREAKDOWN"
    if rho_lo <= rho_now <= rho_hi:
        return "HEALTHY"
    usual_sign = 1 if (rho_lo + rho_hi) >= 0 else -1
    stronger = rho_now > rho_hi if usual_sign > 0 else rho_now < rho_lo
    return "WARNING_TIGHT" if stronger else "WARNING_LOOSE"


def is_warning(state: str) -> bool:
    return state.startswith("WARNING")
