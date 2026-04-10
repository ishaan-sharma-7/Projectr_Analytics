"""Zoning GIS endpoint discovery script.

For each of the 19 remaining pipeline schools (VTech already done), tries to
find a working ArcGIS zoning feature service by:

  1. ArcGIS Hub dataset search API — broadest coverage, searches all public
     hosted layers tagged/titled with "zoning" for a given city+state.
  2. Common direct-server URL patterns (city GIS servers follow predictable
     paths like gis.{city}.gov/arcgis/...).

For every candidate URL found, fires a small bbox query around the campus
centroid. A hit is confirmed when:
  - The response returns >= 1 polygon feature, AND
  - There's at least one string field that looks like a zone code/district.

Output: backend/cache/zoning_discovery.json — one entry per school with:
  status        "found" | "not_found" | "error"
  url           confirmed ArcGIS query URL (if found)
  zone_field    field name holding zone codes
  sample_codes  list of distinct zone values seen in bbox query
  source        "hub_search" | "direct_url"
  notes         any error / debug info

Run from project root:
    python -m backend.scripts.discover_zoning_gis
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

import httpx

# ── School registry: name → (campus_lat, campus_lng, city, state) ─────────────
# VTech is excluded (already configured).
SCHOOLS: list[tuple[str, float, float, str, str]] = [
    ("University of Virginia",               38.0336, -78.5080, "Charlottesville", "VA"),
    ("University of Tennessee Knoxville",    35.9544, -83.9235, "Knoxville",       "TN"),
    ("University of North Carolina Chapel Hill", 35.9049, -79.0469, "Chapel Hill", "NC"),
    ("University of Florida",                29.6436, -82.3549, "Gainesville",     "FL"),
    ("Arizona State University",             33.4242, -111.9281,"Tempe",           "AZ"),
    ("University of Georgia",                33.9480, -83.3774, "Athens",          "GA"),
    ("Clemson University",                   34.6834, -82.8374, "Clemson",         "SC"),
    ("North Carolina State University",      35.7872, -78.6672, "Raleigh",         "NC"),
    ("Boise State University",               43.6037, -116.2003,"Boise",           "ID"),
    ("University of Alabama",                33.2119, -87.5436, "Tuscaloosa",      "AL"),
    ("University of South Carolina",         33.9963, -81.0319, "Columbia",        "SC"),
    ("Ohio State University",                40.0076, -83.0300, "Columbus",        "OH"),
    ("Michigan State University",            42.7251, -84.4791, "East Lansing",    "MI"),
    ("Texas A&M University",                 30.6187, -96.3365, "College Station", "TX"),
    ("Pennsylvania State University",        40.7982, -77.8600, "State College",   "PA"),
    ("Indiana University Bloomington",       39.1682, -86.5230, "Bloomington",     "IN"),
    ("University of Kentucky",               38.0308, -84.5037, "Lexington",       "KY"),
    ("Mississippi State University",         33.4560, -88.7887, "Starkville",      "MS"),
    ("University of Nevada Las Vegas",       36.1070, -115.1391,"Las Vegas",       "NV"),
]

# ── Common direct-server URL patterns per city ─────────────────────────────────
# {city_slug} = city name lowercased, spaces removed
# {state_abbr} = state abbreviation lowercased
DIRECT_URL_TEMPLATES = [
    "https://gis.{city_slug}.gov/arcgis/rest/services",
    "https://maps.{city_slug}.gov/arcgis/rest/services",
    "https://{city_slug}maps.{city_slug}.gov/arcgis/rest/services",
    "https://gis.{city_slug}{state_abbr}.gov/arcgis/rest/services",
    "https://geodata.{city_slug}.gov/arcgis/rest/services",
    "https://gis.{county_guess}county.gov/arcgis/rest/services",
]

# Per-city overrides for counties (used in direct URL guessing)
COUNTY_OVERRIDES: dict[str, str] = {
    "Charlottesville": "albemarle",
    "Chapel Hill":     "orange",
    "Knoxville":       "knox",
    "Gainesville":     "alachua",
    "Tempe":           "maricopa",
    "Athens":          "clarke",
    "Clemson":         "pickens",
    "Raleigh":         "wake",
    "Boise":           "ada",
    "Tuscaloosa":      "tuscaloosa",
    "Columbia":        "richland",
    "Columbus":        "franklin",
    "East Lansing":    "ingham",
    "College Station": "brazos",
    "State College":   "centre",
    "Bloomington":     "monroe",
    "Lexington":       "fayette",
    "Starkville":      "oktibbeha",
    "Las Vegas":       "clark",
}

# ArcGIS Hub search endpoint
HUB_SEARCH = "https://hub.arcgis.com/api/v3/datasets"

# Known promising direct endpoints to try for specific cities
# (from prior knowledge / common ArcGIS deployments)
KNOWN_ENDPOINTS: dict[str, list[str]] = {
    "Gainesville": [
        "https://maps.cityofgainesville.org/arcgis/rest/services/Planning/Zoning/MapServer/0/query",
        "https://services.arcgis.com/LBbVDC0hKPAnLRpO/arcgis/rest/services/City_of_Gainesville_Zoning/FeatureServer/0/query",
    ],
    "Raleigh": [
        "https://services.arcgis.com/v400IkDOw1ad7Yad/arcgis/rest/services/Zoning/FeatureServer/0/query",
        "https://maps.raleighnc.gov/arcgis/rest/services/Planning/PlanningGIS/MapServer/22/query",
    ],
    "Columbus": [
        "https://maps.columbus.gov/arcgis/rest/services/Zoning/MapServer/0/query",
        "https://services6.arcgis.com/clPWQMwZfdWn4MQZ/arcgis/rest/services/Zoning/FeatureServer/0/query",
    ],
    "Boise": [
        "https://gis.cityofboise.org/arcgis/rest/services/Planning/Zoning/MapServer/0/query",
        "https://services.arcgis.com/quVBpCKO8I6O2C9R/arcgis/rest/services/Zoning/FeatureServer/0/query",
    ],
    "Tempe": [
        "https://maps.tempe.gov/arcgis/rest/services/Planning/Zoning/MapServer/0/query",
        "https://services.arcgis.com/d3d3d3d3/arcgis/rest/services/Tempe_Zoning/FeatureServer/0/query",
    ],
    "Lexington": [
        "https://maps.lexingtonky.gov/arcgis/rest/services/Planning/Zoning/MapServer/0/query",
    ],
    "Knoxville": [
        "https://gis.knoxplanning.org/arcgis/rest/services/Zoning/MapServer/0/query",
    ],
    "Las Vegas": [
        "https://gis.clarkcountynv.gov/arcgis/rest/services/Zoning/MapServer/0/query",
        "https://maps.lasvegasnevada.gov/arcgis/rest/services/Planning/Zoning/MapServer/0/query",
    ],
}

OUTPUT_PATH = Path(__file__).parent.parent / "cache" / "zoning_discovery.json"


def _bbox(lat: float, lng: float, radius_miles: float = 1.5) -> str:
    dlat = radius_miles / 69.0
    dlng = radius_miles / max(1e-6, 69.172 * abs(math.cos(math.radians(lat))))
    return f"{lng-dlng},{lat-dlat},{lng+dlng},{lat+dlat}"


def _looks_like_zone_field(name: str) -> bool:
    """Heuristic: does this field name suggest it holds zone codes/names?"""
    low = name.lower()
    keywords = {"zone", "zoning", "district", "classif", "desig", "land_use", "landuse", "lu_"}
    return any(k in low for k in keywords)


async def _query_candidate(
    client: httpx.AsyncClient,
    url: str,
    lat: float,
    lng: float,
) -> dict | None:
    """Try querying a candidate ArcGIS layer URL. Returns result dict or None."""
    params = {
        "where": "1=1",
        "geometry": _bbox(lat, lng),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "resultRecordCount": "20",
        "f": "json",
    }
    try:
        resp = await client.get(url, params=params, timeout=12.0)
        if resp.status_code != 200:
            return None
        data = resp.json()
        features = data.get("features", [])
        if not features:
            return None

        # Find fields that look like zone designations
        all_fields = set()
        for feat in features:
            all_fields.update(feat.get("attributes", {}).keys())

        zone_candidates = [f for f in all_fields if _looks_like_zone_field(f)]
        if not zone_candidates:
            return None

        # Pick best field and collect sample values
        zone_field = zone_candidates[0]
        sample_codes: list[str] = []
        seen: set[str] = set()
        for feat in features:
            val = str(feat.get("attributes", {}).get(zone_field, "") or "").strip()
            if val and val not in seen:
                seen.add(val)
                sample_codes.append(val)

        return {"zone_field": zone_field, "sample_codes": sample_codes[:12], "feature_count": len(features)}
    except Exception:
        return None


async def _hub_search(
    client: httpx.AsyncClient,
    city: str,
    state: str,
    lat: float,
    lng: float,
) -> dict | None:
    """Search ArcGIS Hub for a zoning layer near city/state. Returns confirmed hit or None."""
    params = {
        "q": f"zoning {city} {state}",
        "fields[datasets]": "name,url,type,access,tags",
        "filter[type]": "Feature Layer",
        "filter[access]": "public",
        "page[size]": "8",
        "sort": "relevance",
    }
    try:
        resp = await client.get(HUB_SEARCH, params=params, timeout=15.0)
        if resp.status_code != 200:
            return None
        results = resp.json().get("data", [])
    except Exception:
        return None

    for item in results:
        attrs = item.get("attributes", {})
        layer_url = attrs.get("url", "")
        name = attrs.get("name", "")
        if not layer_url:
            continue
        # Filter to plausibly-zoning layers
        name_low = name.lower()
        if not any(k in name_low for k in ("zon", "land use", "landuse", "district")):
            continue
        # Convert layer URL to query URL
        if not layer_url.endswith("/query"):
            query_url = layer_url.rstrip("/") + "/query"
        else:
            query_url = layer_url

        result = await _query_candidate(client, query_url, lat, lng)
        if result:
            return {**result, "url": query_url, "layer_name": name, "source": "hub_search"}

    return None


async def _direct_url_search(
    client: httpx.AsyncClient,
    city: str,
    state: str,
    lat: float,
    lng: float,
) -> dict | None:
    """Try known + pattern-based direct ArcGIS server URLs."""
    candidates: list[str] = []

    # Known endpoints first
    candidates.extend(KNOWN_ENDPOINTS.get(city, []))

    # Pattern-based guesses
    city_slug = city.lower().replace(" ", "")
    state_abbr = state.lower()
    county = COUNTY_OVERRIDES.get(city, city_slug)
    for template in DIRECT_URL_TEMPLATES:
        base = template.format(
            city_slug=city_slug,
            state_abbr=state_abbr,
            county_guess=county,
        )
        # Try common zoning sub-paths on each base server
        for sub in [
            "/Planning/Zoning/MapServer/0/query",
            "/Zoning/MapServer/0/query",
            "/Zoning/FeatureServer/0/query",
            "/Planning/MapServer/0/query",
            "/LandUse/MapServer/0/query",
        ]:
            candidates.append(base.replace("/rest/services", "/rest/services") + sub)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    # Test concurrently (cap parallelism to avoid overwhelming servers)
    sem = asyncio.Semaphore(4)

    async def try_one(url: str) -> dict | None:
        async with sem:
            result = await _query_candidate(client, url, lat, lng)
            if result:
                return {**result, "url": url, "source": "direct_url"}
            return None

    tasks = [try_one(u) for u in unique]
    results = await asyncio.gather(*tasks)
    for r in results:
        if r:
            return r
    return None


async def discover_one(
    school_name: str,
    lat: float,
    lng: float,
    city: str,
    state: str,
) -> dict:
    print(f"  [{city}, {state}] searching...", flush=True)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Run Hub search and direct URL search concurrently
        hub_result, direct_result = await asyncio.gather(
            _hub_search(client, city, state, lat, lng),
            _direct_url_search(client, city, state, lat, lng),
        )

    hit = hub_result or direct_result
    if hit:
        print(f"  [{city}] FOUND via {hit['source']}: {hit['url']}")
        print(f"           zone_field={hit['zone_field']}  samples={hit['sample_codes'][:5]}")
        return {
            "school": school_name,
            "city": city,
            "state": state,
            "status": "found",
            "url": hit["url"],
            "zone_field": hit["zone_field"],
            "sample_codes": hit["sample_codes"],
            "source": hit["source"],
            "layer_name": hit.get("layer_name", ""),
        }
    else:
        print(f"  [{city}] not found")
        return {
            "school": school_name,
            "city": city,
            "state": state,
            "status": "not_found",
            "url": None,
            "zone_field": None,
            "sample_codes": [],
            "source": None,
            "layer_name": "",
        }


async def main() -> None:
    print(f"Discovering zoning GIS endpoints for {len(SCHOOLS)} schools...\n")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Run all schools concurrently (each internally limits parallelism)
    results = await asyncio.gather(*[
        discover_one(name, lat, lng, city, state)
        for name, lat, lng, city, state in SCHOOLS
    ])

    found = [r for r in results if r["status"] == "found"]
    not_found = [r for r in results if r["status"] != "found"]

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(found)}/{len(results)} cities have working GIS endpoints\n")

    print("FOUND:")
    for r in found:
        print(f"  {r['city']:20s} {r['zone_field']:20s} {r['sample_codes'][:4]}")

    print("\nNOT FOUND:")
    for r in not_found:
        print(f"  {r['city']}")

    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nFull results written to {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
