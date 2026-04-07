"""CampusLens FastAPI application.

Endpoints:
  GET  /health              — health check
  POST /score               — compute Housing Pressure Score for a university
  GET  /universities         — list pre-scored universities for the national map
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.config import config
from backend.models.schemas import (
    HousingPressureScore,
    ScoreRequest,
    UniversityListItem,
)
from backend.adapters import scorecard, ipeds, census_bps, census_acs, rent
from backend.scoring.pressure import compute_pressure_score

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

    If the university is pre-scored, returns cached result.
    Otherwise, fetches all data live and computes on-the-fly.
    """
    # ── Check pre-scored cache ──
    if req.unitid and req.unitid in _prescored:
        return _prescored[req.unitid]

    # ── Step 1: Resolve university metadata ──
    if req.unitid:
        uni = await scorecard.get_university_by_id(req.unitid)
    else:
        uni = await scorecard.search_university(req.university_name)

    if not uni:
        raise HTTPException(404, f"University not found: {req.university_name}")

    # Check cache by resolved unitid
    if uni.unitid in _prescored:
        return _prescored[uni.unitid]

    # ── Step 2: Fetch enrollment trend ──
    enrollment_trend = await ipeds.fetch_enrollment_trend(uni.unitid)

    # ── Step 3: Get county FIPS for permit + housing unit lookups ──
    county_info = await census_bps.fetch_county_fips(uni.lat, uni.lon)
    state_fips = county_info[0] if county_info else ""
    county_fips = county_info[1] if county_info else ""

    # ── Step 4: Fetch building permits ──
    permit_history = []
    if state_fips and county_fips:
        permit_history = await census_bps.fetch_permits_by_county(
            uni.state, county_fips,
        )

    # ── Step 5: Fetch housing units ──
    housing_units = 0
    if state_fips and county_fips:
        housing_units = await census_acs.get_county_housing_total(
            state_fips, county_fips,
        )

    # ── Step 6: Fetch rent data ──
    # Pass fips string to rent loader so we can identify the specific county in HUD
    fips = f"{state_fips}{county_fips}" if state_fips and county_fips else ""
    rent_history = await rent.load_rent_data(uni.city, uni.state, fips)

    # ── Step 7: Compute score ──
    result = compute_pressure_score(
        university=uni,
        enrollment_trend=enrollment_trend,
        permit_history=permit_history,
        housing_units=housing_units,
        rent_history=rent_history,
    )

    return result

