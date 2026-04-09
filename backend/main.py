"""CampusLens FastAPI application.

Endpoints:
  GET  /health              — health check
  GET  /universities        — pre-scored universities for the national map
  POST /score               — compute Housing Pressure Score (with Gemini summary)
  POST /score/stream        — SSE endpoint: streams agent log + final score
  GET  /hex/{university_name} — H3 hex GeoJSON for city-level choropleth
  GET  /hex/stream/{university_name} — NDJSON streamed H3 hex chunks
"""

import json
import math
import os
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.config import config
from backend.models.schemas import (
    HousingPressureScore,
    ScoreRequest,
    UniversityListItem,
)
from backend.adapters import (
    scorecard,
    ipeds,
    ipeds_housing,
    census_bps,
    census_acs,
    census_acs_extra,
    rent,
    fema_disasters,
    osm_transit,
    osm_buildings,
    national_constraints,
)
from backend.scoring.pressure import compute_pressure_score
from backend.scoring.h3_hex import (
    generate_campus_hex_grid,
    compute_hex_features,
    to_geojson,
)
from backend.agent.gemini_agent import generate_gemini_summary, score_with_streaming

# ── Pre-scored cache ──
_prescored: dict[int, HousingPressureScore] = {}
_hex_response_cache: dict[tuple, dict] = {}
CLASSIFICATION_MODEL_VERSION = "hex_accuracy_v1_5_2"


def _slugify_filename(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _write_hex_debug_snapshot(university_name: str, payload: dict) -> str | None:
    """Persist a full per-hex debug snapshot to cache/hex_debug for tuning."""
    try:
        debug_dir = Path(config.cache_dir) / "hex_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = _slugify_filename(university_name) or "university"
        debug_path = debug_dir / f"{safe_name}_{ts}.json"
        debug_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(debug_path)
    except Exception as exc:
        print(f"[/hex] Failed writing debug snapshot: {exc}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load pre-scored universities from cache on startup."""
    cache_path = Path(config.cache_dir) / "prescored.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_text())
        for entry in data:
            score = HousingPressureScore.model_validate(entry)
            _prescored[score.university.unitid] = score
        print(f"Loaded {len(_prescored)} pre-scored universities from cache.")
    yield


app = FastAPI(
    title="CampusLens",
    description="Student Housing Market Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ──


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "prescored_count": len(_prescored),
        "has_scorecard_key": bool(config.scorecard_api_key),
        "has_census_key": bool(config.census_api_key),
        "has_gemini_key": bool(config.gemini_api_key),
    }


@app.get("/universities", response_model=list[UniversityListItem])
async def list_universities():
    """Return all pre-scored universities for the national map."""
    items: list[UniversityListItem] = []
    for uid, score in _prescored.items():
        label = "high" if score.score >= 70 else "medium" if score.score >= 40 else "low"
        items.append(UniversityListItem(
            unitid=score.university.unitid,
            name=score.university.name,
            city=score.university.city,
            state=score.university.state,
            lat=score.university.lat,
            lon=score.university.lon,
            score=score.score,
            score_label=label,
        ))
    return items


@app.post("/score", response_model=HousingPressureScore)
async def score_university(req: ScoreRequest):
    """Compute Housing Pressure Score for a university.

    Checks pre-scored cache first. For cache misses, fetches all data live,
    computes the score, and generates a Gemini market summary.
    """
    # ── Cache hit by explicit unitid ──
    if req.unitid and req.unitid in _prescored:
        cached = _prescored[req.unitid]
        if not cached.gemini_summary:
            summary = await generate_gemini_summary(cached)
            if summary:
                cached = cached.model_copy(update={"gemini_summary": summary})
                _prescored[req.unitid] = cached
        return cached

    # ── Step 1: Resolve university metadata + institutional strength ──
    # Single Scorecard call returns both — strength piggybacks on the same
    # request via the extended FIELDS string in the adapter.
    if req.unitid:
        meta_pair = await scorecard.get_university_by_id_with_strength(req.unitid)
    else:
        meta_pair = await scorecard.search_university_with_strength(req.university_name)

    if not meta_pair:
        raise HTTPException(404, f"University not found: {req.university_name}")
    uni, institutional_strength = meta_pair

    # Cache hit by resolved unitid
    if uni.unitid in _prescored:
        cached = _prescored[uni.unitid]
        if not cached.gemini_summary:
            summary = await generate_gemini_summary(cached)
            if summary:
                cached = cached.model_copy(update={"gemini_summary": summary})
                _prescored[uni.unitid] = cached
        return cached

    # ── Step 2: Fetch enrollment trend ──
    enrollment_trend = await ipeds.fetch_enrollment_trend(uni.unitid)

    # ── Step 3: Resolve county FIPS ──
    county_info = await census_bps.fetch_county_fips(uni.lat, uni.lon)
    state_fips = county_info[0] if county_info else ""
    county_fips = county_info[1] if county_info else ""

    # ── Step 4: Fetch building permits ──
    permit_history = []
    if state_fips and county_fips:
        permit_history = await census_bps.fetch_permits_by_county(uni.state, county_fips)

    # ── Step 5: Fetch housing units ──
    housing_units = 0
    if state_fips and county_fips:
        housing_units = await census_acs.get_county_housing_total(state_fips, county_fips)

    # ── Step 6: Fetch rent data ──
    fips = f"{state_fips}{county_fips}" if state_fips and county_fips else ""
    rent_history = await rent.load_rent_data(uni.city, uni.state, fips)

    # ── Step 6b: Fetch ACS demographic context ──
    demographics = None
    if state_fips and county_fips:
        demographics = await census_acs_extra.fetch_county_demographics(
            state_fips, county_fips,
        )

    # ── Step 6c: Fetch on-campus housing capacity ──
    housing_capacity = await ipeds_housing.fetch_housing_capacity(uni.unitid)

    # ── Step 6d: Fetch federal disaster history ──
    disaster_risk = None
    if state_fips and county_fips:
        disaster_risk = await fema_disasters.fetch_disaster_history(
            state_fips, county_fips, years=10,
        )

    # ── Step 6e: Fetch existing residential building footprint ──
    existing_housing = await osm_buildings.fetch_buildings(uni.lat, uni.lon, 1.5)

    # ── Step 7: Compute score ──
    result = compute_pressure_score(
        university=uni,
        enrollment_trend=enrollment_trend,
        permit_history=permit_history,
        housing_units=housing_units,
        rent_history=rent_history,
        demographics=demographics,
        housing_capacity=housing_capacity,
        disaster_risk=disaster_risk,
        institutional_strength=institutional_strength,
        existing_housing=existing_housing,
    )

    # ── Step 8: Gemini summary ──
    summary = await generate_gemini_summary(result)
    if summary:
        result = result.model_copy(update={"gemini_summary": summary})

    return result


@app.post("/score/stream")
async def score_stream(req: ScoreRequest):
    """SSE endpoint: streams agent log events + final score as JSON.

    Event shapes:
      {"type": "log",    "message": "..."}       — progress update
      {"type": "result", "data": {...}}           — HousingPressureScore payload
      {"type": "error",  "message": "..."}        — fatal error

    Usage (JavaScript):
      const es = new EventSource("/score/stream");
      es.onmessage = (e) => { const event = JSON.parse(e.data); ... };

    Note: EventSource only supports GET. For POST bodies, use fetch() with
    ReadableStream to consume the response:
      const resp = await fetch("/score/stream", {method:"POST", body: ...});
      const reader = resp.body.getReader();
    """
    async def generate():
        async for chunk in score_with_streaming(req, _prescored):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering for SSE
        },
    )


@app.get("/hex/{university_name}")
async def get_hex_grid(
    university_name: str,
    radius_miles: float = Query(default=1.5, ge=0.5, le=5.0),
    hex_resolution: int = Query(default=9, ge=8, le=10),
    auto_radius: bool = Query(default=True),
    debug_hex: bool = Query(default=False),
):
    """Return H3 hexagonal grid GeoJSON for the city-level choropleth.

    Each hex feature carries:
      - pressure_score (0–100): drives fill color on the map
      - raw_pressure_score (0–100): unconstrained demand signal
      - distance_km / distance_to_campus_miles: distance from campus centroid
      - permit_density: estimated permits per km² (spatially distributed)
      - unit_density: housing units per km²
      - bus_stop_count: OSM transit nodes inside this hex cell
      - campus_feature_count / dormitory_count: per-hex campus markers
      - off_campus_housing_count / campus_share: mixed-use context
      - development_marker_count: existing built property density
      - non_buildable_marker_count / water_marker_count: land constraints
      - buildable_for_housing / buildability_score: feasibility signal
      - on_campus_constrained: likely non-developable campus-controlled cell
      - development_status: human-readable developability status
      - transit_label: "Transit Hub" | "Walkable" | "Isolated"
      - label: "high" | "medium" | "low"

    Query params:
      radius_miles: Requested search radius around campus (0.5–5.0, default 1.5).
      hex_resolution: H3 resolution (8–10, default 9 for finer cells).
      auto_radius: Dynamically widen radius based on observed housing spread.
    """
    import asyncio

    # ── Resolve university ──
    uni = await scorecard.search_university(university_name)
    if not uni:
        raise HTTPException(404, f"University not found: {university_name}")

    osm_layer_version = "osm_geom_v2"
    # ── Get base score (from cache or compute) ──
    base_score = 50.0  # neutral default
    permits_5yr = 0
    housing_units = 0
    probe_radius_miles = max(radius_miles, 4.0) if auto_radius else radius_miles

    # Transit + campus-land markers are independent of base-score data and can
    # run concurrently with everything else.
    bus_stops_task = asyncio.create_task(
        osm_transit.fetch_bus_stops(uni.lat, uni.lon, probe_radius_miles)
    )
    campus_markers_task = asyncio.create_task(
        osm_buildings.fetch_campus_markers(uni.lat, uni.lon, probe_radius_miles)
    )
    residential_markers_task = asyncio.create_task(
        osm_buildings.fetch_residential_markers(uni.lat, uni.lon, probe_radius_miles)
    )
    non_buildable_markers_task = asyncio.create_task(
        osm_buildings.fetch_non_buildable_markers(uni.lat, uni.lon, probe_radius_miles)
    )
    development_markers_task = asyncio.create_task(
        osm_buildings.fetch_development_markers(uni.lat, uni.lon, probe_radius_miles)
    )
    commercial_markers_task = asyncio.create_task(
        osm_buildings.fetch_commercial_markers(uni.lat, uni.lon, probe_radius_miles)
    )
    parking_markers_task = asyncio.create_task(
        osm_buildings.fetch_parking_markers(uni.lat, uni.lon, probe_radius_miles)
    )
    national_constraint_points_task = asyncio.create_task(
        national_constraints.fetch_national_constraint_points(
            uni.lat, uni.lon, probe_radius_miles
        )
    )

    if uni.unitid in _prescored:
        cached = _prescored[uni.unitid]
        base_score = cached.score
        permits_5yr = sum(p.permits for p in cached.permit_history[-5:])
        housing_units = cached.nearby_housing_units or 0
    else:
        # Fetch data needed for hex coloring
        county_info = await census_bps.fetch_county_fips(uni.lat, uni.lon)
        state_fips = county_info[0] if county_info else ""
        county_fips = county_info[1] if county_info else ""

        if state_fips and county_fips:
            permit_history, housing_units = await _fetch_permits_and_units(
                uni.state, county_fips, state_fips
            )
            permits_5yr = sum(p.permits for p in permit_history[-5:])

    # ── Await transit data (may be empty if Overpass unreachable) ──
    try:
        bus_stops = await bus_stops_task
        bus_stops_ok = True
    except Exception as exc:
        print(f"[/hex] Overpass task failed: {exc}")
        bus_stops = []
        bus_stops_ok = False

    try:
        campus_markers = await campus_markers_task
        campus_markers_ok = True
    except Exception as exc:
        print(f"[/hex] Campus marker task failed: {exc}")
        campus_markers = []
        campus_markers_ok = False

    try:
        residential_markers = await residential_markers_task
        residential_markers_ok = True
    except Exception as exc:
        print(f"[/hex] Residential marker task failed: {exc}")
        residential_markers = []
        residential_markers_ok = False

    try:
        non_buildable_markers = await non_buildable_markers_task
        non_buildable_markers_ok = True
    except Exception as exc:
        print(f"[/hex] Non-buildable marker task failed: {exc}")
        non_buildable_markers = []
        non_buildable_markers_ok = False

    try:
        development_markers = await development_markers_task
        development_markers_ok = True
    except Exception as exc:
        print(f"[/hex] Development marker task failed: {exc}")
        development_markers = []
        development_markers_ok = False

    try:
        commercial_markers = await commercial_markers_task
        commercial_markers_ok = True
    except Exception as exc:
        print(f"[/hex] Commercial marker task failed: {exc}")
        commercial_markers = []
        commercial_markers_ok = False

    try:
        parking_markers = await parking_markers_task
        parking_markers_ok = True
    except Exception as exc:
        print(f"[/hex] Parking marker task failed: {exc}")
        parking_markers = []
        parking_markers_ok = False

    try:
        national_constraint_points = await national_constraint_points_task
        national_constraints_ok = True
    except Exception as exc:
        print(f"[/hex] National constraints task failed: {exc}")
        national_constraint_points = []
        national_constraints_ok = False

    effective_radius_miles = (
        _derive_effective_radius_miles(
            campus_lat=uni.lat,
            campus_lng=uni.lon,
            requested_radius_miles=radius_miles,
            residential_markers=residential_markers,
            non_buildable_markers=non_buildable_markers,
            development_markers=development_markers,
            max_radius_miles=4.5,
        )
        if auto_radius
        else radius_miles
    )

    cache_key = (
        uni.unitid,
        round(effective_radius_miles, 2),
        int(hex_resolution),
        bool(debug_hex),
        CLASSIFICATION_MODEL_VERSION,
        f"{osm_layer_version}|{national_constraints.LAYER_DATA_VERSION}",
    )
    if cache_key in _hex_response_cache:
        return _hex_response_cache[cache_key]

    # ── Generate hex grid ──
    hex_indices = generate_campus_hex_grid(
        campus_lat=uni.lat,
        campus_lng=uni.lon,
        radius_miles=effective_radius_miles,
        resolution=hex_resolution,
    )

    features = compute_hex_features(
        hex_indices=hex_indices,
        campus_lat=uni.lat,
        campus_lng=uni.lon,
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
        resolution=hex_resolution,
    )

    geojson = to_geojson(features, include_debug=debug_hex)
    status_counts = Counter(f.development_status for f in features)
    geojson["metadata"] = {
        "university": uni.name,
        "campus_lat": uni.lat,
        "campus_lng": uni.lon,
        "requested_radius_miles": radius_miles,
        "effective_radius_miles": round(effective_radius_miles, 2),
        "probe_radius_miles": round(probe_radius_miles, 2),
        "auto_radius": auto_radius,
        "hex_resolution": hex_resolution,
        "hex_count": len(features),
        "base_score": base_score,
        "bus_stops_fetched": len(bus_stops),
        "campus_markers_fetched": len(campus_markers),
        "residential_markers_fetched": len(residential_markers),
        "non_buildable_markers_fetched": len(non_buildable_markers),
        "development_markers_fetched": len(development_markers),
        "commercial_markers_fetched": len(commercial_markers),
        "parking_markers_fetched": len(parking_markers),
        "national_constraint_points_fetched": len(national_constraint_points),
        "classification_model_version": CLASSIFICATION_MODEL_VERSION,
        "data_layer_versions": {
            "osm": osm_layer_version,
            "national_constraints": national_constraints.LAYER_DATA_VERSION,
        },
        "source_completeness": {
            "bus_stops": bus_stops_ok,
            "campus_markers": campus_markers_ok,
            "residential_markers": residential_markers_ok,
            "non_buildable_markers": non_buildable_markers_ok,
            "development_markers": development_markers_ok,
            "commercial_markers": commercial_markers_ok,
            "parking_markers": parking_markers_ok,
            "national_constraints": national_constraints_ok,
        },
        "development_status_counts": dict(status_counts),
        "debug_hex_enabled": debug_hex,
    }
    if debug_hex:
        debug_payload = {
            "requested_university_name": university_name,
            "resolved_university_name": uni.name,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "metadata": geojson["metadata"],
            "features": geojson.get("features", []),
        }
        debug_path = _write_hex_debug_snapshot(uni.name, debug_payload)
        if debug_path:
            geojson["metadata"]["debug_log_path"] = debug_path
            print(f"[/hex] Debug snapshot written: {debug_path}")
    _hex_response_cache[cache_key] = geojson
    return geojson


@app.get("/hex/stream/{university_name}")
async def get_hex_grid_stream(
    university_name: str,
    radius_miles: float = Query(default=1.5, ge=0.5, le=5.0),
    hex_resolution: int = Query(default=9, ge=8, le=10),
    auto_radius: bool = Query(default=True),
    debug_hex: bool = Query(default=False),
):
    """Stream H3 hex features as NDJSON chunks for progressive map rendering."""
    import asyncio

    geojson = await get_hex_grid(
        university_name=university_name,
        radius_miles=radius_miles,
        hex_resolution=hex_resolution,
        auto_radius=auto_radius,
        debug_hex=debug_hex,
    )

    async def generate():
        features = geojson.get("features", [])
        metadata = geojson.get("metadata", {})
        total = len(features)
        batch_size = 12

        yield json.dumps({
            "type": "metadata",
            "metadata": metadata,
            "total_features": total,
        }) + "\n"

        for start in range(0, total, batch_size):
            batch = features[start:start + batch_size]
            yield json.dumps({
                "type": "chunk",
                "start": start,
                "count": len(batch),
                "features": batch,
            }) + "\n"
            await asyncio.sleep(0.12)

        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles."""
    R_KM = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return (R_KM * 2 * math.asin(math.sqrt(a))) * 0.621371


def _percentile(sorted_values: list[float], p: float) -> float:
    """Simple nearest-rank percentile for a sorted numeric list."""
    if not sorted_values:
        return 0.0
    p = max(0.0, min(1.0, p))
    idx = int(round((len(sorted_values) - 1) * p))
    return sorted_values[idx]


def _derive_effective_radius_miles(
    campus_lat: float,
    campus_lng: float,
    requested_radius_miles: float,
    residential_markers: list[tuple[float, float, str]],
    non_buildable_markers: list[tuple[float, float, str]],
    development_markers: list[tuple[float, float, str]],
    max_radius_miles: float = 4.5,
) -> float:
    """Dynamically widen radius so off-campus housing clusters are not clipped."""
    housing_distances: list[float] = []
    for lat, lng, building in residential_markers:
        if building not in {"apartments", "residential", "house"}:
            continue
        housing_distances.append(_haversine_miles(campus_lat, campus_lng, lat, lng))

    if not housing_distances:
        # Keep a wider baseline when OSM housing markers are sparse so
        # near-campus neighborhoods are less likely to be clipped.
        return max(2.0, requested_radius_miles)

    housing_distances.sort()
    p90 = _percentile(housing_distances, 0.90)
    p97 = _percentile(housing_distances, 0.97)
    p99 = _percentile(housing_distances, 0.99)

    effective = max(requested_radius_miles, 2.0, p90 + 0.45)
    if p97 > effective + 0.20:
        effective = max(effective, p97 + 0.20)
    if p99 > effective:
        effective = max(effective, p99 + 0.10)

    near_core_nonbuildable = 0
    for lat, lng, _kind in non_buildable_markers:
        if _haversine_miles(campus_lat, campus_lng, lat, lng) <= 1.2:
            near_core_nonbuildable += 1
    if near_core_nonbuildable >= 8:
        effective += 0.35

    near_core_development = 0
    for lat, lng, kind in development_markers:
        if kind != "structure":
            continue
        if _haversine_miles(campus_lat, campus_lng, lat, lng) <= 1.0:
            near_core_development += 1
    if near_core_development >= 40:
        effective += 0.30

    return round(min(max(effective, requested_radius_miles), max_radius_miles), 2)


async def _fetch_permits_and_units(state: str, county_fips: str, state_fips: str):
    """Helper: fetch permit history and housing unit count concurrently."""
    import asyncio
    permit_task = census_bps.fetch_permits_by_county(state, county_fips)
    units_task = census_acs.get_county_housing_total(state_fips, county_fips)
    return await asyncio.gather(permit_task, units_task)
