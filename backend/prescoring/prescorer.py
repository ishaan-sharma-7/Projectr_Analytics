"""Pre-score the 20 target universities and write to cache/prescored.json.

Run from the project root:
    python -m backend.prescoring.prescorer

This hits the real APIs (Scorecard, IPEDS, Census BPS, Census ACS, HUD FMR)
and generates Gemini market summaries for each university. Takes ~3-5 minutes.
Results are saved to backend/cache/prescored.json and loaded at server startup.
"""

import asyncio
import json
from pathlib import Path

from backend.adapters import (
    scorecard, ipeds, ipeds_housing, census_bps, census_acs,
    census_acs_extra, rent, fema_disasters, osm_buildings
)
from backend.scoring.pressure import compute_pressure_score
from backend.agent.gemini_agent import generate_gemini_summary
from backend.config import config

# Hardcoded IPEDS unit IDs for universities that the name-search resolves incorrectly.
# Maps display name → (unitid, display_name_override)
UNIT_ID_OVERRIDES: dict[str, int] = {
    "University of Virginia": 234076,
    "University of Florida": 134130,       # search returns USF instead
    "University of Georgia": 139959,       # search returns Georgia State instead
    "Ohio State University": 204796,       # search returns Newark campus instead
    "Texas A&M University": 228723,        # search returns UT Austin instead
    "Pennsylvania State University": 214777,  # search returns Altoona instead
}

# The 20 target universities from the CampusLens roadmap
TARGET_UNIVERSITIES = [
    "Virginia Tech",
    "University of Virginia",
    "University of Tennessee Knoxville",
    "University of North Carolina Chapel Hill",
    "University of Florida",
    "Arizona State University",
    "University of Georgia",
    "Clemson University",
    "North Carolina State University",
    "Boise State University",
    "University of Alabama",
    "University of South Carolina",
    "Ohio State University",
    "Michigan State University",
    "Texas A&M University",
    "Pennsylvania State University",
    "Indiana University Bloomington",
    "University of Kentucky",
    "Mississippi State University",
    "University of Nevada Las Vegas",
]

CACHE_PATH = Path(__file__).resolve().parent.parent / "cache" / "prescored.json"


async def score_one(name: str) -> dict | None:
    print(f"\n[{name}] Resolving...")
    if name in UNIT_ID_OVERRIDES:
        meta_pair = await scorecard.get_university_by_id_with_strength(UNIT_ID_OVERRIDES[name])
    else:
        meta_pair = await scorecard.search_university_with_strength(name)
    if not meta_pair:
        print(f"[{name}] NOT FOUND — skipping")
        return None
    uni, institutional_strength = meta_pair
    print(f"[{name}] Found: {uni.name} ({uni.city}, {uni.state}), unitid={uni.unitid}")

    enrollment_trend = await ipeds.fetch_enrollment_trend(uni.unitid)
    print(f"[{name}] Enrollment: {len(enrollment_trend)} years")

    county_info = await census_bps.fetch_county_fips(uni.lat, uni.lon)
    state_fips = county_info[0] if county_info else ""
    county_fips = county_info[1] if county_info else ""
    print(f"[{name}] County FIPS: {state_fips}{county_fips}")

    permit_history = []
    housing_units = 0
    demographics = None
    disaster_risk = None
    if state_fips and county_fips:
        permit_history, housing_units, demographics, disaster_risk = await asyncio.gather(
            census_bps.fetch_permits_by_county(uni.state, county_fips),
            census_acs.get_county_housing_total(state_fips, county_fips),
            census_acs_extra.fetch_county_demographics(state_fips, county_fips),
            fema_disasters.fetch_disaster_history(state_fips, county_fips, years=10),
        )
    print(f"[{name}] Permits: {sum(p.permits for p in permit_history)} units, Housing: {housing_units:,}")

    fips = f"{state_fips}{county_fips}" if state_fips and county_fips else ""
    rent_history, housing_capacity, existing_housing = await asyncio.gather(
        rent.load_rent_data(uni.city, uni.state, fips),
        ipeds_housing.fetch_housing_capacity(uni.unitid),
        osm_buildings.fetch_buildings(uni.lat, uni.lon, 1.5)
    )
    print(f"[{name}] Rent: {len(rent_history)} data points")

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
    print(f"[{name}] Score: {result.score}/100")

    summary = await generate_gemini_summary(result)
    if summary:
        result = result.model_copy(update={"gemini_summary": summary})
        print(f"[{name}] Gemini summary: {summary[:80]}...")

    return result.model_dump()


async def main():
    print(f"Pre-scoring {len(TARGET_UNIVERSITIES)} universities...")
    print(f"Output: {CACHE_PATH}")
    print(f"Gemini key: {'set' if config.gemini_api_key else 'MISSING'}")
    print("=" * 60)

    results = []
    failed = []

    for name in TARGET_UNIVERSITIES:
        try:
            data = await score_one(name)
            if data:
                results.append(data)
        except Exception as e:
            print(f"[{name}] ERROR: {e}")
            failed.append(name)
        # Small delay to avoid rate limits
        await asyncio.sleep(1)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(results, indent=2, default=str))

    print("\n" + "=" * 60)
    print(f"Done. {len(results)} universities saved to {CACHE_PATH}")
    if failed:
        print(f"Failed: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
