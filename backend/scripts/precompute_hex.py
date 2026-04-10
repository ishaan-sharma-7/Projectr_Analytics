"""Precompute hex grids for all static universities and persist to disk cache.

Run from project root:
    python -m backend.scripts.precompute_hex

Behaviour:
  - Skips universities whose disk cache file already exists and is < 7 days old.
  - Processes 3 universities at a time with a 3-second inter-batch sleep to
    stay within Overpass API rate limits.
  - Resumable: safe to kill and restart mid-run.
"""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace

from backend.adapters import (
    osm_transit,
    osm_buildings,
    national_constraints,
)
from backend.config import config
from backend.main import (
    CLASSIFICATION_MODEL_VERSION,
    _derive_effective_radius_miles,
)
from backend.scoring.h3_hex import (
    generate_campus_hex_grid,
    compute_hex_features,
    to_geojson,
)

import hashlib
from datetime import datetime, timezone


def _hex_disk_cache_path(cache_key: tuple) -> Path:
    """Return the on-disk path for a hex cache entry."""
    slug = hashlib.md5(str(cache_key).encode()).hexdigest()[:16]
    return Path(config.cache_dir) / "hex" / f"{cache_key[0]}_{slug}.json"


def _load_hex_disk_cache(cache_key: tuple) -> dict | None:
    """Load a hex GeoJSON from disk if it exists and is < 7 days old."""
    path = _hex_disk_cache_path(cache_key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        cached_at = data.get("metadata", {}).get("cached_at")
        if cached_at:
            saved = datetime.fromisoformat(cached_at)
            if (datetime.now(timezone.utc) - saved).days > 7:
                return None
        return data
    except Exception:
        return None


def _write_hex_disk_cache(cache_key: tuple, geojson: dict) -> None:
    """Persist hex GeoJSON to disk cache."""
    path = _hex_disk_cache_path(cache_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    geojson.setdefault("metadata", {})["cached_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(geojson), encoding="utf-8")
    print(f"  [disk] Cached → {path.name}")

RESOLUTION = 9
RADIUS_MILES = 1.5
AUTO_RADIUS = True
OSM_LAYER_VERSION = "osm_geom_v2"
BATCH_SIZE = 3
BATCH_SLEEP_S = 3.0

STATIC_UNIVERSITIES = [
    {"name": "Virginia Tech", "lat": 37.2284, "lon": -80.4234, "state": "VA"},
    {"name": "University of Virginia", "lat": 38.0336, "lon": -78.5080, "state": "VA"},
    {"name": "University of Tennessee Knoxville", "lat": 35.9544, "lon": -83.9243, "state": "TN"},
    {"name": "University of North Carolina Chapel Hill", "lat": 35.9049, "lon": -79.0469, "state": "NC"},
    {"name": "University of Florida", "lat": 29.6436, "lon": -82.3549, "state": "FL"},
    {"name": "Arizona State University", "lat": 33.4242, "lon": -111.9281, "state": "AZ"},
    {"name": "University of Georgia", "lat": 33.9480, "lon": -83.3774, "state": "GA"},
    {"name": "Clemson University", "lat": 34.6834, "lon": -82.8374, "state": "SC"},
    {"name": "North Carolina State University", "lat": 35.7872, "lon": -78.6672, "state": "NC"},
    {"name": "Boise State University", "lat": 43.6016, "lon": -116.1995, "state": "ID"},
    {"name": "University of Alabama", "lat": 33.2119, "lon": -87.5444, "state": "AL"},
    {"name": "University of South Carolina", "lat": 33.9963, "lon": -81.0297, "state": "SC"},
    {"name": "Ohio State University", "lat": 40.0076, "lon": -83.0300, "state": "OH"},
    {"name": "Michigan State University", "lat": 42.7018, "lon": -84.4822, "state": "MI"},
    {"name": "Texas A&M University", "lat": 30.6187, "lon": -96.3365, "state": "TX"},
    {"name": "Pennsylvania State University", "lat": 40.7982, "lon": -77.8599, "state": "PA"},
    {"name": "Indiana University Bloomington", "lat": 39.1682, "lon": -86.5230, "state": "IN"},
    {"name": "University of Kentucky", "lat": 38.0306, "lon": -84.5037, "state": "KY"},
    {"name": "Mississippi State University", "lat": 33.4554, "lon": -88.7923, "state": "MS"},
    {"name": "University of Nevada Las Vegas", "lat": 36.1076, "lon": -115.1405, "state": "NV"},
    {"name": "University of Michigan", "lat": 42.2780, "lon": -83.7382, "state": "MI"},
    {"name": "University of California Los Angeles", "lat": 34.0689, "lon": -118.4452, "state": "CA"},
    {"name": "University of California Berkeley", "lat": 37.8724, "lon": -122.2595, "state": "CA"},
    {"name": "University of Texas at Austin", "lat": 30.2849, "lon": -97.7341, "state": "TX"},
    {"name": "University of Washington", "lat": 47.6553, "lon": -122.3035, "state": "WA"},
    {"name": "University of Wisconsin Madison", "lat": 43.0766, "lon": -89.4125, "state": "WI"},
    {"name": "University of Illinois Urbana-Champaign", "lat": 40.1020, "lon": -88.2272, "state": "IL"},
    {"name": "Purdue University", "lat": 40.4259, "lon": -86.9081, "state": "IN"},
    {"name": "University of Minnesota", "lat": 44.9740, "lon": -93.2277, "state": "MN"},
    {"name": "University of Colorado Boulder", "lat": 40.0076, "lon": -105.2659, "state": "CO"},
    {"name": "Colorado State University", "lat": 40.5734, "lon": -105.0865, "state": "CO"},
    {"name": "Iowa State University", "lat": 42.0267, "lon": -93.6465, "state": "IA"},
    {"name": "Kansas State University", "lat": 39.1836, "lon": -96.5717, "state": "KS"},
    {"name": "University of Kansas", "lat": 38.9543, "lon": -95.2558, "state": "KS"},
    {"name": "University of Missouri", "lat": 38.9404, "lon": -92.3277, "state": "MO"},
    {"name": "University of Nebraska Lincoln", "lat": 40.8202, "lon": -96.7005, "state": "NE"},
    {"name": "Oklahoma State University", "lat": 36.1156, "lon": -97.0584, "state": "OK"},
    {"name": "University of Oklahoma", "lat": 35.2059, "lon": -97.4456, "state": "OK"},
    {"name": "University of Arkansas", "lat": 36.0682, "lon": -94.1742, "state": "AR"},
    {"name": "Louisiana State University", "lat": 30.4133, "lon": -91.1800, "state": "LA"},
    {"name": "Auburn University", "lat": 32.6099, "lon": -85.4808, "state": "AL"},
    {"name": "University of Mississippi", "lat": 34.3654, "lon": -89.5378, "state": "MS"},
    {"name": "University of Memphis", "lat": 35.1185, "lon": -89.9374, "state": "TN"},
    {"name": "University of Arizona", "lat": 32.2319, "lon": -110.9501, "state": "AZ"},
    {"name": "New Mexico State University", "lat": 32.2797, "lon": -106.7481, "state": "NM"},
    {"name": "University of New Mexico", "lat": 35.0844, "lon": -106.6199, "state": "NM"},
    {"name": "University of Utah", "lat": 40.7649, "lon": -111.8421, "state": "UT"},
    {"name": "Utah State University", "lat": 41.7458, "lon": -111.8142, "state": "UT"},
    {"name": "University of Oregon", "lat": 44.0459, "lon": -123.0674, "state": "OR"},
    {"name": "Oregon State University", "lat": 44.5638, "lon": -123.2794, "state": "OR"},
    {"name": "Washington State University", "lat": 46.7298, "lon": -117.1817, "state": "WA"},
    {"name": "Montana State University", "lat": 45.6669, "lon": -111.0541, "state": "MT"},
    {"name": "University of Montana", "lat": 46.8625, "lon": -113.9848, "state": "MT"},
    {"name": "University of Wyoming", "lat": 41.3149, "lon": -105.5666, "state": "WY"},
    {"name": "University of Idaho", "lat": 46.7271, "lon": -116.9916, "state": "ID"},
    {"name": "University of South Florida", "lat": 28.0587, "lon": -82.4139, "state": "FL"},
    {"name": "Florida State University", "lat": 30.4418, "lon": -84.2985, "state": "FL"},
    {"name": "University of Central Florida", "lat": 28.6024, "lon": -81.2001, "state": "FL"},
    {"name": "Georgia Tech", "lat": 33.7756, "lon": -84.3963, "state": "GA"},
    {"name": "University of Maryland", "lat": 38.9869, "lon": -76.9426, "state": "MD"},
    {"name": "Penn State University", "lat": 40.7982, "lon": -77.8599, "state": "PA"},
    {"name": "Rutgers University", "lat": 40.5008, "lon": -74.4474, "state": "NJ"},
    {"name": "University of Pittsburgh", "lat": 40.4444, "lon": -79.9608, "state": "PA"},
    {"name": "Temple University", "lat": 39.9812, "lon": -75.1548, "state": "PA"},
    {"name": "University of Cincinnati", "lat": 39.1329, "lon": -84.5150, "state": "OH"},
]


def _load_prescored() -> dict[str, dict]:
    """Load prescored.json; returns dict keyed by university name."""
    path = Path(config.cache_dir) / "prescored.json"
    if not path.exists():
        return {}
    try:
        entries = json.loads(path.read_text())
        return {e["university"]["name"]: e for e in entries}
    except Exception as exc:
        print(f"[precompute] Failed to load prescored.json: {exc}")
        return {}


async def precompute_one(uni_info: dict, prescored: dict[str, dict]) -> None:
    name = uni_info["name"]
    lat = uni_info["lat"]
    lon = uni_info["lon"]
    state = uni_info["state"]

    # Resolve prescored data for this university
    scored = prescored.get(name)
    if scored:
        unitid = scored["university"]["unitid"]
        base_score = float(scored.get("score", 50.0))
        permit_history = scored.get("permit_history", [])
        permits_5yr = sum(p.get("permits", 0) for p in permit_history[-5:])
        housing_units = int(scored.get("nearby_housing_units") or 0)
    else:
        # Use a placeholder unitid derived from name for cache key stability
        unitid = abs(hash(name)) % (10 ** 9)
        base_score = 50.0
        permits_5yr = 0
        housing_units = 0

    probe_radius_miles = max(RADIUS_MILES, 4.0) if AUTO_RADIUS else RADIUS_MILES

    # Build a stub cache_key to check if disk cache already exists
    # We need the effective radius to compute the real key, but we'll check
    # a wider set by using RADIUS_MILES as a lower bound probe.
    # The real cache_key is built after fetching markers (radius may differ).
    # For skip logic, we check after computing.

    print(f"[precompute] Starting {name} (res={RESOLUTION})")

    # Fetch all markers concurrently
    try:
        (
            bus_stops,
            campus_markers,
            residential_markers,
            non_buildable_markers,
            development_markers,
            commercial_markers,
            parking_markers,
            national_constraint_points,
        ) = await asyncio.gather(
            osm_transit.fetch_bus_stops(lat, lon, probe_radius_miles),
            osm_buildings.fetch_campus_markers(lat, lon, probe_radius_miles),
            osm_buildings.fetch_residential_markers(lat, lon, probe_radius_miles),
            osm_buildings.fetch_non_buildable_markers(lat, lon, probe_radius_miles),
            osm_buildings.fetch_development_markers(lat, lon, probe_radius_miles),
            osm_buildings.fetch_commercial_markers(lat, lon, probe_radius_miles),
            osm_buildings.fetch_parking_markers(lat, lon, probe_radius_miles),
            national_constraints.fetch_national_constraint_points(lat, lon, probe_radius_miles),
            return_exceptions=True,
        )
    except Exception as exc:
        print(f"[precompute] {name}: gather failed: {exc}")
        return

    def _safe(result: object, fallback: list) -> list:
        return result if not isinstance(result, Exception) else fallback

    bus_stops = _safe(bus_stops, [])
    campus_markers = _safe(campus_markers, [])
    residential_markers = _safe(residential_markers, [])
    non_buildable_markers = _safe(non_buildable_markers, [])
    development_markers = _safe(development_markers, [])
    commercial_markers = _safe(commercial_markers, [])
    parking_markers = _safe(parking_markers, [])
    national_constraint_points = _safe(national_constraint_points, [])

    effective_radius_miles = (
        _derive_effective_radius_miles(
            campus_lat=lat,
            campus_lng=lon,
            requested_radius_miles=RADIUS_MILES,
            residential_markers=residential_markers,
            non_buildable_markers=non_buildable_markers,
            development_markers=development_markers,
            max_radius_miles=4.5,
        )
        if AUTO_RADIUS
        else RADIUS_MILES
    )

    cache_key = (
        unitid,
        round(effective_radius_miles, 2),
        int(RESOLUTION),
        False,  # debug_hex always False for precompute
        CLASSIFICATION_MODEL_VERSION,
        f"{OSM_LAYER_VERSION}|{national_constraints.LAYER_DATA_VERSION}",
    )

    if _load_hex_disk_cache(cache_key) is not None:
        print(f"[precompute] {name}: already cached, skipping.")
        return

    hex_indices = generate_campus_hex_grid(
        campus_lat=lat,
        campus_lng=lon,
        radius_miles=effective_radius_miles,
        resolution=RESOLUTION,
    )

    features = compute_hex_features(
        hex_indices=hex_indices,
        campus_lat=lat,
        campus_lng=lon,
        base_score=base_score,
        permits_5yr=permits_5yr,
        housing_units=housing_units,
        radius_miles=effective_radius_miles,
        bus_stops=bus_stops,
        campus_markers=campus_markers,
        residential_markers=residential_markers,
        non_buildable_markers=non_buildable_markers,
        development_markers=development_markers,
        commercial_markers=commercial_markers,
        parking_markers=parking_markers,
        national_constraint_points=national_constraint_points,
        resolution=RESOLUTION,
    )

    geojson = to_geojson(features, include_debug=False)
    geojson["metadata"] = {
        "university": name,
        "campus_lat": lat,
        "campus_lng": lon,
        "requested_radius_miles": RADIUS_MILES,
        "effective_radius_miles": round(effective_radius_miles, 2),
        "probe_radius_miles": round(probe_radius_miles, 2),
        "auto_radius": AUTO_RADIUS,
        "hex_resolution": RESOLUTION,
        "hex_count": len(features),
        "base_score": base_score,
        "classification_model_version": CLASSIFICATION_MODEL_VERSION,
        "data_layer_versions": {
            "osm": OSM_LAYER_VERSION,
            "national_constraints": national_constraints.LAYER_DATA_VERSION,
        },
        "debug_hex_enabled": False,
    }

    _write_hex_disk_cache(cache_key, geojson)
    print(f"[precompute] {name}: done ({len(features)} hexes, radius={effective_radius_miles:.2f} mi)")


async def main() -> None:
    prescored = _load_prescored()
    print(f"[precompute] Loaded {len(prescored)} prescored universities.")
    print(f"[precompute] Precomputing {len(STATIC_UNIVERSITIES)} universities at res={RESOLUTION}…")

    for i in range(0, len(STATIC_UNIVERSITIES), BATCH_SIZE):
        batch = STATIC_UNIVERSITIES[i:i + BATCH_SIZE]
        await asyncio.gather(*[precompute_one(u, prescored) for u in batch])
        if i + BATCH_SIZE < len(STATIC_UNIVERSITIES):
            await asyncio.sleep(BATCH_SLEEP_S)

    print("[precompute] All done.")


if __name__ == "__main__":
    asyncio.run(main())
