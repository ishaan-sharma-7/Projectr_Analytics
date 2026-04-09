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
# In-memory cache: (round(lat,4), round(lon,4), radius_mi) -> [(lat, lon, kind)]
# kind = "dormitory" | "campus"
_CAMPUS_CACHE: dict[tuple[float, float, float], list[tuple[float, float, str]]] = {}
# In-memory cache: (round(lat,4), round(lon,4), radius_mi) -> [(lat, lon, building)]
# building = apartments|dormitory|residential|house
_RESIDENTIAL_MARKER_CACHE: dict[tuple[float, float, float], list[tuple[float, float, str]]] = {}
# In-memory cache: (round(lat,4), round(lon,4), radius_mi) -> [(lat, lon, kind)]
# kind = water|protected|recreation|infrastructure|restricted
_NON_BUILDABLE_CACHE: dict[tuple[float, float, float], list[tuple[float, float, str]]] = {}
# In-memory cache: (round(lat,4), round(lon,4), radius_mi) -> [(lat, lon, kind)]
# kind = structure|minor
_DEVELOPMENT_CACHE: dict[tuple[float, float, float], list[tuple[float, float, str]]] = {}
# In-memory cache: (round(lat,4), round(lon,4), radius_mi) -> [(lat, lon, kind)]
# kind = commercial
_COMMERCIAL_CACHE: dict[tuple[float, float, float], list[tuple[float, float, str]]] = {}
# In-memory cache: (round(lat,4), round(lon,4), radius_mi) -> [(lat, lon, kind)]
# kind = parking
_PARKING_CACHE: dict[tuple[float, float, float], list[tuple[float, float, str]]] = {}


def _add_geom_sampled_markers(
    el: dict,
    kind: str,
    markers: list[tuple[float, float, str]],
    seen: set[tuple[float, float, str]],
    max_points: int = 24,
) -> None:
    """Append center + sampled geometry points for robust per-hex evidence."""
    center = el.get("center", {})
    mlat = el.get("lat", center.get("lat"))
    mlon = el.get("lon", center.get("lon"))

    def _add(plat: float, plon: float) -> None:
        key = (round(plat, 5), round(plon, 5), kind)
        if key in seen:
            return
        seen.add(key)
        markers.append((float(plat), float(plon), kind))

    if mlat is not None and mlon is not None:
        _add(float(mlat), float(mlon))

    geom = el.get("geometry")
    if isinstance(geom, list) and geom:
        stride = max(1, len(geom) // max_points)
        for pt in geom[::stride]:
            glat = pt.get("lat")
            glon = pt.get("lon")
            if glat is None or glon is None:
                continue
            _add(float(glat), float(glon))
        lats = [float(pt["lat"]) for pt in geom if "lat" in pt]
        lons = [float(pt["lon"]) for pt in geom if "lon" in pt]
        if lats and lons:
            _add(sum(lats) / len(lats), sum(lons) / len(lons))


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


def _build_campus_query(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL query for campus-controlled land markers near a university.

    We intentionally cast a wider net than dormitories alone:
      - ``building=dormitory`` captures on-campus bed supply;
      - ``building=college|university``, ``amenity=university``, and
        ``landuse=education`` capture academic-core footprints that are
        generally not available to private off-campus developers.
    """
    return f"""
    [out:json][timeout:25];
    (
      way["building"="dormitory"](around:{radius_m},{lat},{lon});
      way["building"="college"](around:{radius_m},{lat},{lon});
      way["building"="university"](around:{radius_m},{lat},{lon});
      way["amenity"="university"](around:{radius_m},{lat},{lon});
      way["landuse"="education"](around:{radius_m},{lat},{lon});
      relation["amenity"="university"](around:{radius_m},{lat},{lon});
      relation["landuse"="education"](around:{radius_m},{lat},{lon});
      node["amenity"="university"](around:{radius_m},{lat},{lon});
      node["building"="dormitory"](around:{radius_m},{lat},{lon});
    );
    out body geom;
    """.strip()


def _build_residential_marker_query(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL query for residential building marker geometry samples."""
    return f"""
    [out:json][timeout:25];
    (
      way["building"="apartments"](around:{radius_m},{lat},{lon});
      way["building"="dormitory"](around:{radius_m},{lat},{lon});
      way["building"="residential"](around:{radius_m},{lat},{lon});
      way["building"="house"](around:{radius_m},{lat},{lon});
      relation["building"~"^(apartments|dormitory|residential|house)$"](around:{radius_m},{lat},{lon});
    );
    out body geom;
    """.strip()


def _build_non_buildable_query(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL query for land-use markers that block housing development.

    We target strong negatives first (water/wetlands/reservoirs, protected
    areas, industrial/military/cemetery) and include major infrastructure and
    recreation parcels that often reduce buildable frontage in college cores.
    """
    return f"""
    [out:json][timeout:25];
    (
      way["natural"~"^(water|wetland)$"](around:{radius_m},{lat},{lon});
      node["natural"~"^(water|wetland)$"](around:{radius_m},{lat},{lon});
      way["natural"="wood"](around:{radius_m},{lat},{lon});
      node["natural"="wood"](around:{radius_m},{lat},{lon});
      way["waterway"~"^(riverbank|dock|canal)$"](around:{radius_m},{lat},{lon});
      node["waterway"~"^(riverbank|dock|canal)$"](around:{radius_m},{lat},{lon});
      way["landuse"~"^(reservoir|basin)$"](around:{radius_m},{lat},{lon});
      node["landuse"~"^(reservoir|basin)$"](around:{radius_m},{lat},{lon});
      way["landuse"~"^(forest|grass|meadow|recreation_ground)$"](around:{radius_m},{lat},{lon});
      node["landuse"~"^(forest|grass|meadow|recreation_ground)$"](around:{radius_m},{lat},{lon});
      relation["natural"~"^(water|wetland)$"](around:{radius_m},{lat},{lon});
      relation["natural"="wood"](around:{radius_m},{lat},{lon});
      relation["landuse"~"^(reservoir|basin)$"](around:{radius_m},{lat},{lon});
      relation["landuse"~"^(forest|grass|meadow|recreation_ground)$"](around:{radius_m},{lat},{lon});

      way["boundary"="protected_area"](around:{radius_m},{lat},{lon});
      relation["boundary"="protected_area"](around:{radius_m},{lat},{lon});
      way["landuse"~"^(forest|conservation)$"](around:{radius_m},{lat},{lon});
      node["landuse"~"^(forest|conservation)$"](around:{radius_m},{lat},{lon});
      way["leisure"="nature_reserve"](around:{radius_m},{lat},{lon});
      node["leisure"="nature_reserve"](around:{radius_m},{lat},{lon});

      way["landuse"~"^(cemetery|military|industrial|quarry|landfill)$"](around:{radius_m},{lat},{lon});
      node["landuse"~"^(cemetery|military|industrial|quarry|landfill)$"](around:{radius_m},{lat},{lon});
      relation["landuse"~"^(cemetery|military|industrial|quarry|landfill)$"](around:{radius_m},{lat},{lon});

      way["aeroway"](around:{radius_m},{lat},{lon});
      node["aeroway"](around:{radius_m},{lat},{lon});
      way["railway"~"^(yard|station|platform)$"](around:{radius_m},{lat},{lon});

      way["leisure"~"^(park|golf_course|pitch|stadium|track|playground)$"](around:{radius_m},{lat},{lon});
      node["leisure"~"^(park|golf_course|pitch|stadium|track|playground)$"](around:{radius_m},{lat},{lon});
      relation["leisure"~"^(park|golf_course|pitch|stadium|track|playground)$"](around:{radius_m},{lat},{lon});
    );
    out body geom;
    """.strip()


def _build_development_query(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL query for existing built structures (any building tags)."""
    return f"""
    [out:json][timeout:25];
    (
      way["building"](around:{radius_m},{lat},{lon});
      relation["building"](around:{radius_m},{lat},{lon});
    );
    out body geom;
    """.strip()


def _build_commercial_query(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL query for commercial/store footprints and POIs."""
    return f"""
    [out:json][timeout:25];
    (
      way["building"~"^(commercial|retail|supermarket|warehouse|office|mall)$"](around:{radius_m},{lat},{lon});
      relation["building"~"^(commercial|retail|supermarket|warehouse|office|mall)$"](around:{radius_m},{lat},{lon});
      way["shop"](around:{radius_m},{lat},{lon});
      relation["shop"](around:{radius_m},{lat},{lon});
      node["shop"](around:{radius_m},{lat},{lon});
      way["amenity"~"^(marketplace|restaurant|cafe|fast_food|bank)$"](around:{radius_m},{lat},{lon});
      relation["amenity"~"^(marketplace|restaurant|cafe|fast_food|bank)$"](around:{radius_m},{lat},{lon});
      node["amenity"~"^(marketplace|restaurant|cafe|fast_food|bank)$"](around:{radius_m},{lat},{lon});
    );
    out body geom;
    """.strip()


def _build_parking_query(lat: float, lon: float, radius_m: int) -> str:
    """Overpass QL query for parking/infrastructure footprints."""
    return f"""
    [out:json][timeout:25];
    (
      way["amenity"="parking"](around:{radius_m},{lat},{lon});
      relation["amenity"="parking"](around:{radius_m},{lat},{lon});
      node["amenity"="parking"](around:{radius_m},{lat},{lon});
      way["building"~"^(parking|garage|garages)$"](around:{radius_m},{lat},{lon});
      relation["building"~"^(parking|garage|garages)$"](around:{radius_m},{lat},{lon});
      way["parking"](around:{radius_m},{lat},{lon});
      way["highway"="service"](around:{radius_m},{lat},{lon});
    );
    out body geom;
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


async def fetch_campus_markers(
    lat: float,
    lon: float,
    radius_miles: float = 1.5,
) -> list[tuple[float, float, str]]:
    """Return per-feature campus constraints as ``[(lat, lon, kind), ...]``.

    ``kind`` values:
      - ``"dormitory"`` for explicit dorm footprints;
      - ``"campus"`` for education/university land markers.

    Always returns a list. Empty list means either no markers were found or
    Overpass was unavailable.
    """
    cache_key = (round(lat, 4), round(lon, 4), round(radius_miles, 2))
    if cache_key in _CAMPUS_CACHE:
        return _CAMPUS_CACHE[cache_key]

    radius_m = int(radius_miles * 1609.34)
    query = _build_campus_query(lat, lon, radius_m)

    payload = None
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query})
                if resp.status_code != 200:
                    print(f"[OSM-campus] {endpoint} → HTTP {resp.status_code}")
                    continue
                payload = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[OSM-campus] {endpoint} failed: {exc}")
                continue

    if payload is None:
        _CAMPUS_CACHE[cache_key] = []
        return []

    markers: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, str]] = set()
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        kind = "dormitory" if tags.get("building") == "dormitory" else "campus"
        _add_geom_sampled_markers(el, kind, markers, seen, max_points=28)

    _CAMPUS_CACHE[cache_key] = markers
    return markers


async def fetch_residential_markers(
    lat: float,
    lon: float,
    radius_miles: float = 1.5,
) -> list[tuple[float, float, str]]:
    """Return per-building residential markers as ``[(lat, lon, building), ...]``.

    The returned markers are designed for per-hex mixed-use checks so we can
    distinguish campus-dominated cells from cells that also contain meaningful
    off-campus housing stock.
    """
    cache_key = (round(lat, 4), round(lon, 4), round(radius_miles, 2))
    if cache_key in _RESIDENTIAL_MARKER_CACHE:
        return _RESIDENTIAL_MARKER_CACHE[cache_key]

    radius_m = int(radius_miles * 1609.34)
    query = _build_residential_marker_query(lat, lon, radius_m)

    payload = None
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query})
                if resp.status_code != 200:
                    print(f"[OSM-residential] {endpoint} → HTTP {resp.status_code}")
                    continue
                payload = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[OSM-residential] {endpoint} failed: {exc}")
                continue

    if payload is None:
        _RESIDENTIAL_MARKER_CACHE[cache_key] = []
        return []

    markers: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, str]] = set()
    for el in payload.get("elements", []):
        building = el.get("tags", {}).get("building")
        if building is None:
            continue
        _add_geom_sampled_markers(
            el, str(building), markers, seen, max_points=28
        )

    _RESIDENTIAL_MARKER_CACHE[cache_key] = markers
    return markers


def _classify_non_buildable_kind(tags: dict[str, str]) -> str | None:
    """Map OSM tags to non-buildable kind buckets."""
    natural = tags.get("natural", "")
    waterway = tags.get("waterway", "")
    landuse = tags.get("landuse", "")
    leisure = tags.get("leisure", "")
    boundary = tags.get("boundary", "")
    aeroway = tags.get("aeroway", "")
    railway = tags.get("railway", "")

    if leisure == "golf_course":
        return "golf_course"
    if leisure in {"pitch", "stadium", "track"} or landuse == "recreation_ground":
        return "field"
    if natural == "wetland":
        return "wetland"
    if natural == "water" or waterway in {"riverbank", "dock", "canal"} or landuse in {"reservoir", "basin"}:
        return "water"
    if natural == "wood" or landuse == "forest":
        return "forest"
    if boundary == "protected_area" or landuse in {"forest", "conservation"} or leisure == "nature_reserve":
        return "protected"
    if landuse in {"cemetery", "military", "industrial", "quarry", "landfill"}:
        return "restricted"
    if aeroway or railway in {"yard", "station", "platform"}:
        return "infrastructure"
    if leisure in {"park", "playground"} or landuse in {"grass", "meadow"}:
        return "park"
    return None


async def fetch_non_buildable_markers(
    lat: float,
    lon: float,
    radius_miles: float = 1.5,
) -> list[tuple[float, float, str]]:
    """Return non-buildable land-use markers as ``[(lat, lon, kind), ...]``.

    ``kind`` values:
      - ``water`` (lakes/wetlands/reservoir features)
      - ``wetland`` (explicit wetland polygons)
      - ``golf_course`` (highly constrained recreation parcels)
      - ``field`` (athletic fields, stadium parcels)
      - ``forest`` (wooded parcels)
      - ``park`` (park/greenfield parcels)
      - ``protected`` (protected/conservation land)
      - ``restricted`` (industrial/military/cemetery/etc.)
      - ``infrastructure`` (airport/rail-heavy parcels)
    """
    cache_key = (round(lat, 4), round(lon, 4), round(radius_miles, 2))
    if cache_key in _NON_BUILDABLE_CACHE:
        return _NON_BUILDABLE_CACHE[cache_key]

    radius_m = int(radius_miles * 1609.34)
    query = _build_non_buildable_query(lat, lon, radius_m)

    payload = None
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query})
                if resp.status_code != 200:
                    print(f"[OSM-nonbuildable] {endpoint} → HTTP {resp.status_code}")
                    continue
                payload = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[OSM-nonbuildable] {endpoint} failed: {exc}")
                continue

    if payload is None:
        _NON_BUILDABLE_CACHE[cache_key] = []
        return []

    markers: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, str]] = set()

    def _add_marker(mlat: float, mlon: float, kind: str) -> None:
        # Round for dedupe across overlapping way/relation/node queries.
        key = (round(mlat, 5), round(mlon, 5), kind)
        if key in seen:
            return
        seen.add(key)
        markers.append((float(mlat), float(mlon), kind))

    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        kind = _classify_non_buildable_kind(tags)
        if not kind:
            continue

        center = el.get("center", {})
        mlat = el.get("lat", center.get("lat"))
        mlon = el.get("lon", center.get("lon"))
        if mlat is not None and mlon is not None:
            _add_marker(float(mlat), float(mlon), kind)

        # ``out geom`` gives full way/relation geometry; sample it so large
        # polygons (lakes, golf courses, forests) touch multiple hex cells.
        geom = el.get("geometry")
        if isinstance(geom, list) and geom:
            stride = max(1, len(geom) // 48)  # denser sampling for large parcels
            for pt in geom[::stride]:
                glat = pt.get("lat")
                glon = pt.get("lon")
                if glat is None or glon is None:
                    continue
                _add_marker(float(glat), float(glon), kind)
            # Add a centroid marker so interior hexes on large polygons are
            # also tagged (important for lakes/golf courses).
            lats = [float(pt["lat"]) for pt in geom if "lat" in pt]
            lons = [float(pt["lon"]) for pt in geom if "lon" in pt]
            if lats and lons:
                _add_marker(sum(lats) / len(lats), sum(lons) / len(lons), kind)

    _NON_BUILDABLE_CACHE[cache_key] = markers
    return markers


async def fetch_development_markers(
    lat: float,
    lon: float,
    radius_miles: float = 1.5,
) -> list[tuple[float, float, str]]:
    """Return existing structure markers as ``[(lat, lon, kind), ...]``.

    ``kind``:
      - ``structure`` for meaningful built property;
      - ``minor`` for low-signal accessory structures (shed/garage/etc.).
    """
    cache_key = (round(lat, 4), round(lon, 4), round(radius_miles, 2))
    if cache_key in _DEVELOPMENT_CACHE:
        return _DEVELOPMENT_CACHE[cache_key]

    radius_m = int(radius_miles * 1609.34)
    query = _build_development_query(lat, lon, radius_m)

    payload = None
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query})
                if resp.status_code != 200:
                    print(f"[OSM-development] {endpoint} → HTTP {resp.status_code}")
                    continue
                payload = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[OSM-development] {endpoint} failed: {exc}")
                continue

    if payload is None:
        _DEVELOPMENT_CACHE[cache_key] = []
        return []

    minor_buildings = {
        "shed", "garage", "garages", "roof", "carport", "kiosk",
        "hut", "service", "toilets", "bunker",
    }
    markers: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, str]] = set()
    for el in payload.get("elements", []):
        building = str(el.get("tags", {}).get("building", "")).strip().lower()
        kind = "minor" if building in minor_buildings else "structure"
        _add_geom_sampled_markers(el, kind, markers, seen, max_points=20)

    _DEVELOPMENT_CACHE[cache_key] = markers
    return markers


async def fetch_commercial_markers(
    lat: float,
    lon: float,
    radius_miles: float = 1.5,
) -> list[tuple[float, float, str]]:
    """Return commercial/store markers as ``[(lat, lon, "commercial"), ...]``."""
    cache_key = (round(lat, 4), round(lon, 4), round(radius_miles, 2))
    if cache_key in _COMMERCIAL_CACHE:
        return _COMMERCIAL_CACHE[cache_key]

    radius_m = int(radius_miles * 1609.34)
    query = _build_commercial_query(lat, lon, radius_m)

    payload = None
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query})
                if resp.status_code != 200:
                    print(f"[OSM-commercial] {endpoint} → HTTP {resp.status_code}")
                    continue
                payload = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[OSM-commercial] {endpoint} failed: {exc}")
                continue

    if payload is None:
        _COMMERCIAL_CACHE[cache_key] = []
        return []

    markers: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, str]] = set()
    for el in payload.get("elements", []):
        _add_geom_sampled_markers(el, "commercial", markers, seen, max_points=16)

    _COMMERCIAL_CACHE[cache_key] = markers
    return markers


async def fetch_parking_markers(
    lat: float,
    lon: float,
    radius_miles: float = 1.5,
) -> list[tuple[float, float, str]]:
    """Return parking/infrastructure markers as ``[(lat, lon, "parking"), ...]``."""
    cache_key = (round(lat, 4), round(lon, 4), round(radius_miles, 2))
    if cache_key in _PARKING_CACHE:
        return _PARKING_CACHE[cache_key]

    radius_m = int(radius_miles * 1609.34)
    query = _build_parking_query(lat, lon, radius_m)

    payload = None
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS:
            try:
                resp = await client.post(endpoint, data={"data": query})
                if resp.status_code != 200:
                    print(f"[OSM-parking] {endpoint} → HTTP {resp.status_code}")
                    continue
                payload = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[OSM-parking] {endpoint} failed: {exc}")
                continue

    if payload is None:
        _PARKING_CACHE[cache_key] = []
        return []

    markers: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, str]] = set()
    for el in payload.get("elements", []):
        _add_geom_sampled_markers(el, "parking", markers, seen, max_points=18)

    _PARKING_CACHE[cache_key] = markers
    return markers
