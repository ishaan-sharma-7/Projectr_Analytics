"""Occupancy ordinance adapter — city-level rental restriction data.

Some college towns cap the number of unrelated persons who can legally share
a rental unit (the classic "3 unrelated persons" rule). This shapes the
off-campus housing market in two ways:

  1. Strict limits → students can't pack houses cheaply → demand for
     purpose-built student housing (PBSH) is more price-stable and durable.
     This is a POSITIVE signal for PBSH developers.

  2. No limit / permissive → large shared-house market competes directly
     with PBSH on price → negative pressure on PBSH rents and occupancy.

Data is curated in backend/fixtures/occupancy_ordinances.json.
Lookup is by (city, state) normalized to lowercase.
"""

import json
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).parent.parent / "fixtures" / "occupancy_ordinances.json"


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[occupancy_ordinances] Failed to load JSON: {exc}")
        return []


def _normalize(s: str) -> str:
    return s.strip().lower()


def lookup(city: str, state: str) -> dict | None:
    """Return the ordinance entry for a city/state, or None if not in data.

    Matching is case-insensitive. If multiple entries exist for the same city
    (duplicate in fixture), the first non-duplicate is returned.
    """
    target_city = _normalize(city)
    target_state = _normalize(state)
    for entry in _load():
        if (
            _normalize(entry.get("city", "")) == target_city
            and _normalize(entry.get("state", "")) == target_state
        ):
            return entry
    return None


def get_ordinance(city: str, state: str) -> dict | None:
    """Return occupancy ordinance data for a university's city.

    Returns a dict with:
      max_unrelated_occupants  — int or None (None = no cap)
      ordinance_type           — "unrelated-persons" | "nuisance-based" | "none"
      enforced                 — bool
      pbsh_signal              — "positive" | "neutral" | "negative"
      confidence               — "high" | "medium" | "low"
      source                   — citation string
      notes                    — optional detail

    Returns None if the city is not in the dataset.
    """
    entry = lookup(city, state)
    if not entry:
        return None

    max_occ = entry.get("max_unrelated_occupants")
    enforced = entry.get("enforced", False)
    ordinance_type = entry.get("ordinance_type", "none")

    # Determine PBSH signal
    if ordinance_type == "none" or max_occ is None:
        pbsh_signal = "neutral"
    elif not enforced:
        pbsh_signal = "neutral"  # on-books but unenforced = no practical effect
    elif max_occ <= 3:
        pbsh_signal = "positive"   # tight cap → PBSH demand more durable
    elif max_occ <= 4:
        pbsh_signal = "positive"   # moderate restriction still limits cheap house-packing
    else:
        pbsh_signal = "neutral"

    return {
        "city": entry.get("city"),
        "state": entry.get("state"),
        "max_unrelated_occupants": max_occ,
        "ordinance_type": ordinance_type,
        "enforced": enforced,
        "pbsh_signal": pbsh_signal,
        "confidence": entry.get("confidence", "low"),
        "source": entry.get("source", ""),
        "notes": entry.get("notes"),
    }
