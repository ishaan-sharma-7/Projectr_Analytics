"""CampusLens FastAPI application.

Endpoints:
  GET  /health              — health check
  GET  /universities        — pre-scored universities for the national map
  POST /score               — compute Housing Pressure Score (with Gemini summary)
  POST /score/stream        — SSE endpoint: streams agent log + final score
  GET  /hex/{university_name} — H3 hex GeoJSON for city-level choropleth
"""

import json
import os
from contextlib import asynccontextmanager
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
    radius_miles: float = Query(default=1.5, ge=0.5, le=3.0),
):
    """Return H3 hexagonal grid GeoJSON for the city-level choropleth.

    Each hex feature carries:
      - pressure_score (0–100): drives fill color on the map
      - distance_km / distance_to_campus_miles: distance from campus centroid
      - permit_density: estimated permits per km² (spatially distributed)
      - unit_density: housing units per km²
      - bus_stop_count: OSM transit nodes inside this hex cell
      - transit_label: "Transit Hub" | "Walkable" | "Isolated"
      - label: "high" | "medium" | "low"

    Query params:
      radius_miles: Search radius around campus (0.5–3.0, default 1.5).
    """
    import asyncio

    # ── Resolve university ──
    uni = await scorecard.search_university(university_name)
    if not uni:
        raise HTTPException(404, f"University not found: {university_name}")

    # ── Get base score (from cache or compute) ──
    base_score = 50.0  # neutral default
    permits_5yr = 0
    housing_units = 0

    # Bus stop fetch is independent of base-score data and can run concurrently
    # with everything else. Even on a cache hit we still need it for the hex
    # transit layer.
    bus_stops_task = asyncio.create_task(
        osm_transit.fetch_bus_stops(uni.lat, uni.lon, radius_miles)
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
    except Exception as exc:
        print(f"[/hex] Overpass task failed: {exc}")
        bus_stops = []

    # ── Generate hex grid ──
    hex_indices = generate_campus_hex_grid(
        campus_lat=uni.lat,
        campus_lng=uni.lon,
        radius_miles=radius_miles,
        resolution=8,
    )

    features = compute_hex_features(
        hex_indices=hex_indices,
        campus_lat=uni.lat,
        campus_lng=uni.lon,
        base_score=base_score,
        permits_5yr=permits_5yr,
        housing_units=housing_units,
        radius_miles=radius_miles,
        bus_stops=bus_stops,
        resolution=8,
    )

    geojson = to_geojson(features)
    geojson["metadata"] = {
        "university": uni.name,
        "campus_lat": uni.lat,
        "campus_lng": uni.lon,
        "radius_miles": radius_miles,
        "hex_count": len(features),
        "base_score": base_score,
        "bus_stops_fetched": len(bus_stops),
    }

    return geojson


async def _fetch_permits_and_units(state: str, county_fips: str, state_fips: str):
    """Helper: fetch permit history and housing unit count concurrently."""
    import asyncio
    permit_task = census_bps.fetch_permits_by_county(state, county_fips)
    units_task = census_acs.get_county_housing_total(state_fips, county_fips)
    return await asyncio.gather(permit_task, units_task)

