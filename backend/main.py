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
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse

from backend.config import config
from backend.models.schemas import (
    HousingPressureScore,
    ScoreRequest,
    UniversityListItem,
    ChatRequest,
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
    master_plans,
    occupancy_ordinances,
    zoning_gis,
    land_attom,
)
from backend.models.schemas import MasterPlanData, OccupancyOrdinance
from backend.scoring.pressure import compute_pressure_score
from backend.scoring.h3_hex import (
    generate_campus_hex_grid,
    compute_hex_features,
    to_geojson,
)
from backend.agent.gemini_agent import generate_gemini_summary, score_with_streaming, answer_chat_query
from backend.db import firestore as db

# ── Pre-scored cache ──
_prescored: dict[int, HousingPressureScore] = {}
_name_to_unitid: dict[str, int] = {}  # lowercase name → unitid (O(1) lookup)
_hex_response_cache: dict[tuple, dict] = {}
_hex_slim_cache: dict[tuple, bytes] = {}  # pre-serialized gzipped slim responses
_unitid_hex_keys: dict[int, set[tuple]] = {}  # unitid → set of cache keys
CLASSIFICATION_MODEL_VERSION = "hex_accuracy_v3_0_0"


def _register_hex_cache(cache_key: tuple, geojson: dict, compressed: bytes):
    """Store hex data in all tiers and update the unitid index."""
    _hex_response_cache[cache_key] = geojson
    _hex_slim_cache[cache_key] = compressed
    unitid = cache_key[0]
    _unitid_hex_keys.setdefault(unitid, set()).add(cache_key)


def _fast_path_hex_lookup(university_name: str, hex_resolution: int, debug_hex: bool) -> bytes | None:
    """O(1) unitid-based cache lookup. Returns pre-compressed bytes or None."""
    uid = _name_to_unitid.get(university_name.lower())
    if uid is None:
        return None
    candidate_keys = _unitid_hex_keys.get(uid)
    if not candidate_keys:
        return None
    # Prefer exact resolution+debug match
    for ck in candidate_keys:
        if len(ck) >= 4 and ck[2] == int(hex_resolution) and ck[3] == bool(debug_hex):
            cached = _hex_slim_cache.get(ck)
            if cached:
                return cached
    # Fall back to any cached version for this unitid
    for ck in candidate_keys:
        cached = _hex_slim_cache.get(ck)
        if cached:
            return cached
    return None


def _slim_hex_bytes(geojson: dict) -> bytes:
    """Pre-serialize and gzip a slim hex response (no geometry).

    deck.gl renders from h3_index, not polygon coordinates, so geometry
    is stripped. The result is cached as compressed bytes and served
    directly — zero JSON serialization or gzip on cache hits.
    """
    import gzip as _gzip
    slim = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": f["properties"]}
            for f in geojson.get("features", [])
        ],
        "metadata": geojson.get("metadata"),
    }
    return _gzip.compress(json.dumps(slim, separators=(",", ":")).encode(), compresslevel=6)


def _hex_bytes_response(compressed: bytes):
    """Return pre-compressed bytes with correct headers."""
    from fastapi.responses import Response
    return Response(
        content=compressed,
        media_type="application/json",
        headers={"Content-Encoding": "gzip"},
    )


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
    """Load scored universities from Firestore on startup."""
    import asyncio as _aio

    if db.is_available():
        try:
            fs_scores = await _aio.wait_for(db.get_all_scores(), timeout=10.0)
        except _aio.TimeoutError:
            fs_scores = {}
            print("[Firestore] Startup load timed out after 10s — continuing with empty cache.")
        except Exception as exc:
            fs_scores = {}
            print(f"[Firestore] Startup load failed ({exc}) — continuing with empty cache.")

        if fs_scores:
            for uid, data in fs_scores.items():
                _prescored[uid] = HousingPressureScore.model_validate(data)
                _name_to_unitid[_prescored[uid].university.name.lower()] = uid
            print(f"Loaded {len(_prescored)} scores from Firestore.")
        else:
            print("[Firestore] scores collection empty — scores will be added on first analysis.")
    else:
        print("[Firestore] Not configured — scores will only persist in memory.")

    yield


app = FastAPI(
    title="CampusLens",
    description="Student Housing Market Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/chat")
async def chat_with_agent(req: ChatRequest):
    """Answers a chat query via Gemini 2.5 Flash with full DB access, hex data, and scoring."""
    newly_scored: HousingPressureScore | None = None

    async def _score_for_chat(name: str) -> HousingPressureScore | None:
        """Run the full scoring pipeline for a university not yet in the DB."""
        nonlocal newly_scored
        try:
            result = await score_university(ScoreRequest(university_name=name))
            # score_university already persists to _prescored and Firestore
            newly_scored = result
            return result
        except HTTPException:
            return None
        except Exception as exc:
            print(f"[/chat] score_for_chat failed: {exc}")
            return None

    try:
        response_text, resolved_score = await answer_chat_query(
            messages=req.messages,
            uni_name=req.selectedName,
            active_score=req.activeScore,
            all_scores=_prescored,
            hex_cache=_hex_response_cache,
            score_callback=_score_for_chat,
            selected_hex=req.selectedHex,
        )
        # Prefer newly_scored (fresh pipeline run) over resolved_score (cache hit)
        score_to_return = newly_scored or resolved_score
        return {
            "response": response_text,
            "newly_scored": json.loads(score_to_return.model_dump_json()) if score_to_return else None,
        }
    except Exception as exc:
        print(f"[/chat] Error: {exc}")
        raise HTTPException(status_code=500, detail="Internal chat error")


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
        if cached.master_plan is None:
            mp_raw = master_plans.get_planned_beds(cached.university.name)
            if mp_raw:
                cached = cached.model_copy(update={"master_plan": MasterPlanData(**mp_raw)})
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
        if cached.master_plan is None:
            mp_raw = master_plans.get_planned_beds(uni.name)
            if mp_raw:
                cached = cached.model_copy(update={"master_plan": MasterPlanData(**mp_raw)})
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

    # ── Step 6f: Look up campus master plan (planned on-campus beds) ──
    master_plan: MasterPlanData | None = None
    mp_raw = master_plans.get_planned_beds(uni.name)
    if mp_raw:
        master_plan = MasterPlanData(**mp_raw)

    # ── Step 6g: Look up occupancy ordinance for this city ──
    occupancy_ordinance: OccupancyOrdinance | None = None
    occ_raw = occupancy_ordinances.get_ordinance(uni.city, uni.state)
    if occ_raw:
        occupancy_ordinance = OccupancyOrdinance(**occ_raw)

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
        master_plan=master_plan,
        occupancy_ordinance=occupancy_ordinance,
    )

    # ── Step 8: Gemini summary ──
    summary = await generate_gemini_summary(result)
    if summary:
        result = result.model_copy(update={"gemini_summary": summary})

    # Persist to Firestore + in-memory cache
    _prescored[uni.unitid] = result
    _name_to_unitid[result.university.name.lower()] = uni.unitid
    await db.set_score(uni.unitid, json.loads(result.model_dump_json()))

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
            # Persist newly computed scores to Firestore + in-memory cache
            if '"type": "result"' in chunk:
                try:
                    payload = json.loads(chunk.removeprefix("data: ").strip())
                    result = HousingPressureScore.model_validate(payload["data"])
                    uni = result.university
                    _prescored[uni.unitid] = result
                    _name_to_unitid[uni.name.lower()] = uni.unitid
                    await db.set_score(uni.unitid, json.loads(result.model_dump_json()))
                except Exception:
                    pass  # don't break the stream on persistence failure
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

    # ── Fast-path: O(1) unitid index lookup (no API calls, no scanning) ──
    fast = _fast_path_hex_lookup(university_name, hex_resolution, debug_hex)
    if fast is not None:
        return _hex_bytes_response(fast)

    # ── Resolve university: prefer _prescored (free), fall back to Scorecard API ──
    uid = _name_to_unitid.get(university_name.lower())
    if uid and uid in _prescored:
        uni = _prescored[uid].university
    else:
        uni = await scorecard.search_university(university_name)
    if not uni:
        raise HTTPException(404, f"University not found: {university_name}")

    # ── Unitid cache check (catches cases where name didn't match but unitid does) ──
    uid_keys = _unitid_hex_keys.get(uni.unitid)
    if uid_keys:
        for ck in uid_keys:
            cached = _hex_slim_cache.get(ck)
            if cached:
                return _hex_bytes_response(cached)

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
    # Zoning layer: only fetched for universities with a known GIS endpoint.
    zoning_task = (
        asyncio.create_task(
            zoning_gis.fetch_zoning_polygons(
                uni.lat, uni.lon, probe_radius_miles, uni.name
            )
        )
        if zoning_gis.has_gis_support(uni.name)
        else None
    )
    # Land parcel layer: ATTOM vacant lots + land-dominant parcels.
    land_task = asyncio.create_task(
        land_attom.fetch_land_parcels(uni.lat, uni.lon, probe_radius_miles, uni.name)
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

    # ── Await all OSM tasks with a global timeout ──
    # Use gather+wait_for so Overpass failures don't stall the whole request.
    # With the circuit breaker, healthy endpoints respond in 2-8s; if all are
    # down, this caps total wait at 35s and proceeds with whatever data we got.
    _osm_tasks = [
        bus_stops_task, campus_markers_task, residential_markers_task,
        non_buildable_markers_task, development_markers_task,
        commercial_markers_task, parking_markers_task,
    ]
    try:
        _osm_results = await asyncio.wait_for(
            asyncio.gather(*_osm_tasks, return_exceptions=True),
            timeout=35.0,
        )
    except asyncio.TimeoutError:
        print("[/hex] OSM tasks timed out at 35s — using partial data")
        _osm_results = []
        for t in _osm_tasks:
            if t.done() and not t.cancelled():
                try:
                    _osm_results.append(t.result())
                except Exception:
                    _osm_results.append([])
            else:
                t.cancel()
                _osm_results.append([])

    def _safe_result(r, idx):
        val = _osm_results[idx] if idx < len(_osm_results) else []
        return ([], False) if isinstance(val, Exception) else (val, True)

    bus_stops, bus_stops_ok = _safe_result(_osm_results, 0)
    campus_markers, campus_markers_ok = _safe_result(_osm_results, 1)
    residential_markers, residential_markers_ok = _safe_result(_osm_results, 2)
    non_buildable_markers, non_buildable_markers_ok = _safe_result(_osm_results, 3)
    development_markers, development_markers_ok = _safe_result(_osm_results, 4)
    commercial_markers, commercial_markers_ok = _safe_result(_osm_results, 5)
    parking_markers, parking_markers_ok = _safe_result(_osm_results, 6)

    try:
        national_constraint_points = await national_constraint_points_task
        national_constraints_ok = True
    except Exception as exc:
        print(f"[/hex] National constraints task failed: {exc}")
        national_constraint_points = []
        national_constraints_ok = False

    zoning_polygons: list[dict] | None = None
    zoning_ok = False
    if zoning_task is not None:
        try:
            zoning_polygons = await zoning_task
            zoning_ok = True
        except Exception as exc:
            print(f"[/hex] Zoning GIS task failed: {exc}")
            zoning_polygons = None

    land_parcels: list[dict] = []
    land_ok = False
    try:
        land_parcels = await land_task
        land_ok = True
    except Exception as exc:
        print(f"[/hex] Land parcel task failed: {exc}")

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
        f"{osm_layer_version}|{national_constraints.LAYER_DATA_VERSION}|{zoning_gis.LAYER_DATA_VERSION}|{land_attom.LAYER_DATA_VERSION}",
    )
    if cache_key in _hex_slim_cache:
        return _hex_bytes_response(_hex_slim_cache[cache_key])

    if cache_key in _hex_response_cache:
        compressed = _slim_hex_bytes(_hex_response_cache[cache_key])
        _register_hex_cache(cache_key, _hex_response_cache[cache_key], compressed)
        return _hex_bytes_response(compressed)

    fs_hit = await db.get_hex(cache_key)
    if fs_hit:
        compressed = _slim_hex_bytes(fs_hit)
        _register_hex_cache(cache_key, fs_hit, compressed)
        return _hex_bytes_response(compressed)

    # NOTE: Stale fallback removed — old cached versions use legacy labels
    # (high/medium/low) that don't match the current 9-label color system.
    # Serving stale data poisons the cache and causes the "2 color" regression.
    # Fresh computation is always preferred over stale data.

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
        zoning_polygons=zoning_polygons,
        land_parcels=land_parcels,
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
        "zoning_polygons_fetched": len(zoning_polygons) if zoning_polygons is not None else 0,
        "zoning_gis_supported": zoning_task is not None,
        "land_parcels_fetched": len(land_parcels),
        "classification_model_version": CLASSIFICATION_MODEL_VERSION,
        "data_layer_versions": {
            "osm": osm_layer_version,
            "national_constraints": national_constraints.LAYER_DATA_VERSION,
            "zoning_gis": zoning_gis.LAYER_DATA_VERSION,
            "land_attom": land_attom.LAYER_DATA_VERSION,
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
            "zoning_gis": zoning_ok,
            "land_attom": land_ok,
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
    await db.set_hex(cache_key, geojson)
    compressed = _slim_hex_bytes(geojson)
    _register_hex_cache(cache_key, geojson, compressed)
    return _hex_bytes_response(compressed)


@app.get("/hex/stream/{university_name}")
async def get_hex_grid_stream(
    university_name: str,
    radius_miles: float = Query(default=1.5, ge=0.5, le=5.0),
    hex_resolution: int = Query(default=9, ge=8, le=10),
    auto_radius: bool = Query(default=True),
    debug_hex: bool = Query(default=False),
):
    """Stream hex features as NDJSON, sorted center-outward for progressive rendering."""
    import asyncio

    # Ensure the full hex grid is computed and cached
    await get_hex_grid(
        university_name=university_name,
        radius_miles=radius_miles,
        hex_resolution=hex_resolution,
        auto_radius=auto_radius,
        debug_hex=debug_hex,
    )

    # Pull the full geojson from cache using unitid index
    geojson: dict | None = None
    uid = _name_to_unitid.get(university_name.lower())
    if uid:
        for key in (_unitid_hex_keys.get(uid) or ()):
            if key in _hex_response_cache:
                geojson = _hex_response_cache[key]
                break

    if not geojson:
        async def error_gen():
            yield json.dumps({"type": "error", "message": "Hex data not found"}) + "\n"
        return StreamingResponse(error_gen(), media_type="application/x-ndjson")

    async def generate():
        features = geojson.get("features", [])
        metadata = geojson.get("metadata", {})

        # Sort center-outward so closest hexes render first
        features_sorted = sorted(
            features,
            key=lambda f: f.get("properties", {}).get("distance_km", 999),
        )
        # Strip geometry (deck.gl uses h3_index)
        slim_features = [
            {"type": "Feature", "properties": f["properties"]}
            for f in features_sorted
        ]

        total = len(slim_features)
        batch_size = 80

        yield json.dumps({
            "type": "metadata",
            "metadata": metadata,
            "total_features": total,
        }) + "\n"

        for start in range(0, total, batch_size):
            batch = slim_features[start:start + batch_size]
            yield json.dumps({
                "type": "chunk",
                "start": start,
                "count": len(batch),
                "features": batch,
            }) + "\n"

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
