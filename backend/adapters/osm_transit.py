"""OpenStreetMap Overpass API — public bus stop coordinates around a campus.

Fetches every node tagged ``highway=bus_stop`` within a radius of a lat/lon,
plus the major rail/transit station tags that students actually use. Powers
the Transit Access layer of the city-level hex grid.

No API key, no auth — Overpass is run on public donated infrastructure, so
calls are best-effort. We:

  • cache results in-memory keyed by (rounded lat, rounded lon, radius_mi)
    so a popular campus is queried at most once per process lifetime;
  • set a tight 8 s timeout and degrade to ``[]`` on any failure (network,
    HTTP, JSON), letting the rest of the hex pipeline run unaffected;
  • try the canonical endpoint first, then a faster mirror.

Endpoint:  https://overpass-api.de/api/interpreter
Mirror:    https://overpass.kumi.systems/api/interpreter
Docs:      https://wiki.openstreetmap.org/wiki/Overpass_API
"""

from __future__ import annotations

import httpx

# Public Overpass instances. The kumi.systems mirror has consistently been
# 5–10x faster than the canonical endpoint in our testing (e.g. 2s vs 8s+
# timeout for a Blacksburg, VA query), so we hit it first and only fall
# back to overpass-api.de if kumi is unreachable.
_ENDPOINTS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)

# In-memory cache: (round(lat,4), round(lon,4), radius_mi) -> list[(lat, lon)]
_CACHE: dict[tuple[float, float, float], list[tuple[float, float]]] = {}


def _build_query(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL query that pulls every public transit boarding node nearby.

    Tag list intentionally wider than the obvious ``highway=bus_stop``: many
    college-town transit agencies tag stops as ``public_transport=platform``
    or ``stop_position`` instead, and Blacksburg Transit (Virginia Tech) is a
    notable example where most stops are tagged ``public_transport=platform``
    with no ``highway=bus_stop`` companion. Also includes ``amenity=bus_station``
    for hub-style park-and-ride lots and the ``ferry_terminal`` for coastal
    campuses (e.g. UW Tacoma, NYU shuttle dock).
    """
    return f"""
    [out:json][timeout:10];
    (
      node["highway"="bus_stop"](around:{radius_m},{lat},{lon});
      node["public_transport"="platform"](around:{radius_m},{lat},{lon});
      node["public_transport"="stop_position"](around:{radius_m},{lat},{lon});
      node["public_transport"="station"](around:{radius_m},{lat},{lon});
      node["amenity"="bus_station"](around:{radius_m},{lat},{lon});
      node["railway"="tram_stop"](around:{radius_m},{lat},{lon});
      node["railway"="station"](around:{radius_m},{lat},{lon});
      node["railway"="halt"](around:{radius_m},{lat},{lon});
      node["amenity"="ferry_terminal"](around:{radius_m},{lat},{lon});
    );
    out body;
    """.strip()


async def fetch_bus_stops(
    lat: float,
    lon: float,
    radius_miles: float = 1.5,
) -> list[tuple[float, float]]:
    """Return ``[(stop_lat, stop_lon), ...]`` for every transit stop in range.

    Always returns a list — never raises. Empty list means either no stops
    in the area, or Overpass was unreachable. Callers should treat the two
    cases identically and just skip the transit-pressure boost.
    """
    cache_key = (round(lat, 4), round(lon, 4), round(radius_miles, 2))
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    radius_m = int(radius_miles * 1609.34)
    query = _build_query(lat, lon, radius_m)

    from backend.adapters.osm_buildings import _overpass_query
    payload = await _overpass_query(query, "OSM-transit")
    if payload is None:
        _CACHE[cache_key] = []
        return []

    elements = payload.get("elements", [])
    stops: list[tuple[float, float]] = []
    for el in elements:
        slat = el.get("lat")
        slon = el.get("lon")
        if slat is None or slon is None:
            continue
        stops.append((float(slat), float(slon)))

    _CACHE[cache_key] = stops
    return stops
