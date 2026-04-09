"""Gemini agent for CampusLens — market summary generation and streaming orchestration.

Two responsibilities:

1. generate_gemini_summary(score) — takes an already-computed HousingPressureScore
   and asks Gemini 2.0 Flash to write a 3-sentence plain-English market brief
   in the voice of a student housing analyst speaking to a developer.

2. score_with_streaming(req, prescored, adapters) — async generator used by the
   POST /score/stream SSE endpoint. Runs the full data-fetch pipeline while
   yielding structured log events that the frontend renders as the agent log panel.
   After all data is fetched, calls generate_gemini_summary for the final brief.
"""

import asyncio
import json
from typing import AsyncGenerator

from backend.config import config
from backend.models.schemas import HousingPressureScore, ScoreRequest

# ── System prompt for Gemini market summaries ──
_SUMMARY_SYSTEM_PROMPT = """You are a student housing market analyst writing investment briefs for real estate developers.
Your audience: professionals evaluating new purpose-built student housing development sites.
Your output: exactly 3 sentences. No headers, no bullet points, no markdown.
Sentence 1: Describe the core supply/demand dynamic for this university market.
Sentence 2: Cite the single most important data signal (enrollment growth, rent trajectory, or permit pace).
Sentence 3: State the opportunity or risk for a developer entering this market today — be specific and actionable."""

_SUMMARY_PROMPT_TEMPLATE = """Write a 3-sentence student housing market brief for this university:

University: {name} ({city}, {state})
Housing Pressure Score: {score}/100 ({label})

Key data:
- Enrollment CAGR (5-year): {enrollment_cagr}
- Residential permits filed (5-year, county): {permits_5yr:,} units
- Annual rent growth (3-year avg): {rent_growth}
- Enrollment pressure component: {ep:.0f}/100
- Permit gap component: {pg:.0f}/100
- Rent pressure component: {rp:.0f}/100

Write exactly 3 sentences as described. Be specific, data-driven, and developer-focused."""


def _build_summary_prompt(score: HousingPressureScore) -> str:
    from backend.adapters.ipeds import compute_enrollment_cagr
    from backend.adapters.rent import compute_rent_growth

    cagr = compute_enrollment_cagr(score.enrollment_trend, years=5)
    rent_growth = compute_rent_growth(score.rent_history, years=3)
    permits_5yr = sum(p.permits for p in score.permit_history[-5:])

    label = "High Pressure" if score.score >= 70 else "Emerging" if score.score >= 40 else "Balanced"
    cagr_str = f"{cagr:+.1f}% per year" if cagr is not None else "insufficient data"
    rent_str = f"{rent_growth:+.1f}% per year" if rent_growth is not None else "insufficient data"

    return _SUMMARY_PROMPT_TEMPLATE.format(
        name=score.university.name,
        city=score.university.city,
        state=score.university.state,
        score=score.score,
        label=label,
        enrollment_cagr=cagr_str,
        permits_5yr=permits_5yr,
        rent_growth=rent_str,
        ep=score.components.enrollment_pressure,
        pg=score.components.permit_gap,
        rp=score.components.rent_pressure,
    )


async def generate_gemini_summary(score: HousingPressureScore) -> str:
    """Call Gemini to generate a plain-English 3-sentence market brief.

    Returns empty string if the API key is absent or the call fails.
    The caller should treat an empty string as "summary unavailable" and
    render the side panel without it rather than erroring.
    """
    if not config.gemini_api_key:
        return ""

    try:
        from google import genai  # lazy import — not needed if key absent
        from google.genai import types
    except ImportError:
        print("[Gemini] google-genai not installed. Run: pip install google-genai")
        return ""

    prompt = _build_summary_prompt(score)

    try:
        client = genai.Client(api_key=config.gemini_api_key)
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SUMMARY_SYSTEM_PROMPT,
                # Gemini 2.5 Flash uses internal thinking tokens; set a generous
                # limit so the 3-sentence output isn't truncated.
                max_output_tokens=2048,
                temperature=0.4,
                thinking_config=types.ThinkingConfig(thinking_budget=512),
            ),
        )
        return response.text.strip()
    except Exception as exc:
        print(f"[Gemini] Summary generation failed: {exc}")
        return ""


# ── SSE event helpers ──

def _log_event(message: str) -> str:
    """Format a log-type SSE event."""
    return f"data: {json.dumps({'type': 'log', 'message': message})}\n\n"


def _result_event(score: HousingPressureScore) -> str:
    """Format a result-type SSE event carrying the full score payload."""
    return f"data: {json.dumps({'type': 'result', 'data': score.model_dump()})}\n\n"


def _error_event(message: str) -> str:
    return f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"


async def score_with_streaming(
    req: ScoreRequest,
    prescored: dict,
) -> AsyncGenerator[str, None]:
    """Async generator that runs the full scoring pipeline and streams SSE events.

    Yields SSE-formatted strings:
      - {"type": "log", "message": "..."}  — progress update
      - {"type": "result", "data": {...}}  — final HousingPressureScore
      - {"type": "error", "message": "..."} — fatal error

    This is used by POST /score/stream. The frontend appends each log line to
    the agent log panel and replaces the score display when "result" arrives.

    Args:
        req: ScoreRequest with university_name (and optional unitid).
        prescored: The _prescored dict from main.py (dict[int, HousingPressureScore]).
    """
    # Lazy imports to avoid circular deps at module load
    from backend.adapters import (
        scorecard,
        ipeds,
        ipeds_housing,
        census_bps,
        census_acs,
        census_acs_extra,
        rent,
        fema_disasters,
        osm_buildings,
        master_plans,
        occupancy_ordinances,
    )
    from backend.models.schemas import MasterPlanData, OccupancyOrdinance
    from backend.scoring.pressure import compute_pressure_score

    try:
        # ── Step 1: Resolve university ──
        yield _log_event(f"Resolving university: {req.university_name}...")

        if req.unitid and req.unitid in prescored:
            cached = prescored[req.unitid]
            yield _log_event(f"Found in cache: {cached.university.name}")
            if cached.master_plan is None:
                mp_raw = master_plans.get_planned_beds(cached.university.name)
                if mp_raw:
                    cached = cached.model_copy(update={"master_plan": MasterPlanData(**mp_raw)})
                    prescored[req.unitid] = cached
            if not cached.gemini_summary:
                yield _log_event("Generating Gemini market summary...")
                summary = await generate_gemini_summary(cached)
                cached = cached.model_copy(update={"gemini_summary": summary})
            yield _result_event(cached)
            return

        if req.unitid:
            meta_pair = await scorecard.get_university_by_id_with_strength(req.unitid)
        else:
            meta_pair = await scorecard.search_university_with_strength(req.university_name)

        if not meta_pair:
            yield _error_event(f"University not found: {req.university_name}")
            return
        uni, institutional_strength = meta_pair

        yield _log_event(f"Found: {uni.name} ({uni.city}, {uni.state}) — IPEDS ID {uni.unitid}")
        if institutional_strength is not None:
            ret = institutional_strength.retention_rate
            ret_str = f"{ret*100:.0f}%" if ret is not None else "n/a"
            ownership = institutional_strength.ownership_label or "unknown"
            yield _log_event(
                f"Institutional profile: {ownership}, retention {ret_str}"
            )

        if uni.unitid in prescored:
            cached = prescored[uni.unitid]
            yield _log_event(f"Loaded from pre-scored cache.")
            if cached.master_plan is None:
                mp_raw = master_plans.get_planned_beds(uni.name)
                if mp_raw:
                    cached = cached.model_copy(update={"master_plan": MasterPlanData(**mp_raw)})
                    prescored[uni.unitid] = cached
            if not cached.gemini_summary:
                yield _log_event("Generating Gemini market summary...")
                summary = await generate_gemini_summary(cached)
                cached = cached.model_copy(update={"gemini_summary": summary})
            yield _result_event(cached)
            return

        # ── Step 2: Enrollment ──
        yield _log_event(f"Fetching enrollment trend (2013–2023) from Urban Institute...")
        enrollment_trend = await ipeds.fetch_enrollment_trend(uni.unitid)
        year_range = f"{enrollment_trend[0].year}–{enrollment_trend[-1].year}" if enrollment_trend else "no data"
        yield _log_event(f"Enrollment data: {len(enrollment_trend)} years ({year_range})")

        # ── Step 3: County FIPS ──
        yield _log_event(f"Resolving county FIPS for {uni.city}, {uni.state}...")
        county_info = await census_bps.fetch_county_fips(uni.lat, uni.lon)
        state_fips = county_info[0] if county_info else ""
        county_fips = county_info[1] if county_info else ""
        if county_info:
            yield _log_event(f"County FIPS: {state_fips}{county_fips}")
        else:
            yield _log_event("County FIPS lookup failed — permit data may be unavailable")

        # ── Steps 4–6d: Parallel data fetch ──
        yield _log_event("Fetching market data (permits, housing, rent, demographics, IPEDS, FEMA)...")

        fips = f"{state_fips}{county_fips}" if state_fips and county_fips else ""
        tasks: dict[str, asyncio.Task] = {}

        if state_fips and county_fips:
            tasks["permits"] = asyncio.create_task(
                census_bps.fetch_permits_by_county(uni.state, county_fips)
            )
            tasks["housing_units"] = asyncio.create_task(
                census_acs.get_county_housing_total(state_fips, county_fips)
            )
            tasks["demographics"] = asyncio.create_task(
                census_acs_extra.fetch_county_demographics(state_fips, county_fips)
            )
            tasks["disaster"] = asyncio.create_task(
                fema_disasters.fetch_disaster_history(state_fips, county_fips, years=10)
            )

        tasks["rent"] = asyncio.create_task(
            rent.load_rent_data(uni.city, uni.state, fips)
        )
        tasks["housing_cap"] = asyncio.create_task(
            ipeds_housing.fetch_housing_capacity(uni.unitid)
        )
        tasks["existing_housing"] = asyncio.create_task(
            osm_buildings.fetch_buildings(uni.lat, uni.lon, 1.5)
        )

        # Await all concurrently
        results = {}
        for key, task in tasks.items():
            try:
                results[key] = await task
            except Exception as exc:
                yield _log_event(f"Warning: {key} fetch failed — {exc}")
                results[key] = None

        permit_history = results.get("permits") or []
        housing_units = results.get("housing_units") or 0
        rent_history = results.get("rent") or []
        demographics = results.get("demographics")
        housing_capacity = results.get("housing_cap")
        disaster_risk = results.get("disaster")
        existing_housing = results.get("existing_housing")

        # ── Log results ──
        if permit_history:
            total_permits = sum(p.permits for p in permit_history)
            yield _log_event(f"Permits: {total_permits:,} residential units filed over {len(permit_history)} years")

        if housing_units:
            yield _log_event(f"Housing units in county: {housing_units:,}")

        if rent_history:
            latest_rent = rent_history[-1].median_rent
            yield _log_event(f"Median rent: ${latest_rent:,.0f}/mo ({rent_history[-1].source})")
        else:
            yield _log_event("Rent data unavailable for this market")

        if demographics and demographics.vacancy_rate_pct is not None:
            yield _log_event(
                f"Vacancy rate: {demographics.vacancy_rate_pct:.1f}% — "
                f"renter-occupied {demographics.pct_renter_occupied or 0:.0f}%"
            )

        if housing_capacity:
            yield _log_event(f"Dorm capacity: {housing_capacity.dormitory_capacity:,} beds")

        if disaster_risk:
            yield _log_event(
                f"Disasters: {disaster_risk.total_disasters} total, "
                f"{disaster_risk.weather_disasters} weather-related"
            )

        if existing_housing:
            yield _log_event(
                f"Existing housing footprint: {existing_housing.apartment_buildings} apartment "
                f"+ {existing_housing.dormitory_buildings} dormitory + "
                f"{existing_housing.house_buildings} house buildings within 1.5mi "
                f"({existing_housing.saturation_label} saturation)"
            )

        # ── Step 6f: Master plan lookup ──
        master_plan: MasterPlanData | None = None
        mp_raw = master_plans.get_planned_beds(uni.name)
        if mp_raw:
            master_plan = MasterPlanData(**mp_raw)
            yield _log_event(
                f"Master plan: {master_plan.planned_beds:,} beds planned "
                f"(weighted {master_plan.planned_beds_weighted:,}, horizon {master_plan.horizon_year})"
            )

        # ── Step 6g: Occupancy ordinance lookup ──
        occupancy_ordinance: OccupancyOrdinance | None = None
        occ_raw = occupancy_ordinances.get_ordinance(uni.city, uni.state)
        if occ_raw:
            occupancy_ordinance = OccupancyOrdinance(**occ_raw)
            if occupancy_ordinance.ordinance_type != "none":
                cap_str = (
                    f"≤{occupancy_ordinance.max_unrelated_occupants} unrelated"
                    if occupancy_ordinance.max_unrelated_occupants
                    else "no cap"
                )
                enforced_str = "enforced" if occupancy_ordinance.enforced else "unenforced"
                yield _log_event(
                    f"Occupancy ordinance: {cap_str} ({enforced_str}) — "
                    f"{occupancy_ordinance.pbsh_signal} PBSH signal"
                )

        # ── Step 7: Compute score ──
        yield _log_event("Computing Housing Pressure Score...")
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
        yield _log_event(
            f"Score: {result.score}/100 — "
            f"Enrollment {result.components.enrollment_pressure:.0f} | "
            f"Permit gap {result.components.permit_gap:.0f} | "
            f"Rent {result.components.rent_pressure:.0f}"
        )
        if result.institutional_strength and result.institutional_strength.strength_label:
            yield _log_event(
                f"Institutional strength: {result.institutional_strength.strength_score}/100 "
                f"({result.institutional_strength.strength_label})"
            )

        # ── Step 8: Gemini summary ──
        yield _log_event("Generating Gemini market summary...")
        summary = await generate_gemini_summary(result)
        if summary:
            result = result.model_copy(update={"gemini_summary": summary})
            yield _log_event("Market summary ready.")
        else:
            yield _log_event("Gemini summary unavailable (check GEMINI_API_KEY).")

        yield _result_event(result)

    except Exception as exc:
        yield _error_event(f"Pipeline error: {exc}")
