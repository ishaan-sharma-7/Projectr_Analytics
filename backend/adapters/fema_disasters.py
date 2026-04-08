"""OpenFEMA disaster declarations — federally declared disasters per county.

Provides a 10-year disaster history per county as a "climate / hazard
exposure" signal. Acts as the disaster-risk dimension of the score.

Endpoint: https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries
No authentication required. OData filter syntax.

We compute:
  total_disasters_10yr   raw count over the last 10 years
  weather_disasters_10yr count excluding biological / man-made
  by_type                {incident_type: count}
  most_recent_year       most recent declaration year (or None)
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import httpx

from backend.models.schemas import DisasterRisk

OPENFEMA_BASE = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"

# Incident types we count as "weather/climate" for the focused signal
WEATHER_TYPES = {
    "Hurricane", "Tropical Storm", "Severe Storm", "Severe Ice Storm",
    "Winter Storm", "Snowstorm", "Tornado", "Flood", "Coastal Storm",
    "Fire", "Drought", "Mud/Landslide", "Typhoon", "Earthquake",
    "Tsunami", "Volcano", "Freezing",
}


async def fetch_disaster_history(
    state_fips: str,
    county_fips: str,
    years: int = 10,
) -> DisasterRisk | None:
    """Fetch federal disaster declarations for a county over the last N years."""
    if not state_fips or not county_fips:
        return None

    # OpenFEMA uses non-zero-padded county codes within the filter
    state = state_fips.lstrip("0") or "0"
    county = county_fips.lstrip("0") or "0"

    cutoff_year = datetime.now(timezone.utc).year - years
    cutoff_iso = f"{cutoff_year}-01-01T00:00:00.000Z"

    params = {
        "$filter": (
            f"fipsStateCode eq '{state.zfill(2)}' "
            f"and fipsCountyCode eq '{county.zfill(3)}' "
            f"and declarationDate ge '{cutoff_iso}'"
        ),
        "$select": "disasterNumber,declarationDate,incidentType",
        "$top": "1000",
        "$orderby": "declarationDate desc",
    }

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        try:
            r = await client.get(OPENFEMA_BASE, params=params)
            if r.status_code != 200:
                print(f"[OpenFEMA] HTTP {r.status_code}")
                return None
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            print(f"[OpenFEMA] error: {e}")
            return None

    declarations = data.get("DisasterDeclarationsSummaries", [])
    if not declarations:
        return DisasterRisk(
            window_years=years,
            total_disasters=0,
            weather_disasters=0,
            by_type={},
            most_recent_year=None,
        )

    # Distinct disaster numbers — same disaster can be re-declared
    seen_disaster_ids: set[int] = set()
    distinct_rows: list[dict] = []
    for row in declarations:
        did = row.get("disasterNumber")
        if did is None or did in seen_disaster_ids:
            continue
        seen_disaster_ids.add(did)
        distinct_rows.append(row)

    type_counts = Counter(r.get("incidentType", "Unknown") for r in distinct_rows)
    weather_count = sum(c for t, c in type_counts.items() if t in WEATHER_TYPES)

    most_recent_year: int | None = None
    if distinct_rows:
        try:
            most_recent_year = int(distinct_rows[0]["declarationDate"][:4])
        except (KeyError, ValueError):
            pass

    return DisasterRisk(
        window_years=years,
        total_disasters=len(distinct_rows),
        weather_disasters=weather_count,
        by_type=dict(type_counts),
        most_recent_year=most_recent_year,
    )
