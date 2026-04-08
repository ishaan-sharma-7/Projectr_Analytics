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

# Public Overpass instances — try canonical first, then a known fast mirror.
_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

# In-memory cache: (round(lat,4), round(lon,4), radius_mi) -> list[(lat, lon)]
_CACHE: dict[tuple[float, float, float], list[tuple[float, float]]] = {}


def _build_query(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL query that pulls every public transit boarding node nearby.

    We include:
      highway=bus_stop          ordinary bus stops
      public_transit=platform   bus / shuttle / light-rail platforms
      railway=tram_stop         tram / streetcar stops
      railway=station           commuter rail / subway entrances
    """
    return f"""
    [out:json][timeout:8];
    (
      node["highway"="bus_stop"](around:{radius_m},{lat},{lon});
      node["public_transport"="platform"](around:{radius_m},{lat},{lon});
      node["railway"="tram_stop"](around:{radius_m},{lat},{lon});
      node["railway"="station"](around:{radius_m},{lat},{lon});
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

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query})
                if resp.status_code != 200:
                    print(f"[Overpass] {endpoint} → HTTP {resp.status_code}")
                    continue
                payload = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[Overpass] {endpoint} failed: {exc}")
                continue
        else:
            # All endpoints failed
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
