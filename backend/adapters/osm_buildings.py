"""OSM Overpass — existing residential building footprint near campus.

Counts buildings tagged ``building=apartments|dormitory|residential|house``
within a radius of campus. Powers the "Existing Housing Stock" signal in
the score panel — a market that already has 400+ apartment buildings packed
around the school has far less headroom for new PBSH than one with 30, even
if the underlying enrollment pressure is identical.

Same Overpass infrastructure as ``osm_transit.py``: in-memory cache keyed by
(rounded lat, rounded lon, radius), tries the kumi.systems mirror first,
graceful degradation to ``None`` on any failure.

Endpoint:  https://overpass.kumi.systems/api/interpreter
Mirror:    https://overpass-api.de/api/interpreter
"""

from __future__ import annotations

import math
from collections import Counter

import httpx

from backend.models.schemas import ExistingHousingStock

_ENDPOINTS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)

# In-memory cache: (round(lat,4), round(lon,4), radius_mi) -> ExistingHousingStock
_CACHE: dict[tuple[float, float, float], ExistingHousingStock] = {}


def _build_query(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL query that pulls every residential building footprint nearby.

    We query ``way`` (most building footprints in OSM are ways, not nodes or
    relations) and ask for ``out center`` so we get a cheap centroid for
    each footprint without paying for the full geometry. Centroids could be
    bucketed into the H3 hex grid in a follow-up.
    """
    return f"""
    [out:json][timeout:25];
    (
      way["building"="apartments"](around:{radius_m},{lat},{lon});
      way["building"="dormitory"](around:{radius_m},{lat},{lon});
      way["building"="residential"](around:{radius_m},{lat},{lon});
      way["building"="house"](around:{radius_m},{lat},{lon});
    );
    out center;
    """.strip()


def _saturation_label(pbsh_density: float) -> str:
    """Bucket PBSH-competing density (apartments + dormitories) per km².

    Calibrated against real OSM data for typical college towns:
      VTech (Blacksburg, VA):   21/km² → moderate
      Penn State (State College): 17/km² → moderate
      UVA (Charlottesville):    19/km² → moderate

    Thresholds:
      <12/km²   → low      (genuine headroom for new build)
      12–25/km² → moderate (typical college market)
      ≥25/km²   → high     (saturated — Boston, NYU, Berkeley, etc.)
    """
    if pbsh_density >= 25:
        return "high"
    if pbsh_density >= 12:
        return "moderate"
    return "low"


async def fetch_buildings(
    lat: float,
    lon: float,
    radius_miles: float = 1.5,
) -> ExistingHousingStock | None:
    """Return existing housing footprint counts within ``radius_miles`` of campus.

    Returns ``None`` (not an empty record) when the Overpass query fails so
    callers can distinguish "no data" from "really zero buildings". A real
    campus will essentially never have zero — even rural ones have houses.
    """
    cache_key = (round(lat, 4), round(lon, 4), round(radius_miles, 2))
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    radius_m = int(radius_miles * 1609.34)
    query = _build_query(lat, lon, radius_m)

    payload = None
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query})
                if resp.status_code != 200:
                    print(f"[OSM-buildings] {endpoint} → HTTP {resp.status_code}")
                    continue
                payload = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[OSM-buildings] {endpoint} failed: {exc}")
                continue

    if payload is None:
        return None

    elements = payload.get("elements", [])
    type_counts: Counter[str] = Counter()
    for el in elements:
        building_type = el.get("tags", {}).get("building")
        if building_type:
            type_counts[building_type] += 1

    # Area of the search disk in km² for density calc
    radius_km = radius_miles * 1.60934
    area_km2 = math.pi * radius_km * radius_km

    apartment_count = type_counts["apartments"]
    dormitory_count = type_counts["dormitory"]
    # PBSH-competing density = apartments + dorms per km². Houses are noisy
    # SFR shadow supply that doesn't gate new ground-up apartment projects.
    pbsh_density = round((apartment_count + dormitory_count) / area_km2, 2) if area_km2 > 0 else 0.0

    stock = ExistingHousingStock(
        radius_miles=radius_miles,
        apartment_buildings=apartment_count,
        dormitory_buildings=dormitory_count,
        residential_buildings=type_counts["residential"],
        house_buildings=type_counts["house"],
        total_buildings=sum(type_counts.values()),
        apartment_density_per_km2=pbsh_density,
        saturation_label=_saturation_label(pbsh_density),
    )

    _CACHE[cache_key] = stock
    return stock
