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
from collections import Counter
from typing import AsyncGenerator

from backend.config import config
from backend.models.schemas import HousingPressureScore, ScoreRequest, ChatMessage

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


# ── Chat agent ──

_CHAT_SYSTEM_PROMPT = """You are an expert student housing market analyst and real estate development advisor embedded in the CampusLens intelligence platform.

You help real estate developers, institutional investors, and housing analysts make data-driven decisions about purpose-built student housing (PBSH) development.

## YOUR CAPABILITIES
- Access detailed housing market data for any scored university in the database
- Analyze H3 hexagonal grid data showing spatial supply/demand patterns around campuses
- Score and analyze new universities not yet in the database (takes ~30 seconds)
- Compare markets across multiple universities
- Discuss specific development sites, parcels, zoning, and buildability at the hex level

## DATA YOU UNDERSTAND

### Housing Pressure Score (0-100)
Composite index of student housing undersupply:
- **Enrollment Pressure** (40% weight): Based on 5-year enrollment CAGR. Higher growth = more demand.
- **Permit Gap** (35% weight): Ratio of new residential permits to existing housing stock. Fewer permits relative to stock = higher gap = more undersupply.
- **Rent Pressure** (25% weight): 3-year average rent growth. Faster rent growth = stronger demand signal.

Score labels: High Pressure (>=70) = strong development opportunity | Emerging (40-69) = moderate | Balanced (<40) = likely saturated

### University-Level Data
Each scored university has: enrollment trends (10+ years from IPEDS), county-level building permits (Census BPS), rent history (ApartmentList + HUD FMR), demographics (Census ACS: income, home values, vacancy rates, renter share, education), on-campus dorm capacity (IPEDS beds-per-student ratio), disaster risk (FEMA declarations), institutional strength (endowment, retention, selectivity: composite 0-100), existing housing stock (OSM building counts and density), master plans (planned on-campus beds, P3 deals, horizon years), and occupancy ordinances (city-level caps on unrelated persons per unit).

### Hex-Level Spatial Data (H3 Grid)
When hex data is loaded for a university, each H3 hex cell around the campus contains:
- **pressure_score** (0-100): Localized demand signal for that specific area
- **development_status**: One of: "Potentially buildable", "Likely off-campus", "Already developed (infill/redevelopment only)", "On-campus constrained", "Hard non-buildable", or "Likely non-buildable (water/land-use constraints)"
- **buildability_score** (0-100): Construction feasibility based on land use, constraints, and zoning
- **transit_label**: "Transit Hub" / "Walkable" / "Isolated"
- **zoning_code / zoning_label / zoning_pbsh_signal**: Municipal zoning district and whether it's favorable for PBSH (positive / neutral / restrictive / constrained / negative)
- **land_parcels**: Vacant or land-dominant parcels with address, acreage, land value, market value, owner name, absentee status, and land use classification
- **coverage_pct**: Land use breakdown (water, wetland, campus, residential built, commercial built, parking, open/recreation)
- **distance_to_campus_miles**: Proximity to campus center
- **bus_stop_count / permit_density / unit_density**: Transit and supply metrics
- **vacant_parcel_count**: Number of developable parcels in the hex

## TOOLS
1. **lookup_university** - Get full market data for any university in the database. Use when the user asks about a university other than the currently selected one, or when comparing markets.
2. **lookup_hex_data** - Get H3 hex grid spatial analysis for a university. Returns development status, buildability, transit, zoning, and land parcels.
3. **score_new_university** - Score a university NOT in the database. Runs the full data pipeline (~30 seconds). Use when asked about an unscored university. Tell the user you're running the analysis.

## ACTIONS
You can select hexes on the user's map by embedding action markers in your response:
- **Select a hex**: Write `[[SELECT_HEX:h3_index]]` (e.g. `[[SELECT_HEX:892a8ac60b3ffff]]`)
  This renders as a clickable badge in the chat. When the user clicks it, that hex gets highlighted on the map with its InfoWindow.
- Use this whenever you recommend a specific hex or development site. Always include the h3_index from the hex data.
- You can include multiple SELECT_HEX markers in one response to highlight several candidates.

## CRITICAL: HEX RECOMMENDATION RULES
When recommending hexes for development, you MUST follow this strict filtering order:
1. **NEVER recommend a hex unless `buildable_for_housing` is true.** Hexes with development_status "Hard non-buildable", "Likely non-buildable", "On-campus constrained", or "Already developed" are OFF LIMITS for new construction. Do not recommend them regardless of their pressure score.
2. **Check zoning first.** A hex with zoning_pbsh_signal "constrained", "negative", or "restrictive" is a poor candidate even if buildable. Prefer hexes with "positive" or "neutral" zoning.
3. **Then check buildability_score.** Higher is better — this accounts for terrain, land use, and zoning feasibility.
4. **Then check pressure_score.** This is demand signal only — a high pressure score on non-buildable land is meaningless.
5. **Prefer hexes with land parcels.** Vacant parcels with absentee owners are the most actionable acquisition targets.
6. **Prefer transit access.** "Transit Hub" > "Walkable" > "Isolated".

A high pressure_score does NOT mean a hex is a good development site. Pressure measures demand, not feasibility. Always lead with buildability and development_status, then layer in demand.

## RESPONSE GUIDELINES
- Be analytical, specific, and data-driven. Reference actual numbers from the data.
- For development questions, discuss specific sites, parcels, zoning, and buildability. USE SELECT_HEX markers so the user can click to see the hex on the map.
- When comparing markets, use lookup_university to fetch data for each one.
- If asked about a university not in the database, IMMEDIATELY use score_new_university — do NOT ask for permission first. Tell the user "I'm analyzing [university name] now — this takes about 30 seconds" and then proceed with the tool call.
- Highlight actionable insights: where to build, what risks exist, regulatory constraints, competitive dynamics.
- When discussing parcels, mention addresses, acreage, owners, and absentee status.
- Be concise but thorough. No filler. Think like a development advisor speaking to a sophisticated investor.
- Use markdown formatting for readability (headers, bold, bullet points) when appropriate."""


def _build_score_snapshot(name: str, score: HousingPressureScore) -> str:
    """Build a comprehensive market data snapshot from a HousingPressureScore."""
    from backend.adapters.ipeds import compute_enrollment_cagr
    from backend.adapters.rent import compute_rent_growth

    cagr = compute_enrollment_cagr(score.enrollment_trend, years=5)
    rent_growth = compute_rent_growth(score.rent_history, years=3)
    permits_5yr = sum(p.permits for p in score.permit_history[-5:]) if score.permit_history else 0

    cagr_str = f"{cagr:+.1f}%" if cagr is not None else "N/A"
    rent_str = f"{rent_growth:+.1f}%" if rent_growth is not None else "N/A"

    enrollment = score.enrollment_trend[-1].total_enrollment if score.enrollment_trend else None
    housing_units = score.nearby_housing_units or None
    beds = score.housing_capacity.dormitory_capacity if score.housing_capacity and score.housing_capacity.dormitory_capacity else None

    beds_ratio = "N/A"
    if beds is not None and enrollment is not None and enrollment > 0:
        beds_ratio = f"{beds / enrollment:.3f}"

    enrollment_str = f"{enrollment:,}" if enrollment is not None else "N/A"
    housing_units_str = f"{housing_units:,}" if housing_units is not None else "N/A"
    beds_str = f"{beds:,}" if beds is not None else "N/A"
    label = "High Pressure" if score.score >= 70 else "Emerging" if score.score >= 40 else "Balanced"

    lines = [
        f"\n=== MARKET DATA: {name} ===",
        f"Location: {score.university.city}, {score.university.state} | IPEDS: {score.university.unitid}",
        f"",
        f"HOUSING PRESSURE SCORE: {score.score:.1f}/100 ({label})",
        f"  Enrollment Pressure: {score.components.enrollment_pressure:.1f}/100 (40% weight)",
        f"  Permit Gap: {score.components.permit_gap:.1f}/100 (35% weight)",
        f"  Rent Pressure: {score.components.rent_pressure:.1f}/100 (25% weight)",
        f"",
        f"KEY METRICS:",
        f"  Enrollment: {enrollment_str} (5yr CAGR: {cagr_str})",
        f"  Residential Permits (5yr total): {permits_5yr:,} units",
        f"  Rent Growth (3yr avg): {rent_str}",
        f"  County Housing Units: {housing_units_str}",
        f"  On-Campus Beds: {beds_str} ({beds_ratio} beds/student)",
    ]

    if score.demographics:
        d = score.demographics
        lines += ["", "DEMOGRAPHICS (Census ACS):"]
        if d.median_household_income:
            lines.append(f"  Median HH Income: ${d.median_household_income:,}")
        if d.median_home_value:
            lines.append(f"  Median Home Value: ${d.median_home_value:,}")
        if d.median_gross_rent:
            lines.append(f"  Median Gross Rent: ${d.median_gross_rent:,}/mo")
        if d.vacancy_rate_pct is not None:
            lines.append(f"  Vacancy Rate: {d.vacancy_rate_pct:.1f}%")
        if d.pct_renter_occupied is not None:
            lines.append(f"  Renter-Occupied: {d.pct_renter_occupied:.1f}%")
        if d.pct_bachelors_or_higher is not None:
            lines.append(f"  Bachelor's+: {d.pct_bachelors_or_higher:.1f}%")
        if d.total_housing_units:
            lines.append(f"  Total Housing Units: {d.total_housing_units:,}")

    if score.housing_capacity:
        hc = score.housing_capacity
        lines += ["", "ON-CAMPUS HOUSING (IPEDS):"]
        lines.append(f"  Dormitory Capacity: {hc.dormitory_capacity:,} beds (year: {hc.year})")
        if hc.typical_room_charge:
            lines.append(f"  Room Charge: ${hc.typical_room_charge:,}/yr")
        if hc.typical_board_charge:
            lines.append(f"  Board Charge: ${hc.typical_board_charge:,}/yr")
        if hc.beds_per_student is not None:
            lines.append(f"  Beds/Student: {hc.beds_per_student:.3f}")

    if score.institutional_strength:
        ist = score.institutional_strength
        lines += ["", "INSTITUTIONAL STRENGTH:"]
        if ist.ownership_label:
            lines.append(f"  Type: {ist.ownership_label}")
        if ist.endowment_end:
            lines.append(f"  Endowment: ${ist.endowment_end:,}")
        if ist.endowment_per_student:
            lines.append(f"  Endowment/Student: ${ist.endowment_per_student:,}")
        if ist.retention_rate is not None:
            lines.append(f"  Retention: {ist.retention_rate*100:.1f}%")
        if ist.admission_rate is not None:
            lines.append(f"  Admission Rate: {ist.admission_rate*100:.1f}%")
        if ist.pell_grant_rate is not None:
            lines.append(f"  Pell Rate: {ist.pell_grant_rate*100:.1f}%")
        if ist.strength_score is not None:
            lines.append(f"  Strength: {ist.strength_score:.0f}/100 ({ist.strength_label or 'N/A'})")

    if score.disaster_risk:
        dr = score.disaster_risk
        lines += ["", f"DISASTER RISK ({dr.window_years}yr):"]
        lines.append(f"  Total: {dr.total_disasters} | Weather: {dr.weather_disasters}")
        if dr.by_type:
            for dtype, count in sorted(dr.by_type.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"    {dtype}: {count}")
        if dr.most_recent_year:
            lines.append(f"  Most Recent: {dr.most_recent_year}")

    if score.existing_housing:
        eh = score.existing_housing
        lines += ["", f"EXISTING HOUSING (OSM, {eh.radius_miles}mi):"]
        lines.append(f"  Apartments: {eh.apartment_buildings} | Dorms: {eh.dormitory_buildings} | Residential: {eh.residential_buildings} | Houses: {eh.house_buildings}")
        lines.append(f"  Total: {eh.total_buildings} | Density: {eh.apartment_density_per_km2:.1f}/km2 | Saturation: {eh.saturation_label}")

    if score.master_plan:
        mp = score.master_plan
        lines += ["", "MASTER PLAN:"]
        lines.append(f"  Planned Beds: {mp.planned_beds:,} (weighted: {mp.planned_beds_weighted:,})")
        if mp.horizon_year:
            lines.append(f"  Horizon: {mp.horizon_year}")
        p3_str = f"Yes — {mp.p3_partner}" if mp.p3_deal and mp.p3_partner else ("Yes" if mp.p3_deal else "No")
        lines.append(f"  P3: {p3_str}")
        lines.append(f"  Confidence: {mp.confidence}")
        if mp.notes:
            lines.append(f"  Notes: {mp.notes}")

    if score.occupancy_ordinance and score.occupancy_ordinance.ordinance_type != "none":
        oo = score.occupancy_ordinance
        lines += ["", "OCCUPANCY ORDINANCE:"]
        lines.append(f"  Type: {oo.ordinance_type}")
        if oo.max_unrelated_occupants:
            lines.append(f"  Max Unrelated: {oo.max_unrelated_occupants}")
        lines.append(f"  Enforced: {'Yes' if oo.enforced else 'No'} | PBSH Signal: {oo.pbsh_signal}")
        if oo.notes:
            lines.append(f"  Notes: {oo.notes}")

    if score.enrollment_trend:
        lines += ["", "ENROLLMENT TREND:"]
        for et in score.enrollment_trend:
            lines.append(f"  {et.year}: {et.total_enrollment:,}")

    if score.permit_history:
        lines += ["", "PERMIT HISTORY:"]
        for ph in score.permit_history:
            lines.append(f"  {ph.year}: {ph.permits:,}")

    if score.rent_history:
        lines += ["", "RENT HISTORY:"]
        for rh in score.rent_history:
            month_str = f"/{rh.month:02d}" if rh.month else ""
            lines.append(f"  {rh.year}{month_str}: ${rh.median_rent:,.0f}/mo ({rh.source})")

    return "\n".join(lines)


def _build_hex_summary(geojson: dict, university_name: str = "") -> str:
    """Build a comprehensive hex grid summary for Gemini context."""
    features = geojson.get("features", [])
    metadata = geojson.get("metadata", {})

    if not features:
        return f"No hex grid data available for {university_name}."

    uni_name = metadata.get("university", university_name)
    scores = [
        f["properties"]["pressure_score"]
        for f in features
        if "pressure_score" in f.get("properties", {})
    ]

    statuses = Counter(
        f["properties"].get("development_status", "Unknown") for f in features
    )
    transit_labels = Counter(
        f["properties"].get("transit_label", "Unknown") for f in features
    )

    buildable = [
        f for f in features if f.get("properties", {}).get("buildable_for_housing")
    ]
    # Sort by buildability first (feasibility), then pressure (demand)
    top_hexes = sorted(
        buildable,
        key=lambda f: (
            f["properties"].get("buildability_score", 0),
            f["properties"]["pressure_score"],
        ),
        reverse=True,
    )[:15]

    lines = [
        f"\n=== HEX GRID: {uni_name} ===",
        f"Radius: {metadata.get('effective_radius_miles', 'N/A')}mi | "
        f"Resolution: {metadata.get('hex_resolution', 9)} | "
        f"Total: {len(features)} hexes",
    ]

    if scores:
        lines += [
            "",
            "PRESSURE SCORE DISTRIBUTION:",
            f"  Mean: {sum(scores)/len(scores):.1f} | Min: {min(scores):.0f} | Max: {max(scores):.0f}",
            f"  High (>=70): {sum(1 for s in scores if s >= 70)} | "
            f"Medium (40-69): {sum(1 for s in scores if 40 <= s < 70)} | "
            f"Low (<40): {sum(1 for s in scores if s < 40)}",
        ]

    lines += ["", "DEVELOPMENT STATUS:"]
    for status, count in sorted(statuses.items(), key=lambda x: -x[1]):
        lines.append(f"  {status}: {count}")

    lines += ["", "TRANSIT ACCESS:"]
    for lbl, count in sorted(transit_labels.items(), key=lambda x: -x[1]):
        lines.append(f"  {lbl}: {count}")

    # Zoning signals
    zoning_signals: Counter = Counter()
    for f in features:
        signal = f.get("properties", {}).get("zoning_pbsh_signal")
        if signal:
            zoning_signals[signal] += 1
    if zoning_signals:
        lines += ["", "ZONING PBSH SIGNALS:"]
        for signal, count in sorted(zoning_signals.items(), key=lambda x: -x[1]):
            lines.append(f"  {signal}: {count}")

    lines.append(f"\nBUILDABLE HEXES: {len(buildable)} of {len(features)}")

    if top_hexes:
        lines += ["", "TOP BUILDABLE HEXES (by buildability, then demand):"]
        for i, f in enumerate(top_hexes, 1):
            p = f["properties"]
            h3_id = p.get("h3_index", "unknown")
            parts = [f"  {i}. h3={h3_id}"]
            parts.append(f"buildability={p.get('buildability_score', 0):.0f}")
            parts.append(f"score={p['pressure_score']:.0f}")
            parts.append(f"dist={p.get('distance_to_campus_miles', 0):.1f}mi")
            parts.append(f"transit={p.get('transit_label', 'N/A')}")
            if p.get("zoning_label"):
                parts.append(
                    f"zoning={p['zoning_label']}({p.get('zoning_pbsh_signal', '?')})"
                )
            if p.get("vacant_parcel_count"):
                parts.append(f"parcels={p['vacant_parcel_count']}")
            if p.get("center_lat") and p.get("center_lng"):
                parts.append(f"@({p['center_lat']:.4f},{p['center_lng']:.4f})")
            lines.append(", ".join(parts))

    # Land parcels across all hexes
    all_parcels: list[dict] = []
    for f in features:
        props = f.get("properties", {})
        for parcel in props.get("land_parcels", []):
            all_parcels.append(
                {
                    **parcel,
                    "hex_score": props.get("pressure_score", 0),
                    "hex_status": props.get("development_status", ""),
                    "hex_dist": props.get("distance_to_campus_miles", 0),
                }
            )

    if all_parcels:
        top_parcels = sorted(
            all_parcels, key=lambda p: p.get("lot_size_acres", 0), reverse=True
        )[:20]
        lines += ["", f"LAND PARCELS ({len(all_parcels)} total, top 20 by size):"]
        for p in top_parcels:
            parts = [f"  {p.get('address', 'Unknown')}"]
            parts.append(f"{p.get('lot_size_acres', 0):.2f}ac")
            parts.append(f"mkt=${p.get('market_value', 0):,.0f}")
            parts.append(f"land=${p.get('land_value', 0):,.0f}")
            parts.append(f"owner={p.get('owner_name', '?')}")
            if p.get("is_absentee"):
                parts.append("ABSENTEE")
            parts.append(f"use={p.get('land_use', '?')}")
            parts.append(
                f"(hex: score={p['hex_score']:.0f}, "
                f"{p['hex_dist']:.1f}mi, {p['hex_status']})"
            )
            lines.append(", ".join(parts))

    return "\n".join(lines)


def _resolve_unitid(
    university_name: str,
    all_scores: dict[int, HousingPressureScore] | None,
) -> int | None:
    """Resolve a university name to a unitid using fuzzy matching."""
    if not all_scores:
        return None
    query = university_name.lower()
    # Exact substring match first
    for uid, s in all_scores.items():
        if query in s.university.name.lower():
            return uid
    # Reverse: full name contains query words
    query_words = set(query.split())
    for uid, s in all_scores.items():
        name_lower = s.university.name.lower()
        if all(w in name_lower for w in query_words):
            return uid
    # Word-overlap match: all query words present in name
    for uid, s in all_scores.items():
        name_words = set(s.university.name.lower().split())
        if query_words and query_words.issubset(name_words):
            return uid
    return None


def _find_hex_for_university(
    university_name: str,
    all_scores: dict[int, HousingPressureScore] | None,
    hex_cache: dict | None,
    unitid: int | None = None,
) -> dict | None:
    """Find hex GeoJSON for a university from the memory cache."""
    if not hex_cache:
        return None

    # Direct unitid lookup (fastest path)
    if unitid is not None:
        for key, data in hex_cache.items():
            if key[0] == unitid:
                return data

    # Resolve unitid from name
    resolved = _resolve_unitid(university_name, all_scores)
    if resolved is not None:
        for key, data in hex_cache.items():
            if key[0] == resolved:
                return data

    # Fallback: search hex cache metadata for university name
    query = university_name.lower()
    for _key, data in hex_cache.items():
        meta = data.get("metadata", {})
        cached_name = meta.get("university", "").lower()
        if cached_name and (query in cached_name or cached_name in query):
            return data
        # Word overlap on metadata name
        if cached_name:
            query_words = set(query.split())
            name_words = set(cached_name.split())
            if query_words and len(query_words & name_words) >= len(query_words) * 0.6:
                return data

    return None


def _build_selected_hex_context(hex_props: dict) -> str:
    """Build context string for the user's currently selected/clicked hex cell."""
    lines = ["\n=== CURRENTLY SELECTED HEX (user is looking at this hex) ==="]

    if hex_props.get("hex_number") is not None:
        lines.append(f"Hex #{hex_props['hex_number']}")
    if hex_props.get("h3_index"):
        lines.append(f"H3 Index: {hex_props['h3_index']}")
    lines.append(f"Pressure Score: {hex_props.get('pressure_score', 'N/A')}/100")
    if hex_props.get("raw_pressure_score") is not None:
        lines.append(f"Raw Pressure Score: {hex_props['raw_pressure_score']}/100")
    lines.append(f"Development Status: {hex_props.get('development_status', 'Unknown')}")
    lines.append(f"Buildable: {'Yes' if hex_props.get('buildable_for_housing') else 'No'}")
    if hex_props.get("buildability_score") is not None:
        lines.append(f"Buildability Score: {hex_props['buildability_score']}/100")
    lines.append(
        f"Distance: {hex_props.get('distance_to_campus_miles', 'N/A')} miles from campus"
    )
    lines.append(f"Transit: {hex_props.get('transit_label', 'N/A')} ({hex_props.get('bus_stop_count', 0)} stops)")
    lines.append(f"Permit Density: {hex_props.get('permit_density', 0):.2f}/km2")
    lines.append(f"Unit Density: {hex_props.get('unit_density', 0):.0f}/km2")

    # Zoning
    if hex_props.get("zoning_code"):
        lines.append(
            f"Zoning: {hex_props['zoning_code']}"
            f" — {hex_props.get('zoning_label', 'N/A')}"
            f" (PBSH signal: {hex_props.get('zoning_pbsh_signal', 'N/A')})"
        )

    # Coverage percentages
    coverage = hex_props.get("coverage_pct")
    if coverage and isinstance(coverage, dict):
        lines.append("Land Use Coverage:")
        for use_type, pct in sorted(coverage.items(), key=lambda x: -x[1]):
            if pct > 0:
                lines.append(f"  {use_type}: {pct:.1f}%")

    # Land parcels
    parcels = hex_props.get("land_parcels", [])
    if parcels:
        lines.append(f"\nLand Parcels in this hex ({len(parcels)}):")
        for p in parcels:
            parts = [f"  {p.get('address', 'Unknown')}"]
            parts.append(f"{p.get('lot_size_acres', 0):.2f}ac")
            parts.append(f"mkt=${p.get('market_value', 0):,.0f}")
            parts.append(f"land=${p.get('land_value', 0):,.0f}")
            parts.append(f"owner={p.get('owner_name', '?')}")
            if p.get("is_absentee"):
                parts.append("ABSENTEE")
            parts.append(f"use={p.get('land_use', '?')}")
            lines.append(", ".join(parts))

    # Classification
    if hex_props.get("classification_reason_codes"):
        lines.append(f"Classification reasons: {', '.join(hex_props['classification_reason_codes'])}")
    if hex_props.get("dominant_land_use"):
        lines.append(f"Dominant land use: {hex_props['dominant_land_use']}")

    return "\n".join(lines)


def _lookup_university_data(
    name: str,
    all_scores: dict[int, HousingPressureScore] | None,
) -> str:
    """Search scored universities by name and return a comprehensive snapshot."""
    if not all_scores:
        return json.dumps({"error": "No university data available in database"})

    uid = _resolve_unitid(name, all_scores)
    if uid is not None:
        score = all_scores[uid]
        return _build_score_snapshot(score.university.name, score)

    return json.dumps(
        {
            "error": f"University '{name}' not found in database. "
            "Use score_new_university to analyze it."
        }
    )


def _lookup_hex_data(
    name: str,
    all_scores: dict[int, HousingPressureScore] | None,
    hex_cache: dict | None,
) -> str:
    """Look up hex grid spatial analysis for a university."""
    geojson = _find_hex_for_university(name, all_scores, hex_cache)
    if geojson:
        return _build_hex_summary(geojson, name)
    return json.dumps(
        {
            "error": f"No hex grid data loaded for '{name}'. "
            "Hex data is generated when viewing a university on the map "
            "at city zoom level."
        }
    )


async def answer_chat_query(
    messages: list[ChatMessage],
    uni_name: str | None,
    active_score: HousingPressureScore | None,
    all_scores: dict[int, "HousingPressureScore"] | None = None,
    hex_cache: dict | None = None,
    score_callback=None,
    selected_hex: dict | None = None,
) -> tuple[str, HousingPressureScore | None]:
    """Answer a chat query with full database access, hex data, and scoring capability."""
    if not config.gemini_api_key:
        return "AI capabilities aren't configured (missing Gemini API key).", None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return "The google-genai package is not installed on the server.", None

    client = genai.Client(api_key=config.gemini_api_key)

    # ── Build system prompt with injected context ──
    system_parts = [_CHAT_SYSTEM_PROMPT]

    if all_scores:
        lines = []
        for uid, s in all_scores.items():
            label = "High" if s.score >= 70 else "Medium" if s.score >= 40 else "Low"
            lines.append(
                f"  - {s.university.name} ({s.university.city}, {s.university.state})"
                f" — {s.score:.0f}/100 [{label}]"
            )
        system_parts.append(
            f"\nUNIVERSITIES IN DATABASE ({len(all_scores)} scored):\n"
            + "\n".join(sorted(lines))
        )

    if uni_name and active_score:
        system_parts.append("\n[CURRENTLY SELECTED UNIVERSITY]")
        system_parts.append(_build_score_snapshot(uni_name, active_score))

    # Auto-include hex data for the currently selected university
    if hex_cache and active_score:
        hex_geojson = _find_hex_for_university(
            uni_name or "",
            all_scores,
            hex_cache,
            unitid=active_score.university.unitid,
        )
        if hex_geojson:
            system_parts.append(_build_hex_summary(hex_geojson, uni_name or ""))
    elif hex_cache and uni_name:
        hex_geojson = _find_hex_for_university(uni_name, all_scores, hex_cache)
        if hex_geojson:
            system_parts.append(_build_hex_summary(hex_geojson, uni_name))

    # Include currently selected hex cell if provided
    if selected_hex:
        system_parts.append(_build_selected_hex_context(selected_hex))

    system_instruction = "\n".join(system_parts)

    # ── Tool definitions ──
    tool_declarations = [
        types.FunctionDeclaration(
            name="lookup_university",
            description=(
                "Look up detailed housing market data for any university in the "
                "CampusLens database. Use when the user asks about a university "
                "other than the currently selected one, or when comparing markets."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "university_name": types.Schema(
                        type=types.Type.STRING,
                        description="Name of the university to look up",
                    ),
                },
                required=["university_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="lookup_hex_data",
            description=(
                "Look up H3 hexagonal grid spatial analysis for a university. "
                "Returns development status, buildability, transit access, zoning, "
                "and land parcel data for hex cells around campus. Only available "
                "for universities whose hex data has been loaded on the map."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "university_name": types.Schema(
                        type=types.Type.STRING,
                        description="Name of the university",
                    ),
                },
                required=["university_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="score_new_university",
            description=(
                "Score and analyze a university that is NOT yet in the database. "
                "Runs the full data pipeline (enrollment, permits, rent, demographics, "
                "housing, institutional data) which takes about 30 seconds. The scored "
                "data is added to the database for future queries. Use when asked about "
                "a university not in the database list."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "university_name": types.Schema(
                        type=types.Type.STRING,
                        description="Full name of the university to score",
                    ),
                },
                required=["university_name"],
            ),
        ),
    ]

    tool_config = types.Tool(function_declarations=tool_declarations)

    contents = []
    for msg in messages:
        gemini_role = "model" if msg.role == "assistant" else msg.role
        contents.append(
            types.Content(
                role=gemini_role, parts=[types.Part.from_text(text=msg.content)]
            )
        )

    gen_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[tool_config],
        temperature=0.4,
    )

    resolved_score: HousingPressureScore | None = None

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=gen_config,
        )

        # Handle function-calling loop (max 8 rounds for multi-step reasoning)
        for _ in range(8):
            candidate = response.candidates[0]
            fn_calls = [p for p in candidate.content.parts if p.function_call]
            if not fn_calls:
                break

            contents.append(candidate.content)

            fn_response_parts = []
            for part in fn_calls:
                fc = part.function_call
                result = ""

                if fc.name == "lookup_university":
                    uni_to_lookup = fc.args.get("university_name", "")
                    result = _lookup_university_data(uni_to_lookup, all_scores)
                    # Track the resolved score so the frontend can add it to the map
                    if all_scores and resolved_score is None:
                        uid = _resolve_unitid(uni_to_lookup, all_scores)
                        if uid is not None:
                            resolved_score = all_scores[uid]
                elif fc.name == "lookup_hex_data":
                    result = _lookup_hex_data(
                        fc.args.get("university_name", ""),
                        all_scores,
                        hex_cache,
                    )
                elif fc.name == "score_new_university":
                    uni_to_score = fc.args.get("university_name", "")
                    if score_callback:
                        try:
                            new_score = await score_callback(uni_to_score)
                            if new_score:
                                resolved_score = new_score
                                result = (
                                    "Successfully scored! Data is now in the database.\n"
                                    + _build_score_snapshot(
                                        new_score.university.name, new_score
                                    )
                                )
                            else:
                                result = json.dumps(
                                    {
                                        "error": f"Could not find or score '{uni_to_score}'. "
                                        "The university may not exist in the College Scorecard database."
                                    }
                                )
                        except Exception as exc:
                            result = json.dumps(
                                {"error": f"Scoring failed: {exc}"}
                            )
                    else:
                        result = json.dumps(
                            {"error": "Scoring capability not available."}
                        )
                else:
                    result = json.dumps({"error": f"Unknown tool: {fc.name}"})

                fn_response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name, response={"result": result}
                    )
                )

            contents.append(types.Content(parts=fn_response_parts))

            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=gen_config,
            )

        return response.text.strip(), resolved_score
    except Exception as exc:
        print(f"[Gemini] Chat exception: {exc}")
        return "I hit a snag processing that. Could you try asking again?", None


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
