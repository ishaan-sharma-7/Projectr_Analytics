"""Campus master plan adapter — planned on-campus bed pipeline.

Reads a curated JSON file (backend/data/master_plans.json) that tracks
universities with announced or in-progress on-campus residential expansions.

Each entry includes:
  planned_beds     — total beds announced / under construction
  horizon_year     — expected first occupancy
  p3_deal          — whether this involves a P3 private partner
  p3_partner       — operator name if P3
  confidence       — "high" | "medium" | "low"

The planned_beds_weighted value time-discounts beds based on horizon:
  ≤ 1yr out  → 1.00  (under construction / imminent)
  2–3yr out  → 0.70
  4–5yr out  → 0.40
  6+yr out   → 0.20

This weighted figure feeds into the pressure score multiplier chain:
a large planned pipeline is a negative signal for off-campus PBSH demand.
"""

import json
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).parent.parent / "fixtures" / "master_plans.json"
_CURRENT_YEAR = 2026  # update when data is refreshed


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[master_plans] Failed to load JSON: {exc}")
        return []


def _time_discount(horizon_year: int | None) -> float:
    """Return a [0,1] discount based on years until planned beds open."""
    if horizon_year is None:
        return 0.4  # unknown timeline — treat as mid-range
    years_out = max(0, horizon_year - _CURRENT_YEAR)
    if years_out <= 1:
        return 1.00
    if years_out <= 3:
        return 0.70
    if years_out <= 5:
        return 0.40
    return 0.20


def _normalize_name(name: str) -> str:
    """Normalize university name for matching: lowercase, hyphens → spaces, collapse whitespace."""
    return " ".join(name.strip().lower().replace("-", " ").split())


def lookup(university_name: str) -> dict | None:
    """Return raw master plan entry for a university, or None if not in data.

    Matching is case-insensitive with hyphen/whitespace normalization so that
    IPEDS names like "University of California-Los Angeles" match fixture entries
    written as "University of California Los Angeles".
    """
    target = _normalize_name(university_name)
    for entry in _load():
        if _normalize_name(entry.get("university_name", "")) == target:
            return entry
    return None


def get_planned_beds(university_name: str) -> dict | None:
    """Return a dict with planned_beds, planned_beds_weighted, and metadata.

    Returns None if the university has no master plan entry.
    """
    entry = lookup(university_name)
    if not entry:
        return None

    planned_beds = entry.get("planned_beds", 0)
    horizon_year = entry.get("horizon_year")
    discount = _time_discount(horizon_year)
    weighted = round(planned_beds * discount)

    return {
        "planned_beds": planned_beds,
        "planned_beds_weighted": weighted,
        "horizon_year": horizon_year,
        "p3_deal": entry.get("p3_deal", False),
        "p3_partner": entry.get("p3_partner"),
        "source": entry.get("source", ""),
        "confidence": entry.get("confidence", "medium"),
        "notes": entry.get("notes"),
    }
