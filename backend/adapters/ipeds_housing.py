"""IPEDS Institutional Characteristics — on-campus housing capacity + cost.

Provides three new signals per university:
  - dormitory_capacity   number of beds in on-campus residence halls
  - typical_room_charge  annual room cost ($)
  - typical_board_charge annual board (meal plan) cost ($)

Beds-per-student is the most defensible "is this campus undersupplied"
signal we can build, and the Project Summary doc names it explicitly
("beds per student deficit") but no existing adapter computes it.

Endpoint: educationdata.urban.org/api/v1/college-university/ipeds/
          institutional-characteristics/{year}/?unitid={id}
No authentication required.
"""

from __future__ import annotations

import asyncio

import httpx

from backend.models.schemas import HousingCapacity

URBAN_BASE = "https://educationdata.urban.org/api/v1"

# Try most-recent year first; fall back if data not yet released for that year.
CANDIDATE_YEARS = [2023, 2022, 2021, 2020]


def _to_int_or_none(v) -> int | None:
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return n


async def fetch_housing_capacity(unitid: int) -> HousingCapacity | None:
    """Fetch dorm capacity + room/board cost. Returns None if no data found."""

    async def fetch_year(client: httpx.AsyncClient, year: int) -> HousingCapacity | None:
        url = (
            f"{URBAN_BASE}/college-university/ipeds/"
            f"institutional-characteristics/{year}/?unitid={unitid}"
        )
        try:
            r = await client.get(url, timeout=15)
            if r.status_code != 200:
                return None
            results = r.json().get("results", [])
            if not results:
                return None
            row = results[0]
            cap = _to_int_or_none(row.get("dormitory_capacity"))
            if cap is None or cap == 0:
                return None
            return HousingCapacity(
                year=year,
                dormitory_capacity=cap,
                typical_room_charge=_to_int_or_none(row.get("typical_room_charge")),
                typical_board_charge=_to_int_or_none(row.get("typical_board_charge")),
            )
        except httpx.HTTPError:
            return None

    async with httpx.AsyncClient() as client:
        for year in CANDIDATE_YEARS:
            result = await fetch_year(client, year)
            if result:
                return result
    return None


def beds_per_student(capacity: HousingCapacity | None, enrollment: int | None) -> float | None:
    """Compute beds-per-student ratio. Returns None if either input is missing."""
    if not capacity or not enrollment or enrollment <= 0:
        return None
    return round(capacity.dormitory_capacity / enrollment, 3)
