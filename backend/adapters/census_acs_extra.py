"""Census ACS 5-Year — extra demographic + housing fields beyond unit count.

Pulls a batch of ACS variables in a single call so the score endpoint gets
six new signals for the price of one HTTP request.

Variables (ACS 2023 5-year):
  B25002_001E  total housing units
  B25002_003E  vacant housing units
  B19013_001E  median household income (dollars)
  B15003_022E  pop 25+ with bachelor's degree
  B15003_001E  pop 25+ total (denominator for % bachelor's+)
  B25077_001E  median home value (dollars)
  B25064_001E  median gross rent (dollars/month)
  B25008_001E  total occupied housing units
  B25008_003E  renter-occupied housing units
  B25035_001E  median year structure built

Granularity: county. Same key as `census_acs.py`.
Docs: https://api.census.gov/data/2023/acs/acs5/variables.html
"""

from __future__ import annotations

import httpx

from backend.config import config
from backend.models.schemas import MarketDemographics

ACS_BASE = "https://api.census.gov/data/2023/acs/acs5"

VARIABLES = [
    "B25002_001E",  # total housing units
    "B25002_003E",  # vacant
    "B19013_001E",  # median household income
    "B15003_022E",  # pop 25+ with bachelor's
    "B15003_001E",  # pop 25+ total
    "B25077_001E",  # median home value
    "B25064_001E",  # median gross rent
    "B25008_001E",  # total occupied
    "B25008_003E",  # renter-occupied
    "B25035_001E",  # median year built
]


def _to_int(v) -> int | None:
    """ACS sentinel values for missing: -666666666, -888888888, etc."""
    if v is None or v == "":
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    if n < -1000:
        return None
    return n


async def fetch_county_demographics(
    state_fips: str,
    county_fips: str,
) -> MarketDemographics | None:
    """Fetch a batch of ACS variables for one county. Returns None on failure."""
    if not state_fips or not county_fips:
        return None

    params: dict[str, str] = {
        "get": ",".join(VARIABLES),
        "for": f"county:{county_fips}",
        "in": f"state:{state_fips}",
    }
    if config.census_api_key:
        params["key"] = config.census_api_key

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(ACS_BASE, params=params)
            if resp.status_code != 200:
                print(f"[ACS extra] HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            rows = resp.json()
        except httpx.HTTPError as e:
            print(f"[ACS extra] error: {e}")
            return None

    if len(rows) < 2:
        return None

    header = rows[0]
    values = rows[1]
    record = dict(zip(header, values))

    total_units = _to_int(record.get("B25002_001E"))
    vacant = _to_int(record.get("B25002_003E"))
    bachelors = _to_int(record.get("B15003_022E"))
    edu_total = _to_int(record.get("B15003_001E"))
    occupied = _to_int(record.get("B25008_001E"))
    renter_occupied = _to_int(record.get("B25008_003E"))

    vacancy_rate = (
        round(vacant / total_units * 100, 2)
        if total_units and vacant is not None and total_units > 0
        else None
    )
    pct_bachelors = (
        round(bachelors / edu_total * 100, 2)
        if edu_total and bachelors is not None and edu_total > 0
        else None
    )
    pct_renter = (
        round(renter_occupied / occupied * 100, 2)
        if occupied and renter_occupied is not None and occupied > 0
        else None
    )

    return MarketDemographics(
        median_household_income=_to_int(record.get("B19013_001E")),
        median_home_value=_to_int(record.get("B25077_001E")),
        median_gross_rent=_to_int(record.get("B25064_001E")),
        median_year_built=_to_int(record.get("B25035_001E")),
        vacancy_rate_pct=vacancy_rate,
        pct_bachelors_or_higher=pct_bachelors,
        pct_renter_occupied=pct_renter,
        total_housing_units=total_units,
    )
