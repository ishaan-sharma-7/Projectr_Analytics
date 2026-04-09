"""Short-term rental (STR) shadow supply adapter.

High Airbnb/VRBO concentration near campus removes units from the long-term
rental pool that students would otherwise occupy. This tightens the effective
supply of student-suitable housing and increases PBSH demand durability.

Scoring signal:
  very_high (>5% of units): major supply compression → positive PBSH signal
  high      (2–5%):          meaningful compression → moderate positive
  moderate  (0.5–2%):        minor effect → neutral
  low       (<0.5%):         seasonal/game-day only → neutral

Data is curated in backend/fixtures/str_markets.json based on InsideAirbnb
public datasets and market research. City-level estimates; confidence varies.
"""

import json
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).parent.parent / "fixtures" / "str_markets.json"


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[str_markets] Failed to load JSON: {exc}")
        return []


def _normalize(s: str) -> str:
    return s.strip().lower()


def lookup(city: str, state: str) -> dict | None:
    """Return the STR market entry for a city/state, or None if not in data."""
    target_city = _normalize(city)
    target_state = _normalize(state)
    for entry in _load():
        if (
            _normalize(entry.get("city", "")) == target_city
            and _normalize(entry.get("state", "")) == target_state
        ):
            return entry
    return None


def get_str_market(city: str, state: str) -> dict | None:
    """Return STR market data for a university's city.

    Returns a dict with:
      str_intensity         — "very_high" | "high" | "moderate" | "low"
      estimated_str_pct     — float, estimated % of housing units on STR platforms
      pbsh_signal           — "positive" | "neutral"
      score_multiplier      — float, multiplier for the pressure score
      confidence            — "high" | "medium" | "low"
      source                — citation string
      notes                 — optional detail

    Returns None if the city is not in the dataset.
    """
    entry = lookup(city, state)
    if not entry:
        return None

    intensity = entry.get("str_intensity", "low")
    str_pct = entry.get("estimated_str_pct_of_units", 0.0)

    if intensity == "very_high":
        pbsh_signal = "positive"
        score_multiplier = 1.07
    elif intensity == "high":
        pbsh_signal = "positive"
        score_multiplier = 1.04
    elif intensity == "moderate":
        pbsh_signal = "neutral"
        score_multiplier = 1.0
    else:  # low
        pbsh_signal = "neutral"
        score_multiplier = 1.0

    return {
        "city": entry.get("city"),
        "state": entry.get("state"),
        "str_intensity": intensity,
        "estimated_str_pct": str_pct,
        "pbsh_signal": pbsh_signal,
        "score_multiplier": score_multiplier,
        "confidence": entry.get("confidence", "low"),
        "source": entry.get("source", ""),
        "notes": entry.get("notes"),
    }
