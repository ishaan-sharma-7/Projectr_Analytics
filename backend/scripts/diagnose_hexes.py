"""Comprehensive hex diagnostics for all 66 universities.

Checks:
  1. PERFORMANCE — timing for each university's hex endpoint
     - Overpass API response times (8 concurrent queries)
     - Coverage computation time (per-hex sampling)
     - Total cold-start vs cached response time
     - Which phase is the bottleneck per university

  2. QUALITY — hex classification distribution & color regression
     - Label distribution (how many distinct labels/colors)
     - Pressure score spread (min/max/mean/stdev)
     - Development status distribution
     - Stale cache detection (model version mismatch)
     - Low-confidence hex ratio
     - "Two-color problem" detection (like Purdue)

  3. DATA INTEGRITY — sampling accuracy & cache health
     - Coverage ratio statistics per university
     - debug_trace sample_side mismatch detection
     - Cache key version consistency
     - Broken precompute script detection

Run:
    python -m backend.scripts.diagnose_hexes [--live] [--university "Purdue University"]

Flags:
    --live       Hit the actual hex endpoint (requires server running on :8000)
    --university Only diagnose a specific university (can repeat)
    --cache-only Only analyze existing disk cache files (no network)
    --output     Output file path (default: backend/cache/hex_diagnostic_report.json)
    --verbose    Print per-hex details for flagged universities
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.adapters import osm_buildings, osm_transit, national_constraints
from backend.scoring.h3_hex import (
    generate_campus_hex_grid,
    compute_hex_features,
    to_geojson,
    _sample_points_in_polygon,
    _cell_to_boundary,
    _latlng_to_cell,
    _avg_hex_edge_km,
)

# ── All 66 universities ──────────────────────────────────────────────────────
UNIVERSITIES = [
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

RESOLUTION = 9
PROBE_RADIUS = 4.0  # auto_radius probes at max(1.5, 4.0)

# Expected labels for a healthy hex grid (9 labels = 9 colors)
EXPECTED_LABELS = {
    "protected", "campus", "developed", "constrained",
    "zoning_blocked", "prime", "opportunity", "emerging", "open_land",
}


# ── Cache Analysis ────────────────────────────────────────────────────────────

def analyze_cache_file(path: Path) -> dict:
    """Analyze a single hex cache file for quality issues."""
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return {"path": str(path), "error": f"Failed to parse: {exc}"}

    features = data.get("features", [])
    metadata = data.get("metadata", {})
    uni_name = metadata.get("university", path.stem)

    if not features:
        return {
            "university": uni_name,
            "path": str(path),
            "error": "No features in cache file",
            "hex_count": 0,
        }

    # Extract properties from features
    props_list = [f.get("properties", {}) for f in features]

    # Label distribution
    labels = [p.get("label", "unknown") for p in props_list]
    label_counts = dict(Counter(labels))
    unique_labels = set(labels)
    missing_labels = EXPECTED_LABELS - unique_labels
    extra_labels = unique_labels - EXPECTED_LABELS

    # Pressure score distribution
    pressures = [p.get("pressure_score", 0) for p in props_list]
    raw_pressures = [p.get("raw_pressure_score", 0) for p in props_list]

    # Development status distribution
    dev_statuses = [p.get("development_status", "unknown") for p in props_list]
    status_counts = dict(Counter(dev_statuses))

    # Buildability
    buildable_count = sum(1 for p in props_list if p.get("buildable_for_housing"))
    non_buildable_count = len(props_list) - buildable_count

    # Confidence distribution
    confidence_levels = [p.get("classification_confidence", "unknown") for p in props_list]
    confidence_counts = dict(Counter(confidence_levels))
    low_confidence_ratio = confidence_counts.get("low", 0) / max(len(props_list), 1)

    # Coverage ratio statistics
    coverage_keys = ["water", "wetland", "campus", "residential_built",
                     "commercial_built", "parking_infrastructure",
                     "open_recreation", "natural_land"]
    coverage_stats = {}
    for key in coverage_keys:
        values = [p.get("coverage_pct", {}).get(key, 0) for p in props_list]
        if values:
            coverage_stats[key] = {
                "mean": round(statistics.mean(values), 4),
                "max": round(max(values), 4),
                "nonzero_count": sum(1 for v in values if v > 0),
                "nonzero_pct": round(sum(1 for v in values if v > 0) / len(values) * 100, 1),
            }

    # Pressure score analysis
    pressure_stats = {}
    if pressures:
        pressure_stats = {
            "min": round(min(pressures), 1),
            "max": round(max(pressures), 1),
            "mean": round(statistics.mean(pressures), 1),
            "stdev": round(statistics.stdev(pressures), 1) if len(pressures) > 1 else 0,
            "median": round(statistics.median(pressures), 1),
            "p10": round(sorted(pressures)[len(pressures) // 10], 1),
            "p90": round(sorted(pressures)[9 * len(pressures) // 10], 1),
        }

    raw_pressure_stats = {}
    if raw_pressures:
        raw_pressure_stats = {
            "min": round(min(raw_pressures), 1),
            "max": round(max(raw_pressures), 1),
            "mean": round(statistics.mean(raw_pressures), 1),
            "stdev": round(statistics.stdev(raw_pressures), 1) if len(raw_pressures) > 1 else 0,
        }

    # Capped pressure analysis — how much pressure is being suppressed
    capped_hexes = sum(1 for p, r in zip(pressures, raw_pressures) if r > p + 0.5)
    capped_ratio = capped_hexes / max(len(pressures), 1)

    # Transit analysis
    transit_labels = [p.get("transit_label", "unknown") for p in props_list]
    transit_counts = dict(Counter(transit_labels))

    # Distance spread
    distances = [p.get("distance_to_campus_miles", 0) for p in props_list]
    distance_stats = {}
    if distances:
        distance_stats = {
            "min": round(min(distances), 2),
            "max": round(max(distances), 2),
            "mean": round(statistics.mean(distances), 2),
        }

    # Marker density analysis
    total_markers_per_hex = []
    for p in props_list:
        total = (
            p.get("campus_feature_count", 0)
            + p.get("off_campus_housing_count", 0)
            + p.get("development_marker_count", 0)
            + p.get("non_buildable_marker_count", 0)
        )
        total_markers_per_hex.append(total)

    sparse_hexes = sum(1 for m in total_markers_per_hex if m <= 5)
    sparse_ratio = sparse_hexes / max(len(total_markers_per_hex), 1)

    # ── Quality flags ──
    flags = []

    # TWO-COLOR PROBLEM: Purdue-like regression
    if len(unique_labels) <= 2:
        flags.append(f"CRITICAL: Only {len(unique_labels)} label(s): {unique_labels}")
    elif len(unique_labels) <= 3:
        flags.append(f"WARNING: Only {len(unique_labels)} labels: {unique_labels}")

    # No buildable pressure gradient
    buildable_labels = unique_labels & {"prime", "opportunity", "emerging"}
    if len(buildable_labels) <= 1 and buildable_count > 5:
        flags.append(f"REGRESSION: {buildable_count} buildable hexes but only {len(buildable_labels)} pressure tier(s)")

    # Most hexes capped
    if capped_ratio > 0.6:
        flags.append(f"WARNING: {capped_ratio:.0%} of hexes have capped pressure scores")

    # Very low pressure spread
    if pressure_stats and pressure_stats.get("stdev", 0) < 3.0 and len(pressures) > 10:
        flags.append(f"WARNING: Very low pressure spread (stdev={pressure_stats['stdev']})")

    # High sparse ratio
    if sparse_ratio > 0.5:
        flags.append(f"WARNING: {sparse_ratio:.0%} of hexes have ≤5 markers (low confidence)")

    # Low confidence dominant
    if low_confidence_ratio > 0.6:
        flags.append(f"WARNING: {low_confidence_ratio:.0%} of hexes are low-confidence")

    # All same development status
    if len(status_counts) <= 2:
        flags.append(f"WARNING: Only {len(status_counts)} development status(es): {list(status_counts.keys())}")

    # Model version check
    model_version = metadata.get("classification_model_version", "unknown")
    if model_version != "hex_accuracy_v3_0_0":
        flags.append(f"STALE: Model version {model_version} != current hex_accuracy_v3_0_0")

    return {
        "university": uni_name,
        "path": str(path),
        "hex_count": len(features),
        "effective_radius_miles": metadata.get("effective_radius_miles"),
        "base_score": metadata.get("base_score"),
        "model_version": model_version,
        "label_distribution": label_counts,
        "unique_label_count": len(unique_labels),
        "missing_labels": sorted(missing_labels) if missing_labels else [],
        "development_status_counts": status_counts,
        "buildable_count": buildable_count,
        "non_buildable_count": non_buildable_count,
        "pressure_stats": pressure_stats,
        "raw_pressure_stats": raw_pressure_stats,
        "capped_ratio": round(capped_ratio, 3),
        "coverage_stats": coverage_stats,
        "confidence_distribution": confidence_counts,
        "low_confidence_ratio": round(low_confidence_ratio, 3),
        "transit_distribution": transit_counts,
        "distance_stats": distance_stats,
        "sparse_hex_ratio": round(sparse_ratio, 3),
        "marker_count_stats": {
            "mean": round(statistics.mean(total_markers_per_hex), 1) if total_markers_per_hex else 0,
            "max": max(total_markers_per_hex) if total_markers_per_hex else 0,
            "sparse_count": sparse_hexes,
        },
        "data_layer_versions": metadata.get("data_layer_versions", {}),
        "source_completeness": metadata.get("source_completeness", {}),
        "markers_fetched": {
            "bus_stops": metadata.get("bus_stops_fetched", "?"),
            "campus": metadata.get("campus_markers_fetched", "?"),
            "residential": metadata.get("residential_markers_fetched", "?"),
            "non_buildable": metadata.get("non_buildable_markers_fetched", "?"),
            "development": metadata.get("development_markers_fetched", "?"),
            "commercial": metadata.get("commercial_markers_fetched", "?"),
            "parking": metadata.get("parking_markers_fetched", "?"),
            "national_constraints": metadata.get("national_constraint_points_fetched", "?"),
            "zoning": metadata.get("zoning_polygons_fetched", "?"),
            "land_parcels": metadata.get("land_parcels_fetched", "?"),
        },
        "flags": flags,
        "quality_score": _compute_quality_score(
            len(unique_labels), pressure_stats, capped_ratio,
            sparse_ratio, low_confidence_ratio, len(status_counts),
            len(buildable_labels), buildable_count,
        ),
    }


def _compute_quality_score(
    unique_labels: int,
    pressure_stats: dict,
    capped_ratio: float,
    sparse_ratio: float,
    low_confidence_ratio: float,
    status_count: int,
    buildable_label_count: int,
    buildable_count: int,
) -> int:
    """0–100 quality score for hex grid output."""
    score = 100

    # Label diversity (max penalty: -40)
    if unique_labels <= 2:
        score -= 40
    elif unique_labels <= 3:
        score -= 25
    elif unique_labels <= 4:
        score -= 15
    elif unique_labels <= 5:
        score -= 5

    # Pressure gradient in buildable hexes (max penalty: -25)
    if buildable_count > 5:
        if buildable_label_count == 0:
            score -= 25
        elif buildable_label_count == 1:
            score -= 15
        elif buildable_label_count == 2:
            score -= 5

    # Pressure spread (max penalty: -10)
    stdev = pressure_stats.get("stdev", 0)
    if stdev < 2.0:
        score -= 10
    elif stdev < 5.0:
        score -= 5

    # Capped ratio (max penalty: -10)
    if capped_ratio > 0.7:
        score -= 10
    elif capped_ratio > 0.5:
        score -= 5

    # Sparse data (max penalty: -10)
    if sparse_ratio > 0.6:
        score -= 10
    elif sparse_ratio > 0.4:
        score -= 5

    # Low confidence (max penalty: -5)
    if low_confidence_ratio > 0.6:
        score -= 5

    return max(0, score)


# ── Live Performance Test ─────────────────────────────────────────────────────

async def time_overpass_queries(lat: float, lon: float, radius_miles: float) -> dict:
    """Time each Overpass query type individually."""
    timings = {}

    async def _timed(label: str, coro):
        t0 = time.monotonic()
        try:
            result = await coro
            elapsed = time.monotonic() - t0
            count = len(result) if isinstance(result, list) else 0
            timings[label] = {"elapsed_s": round(elapsed, 2), "count": count, "ok": True}
            return result
        except Exception as exc:
            elapsed = time.monotonic() - t0
            timings[label] = {"elapsed_s": round(elapsed, 2), "error": str(exc), "ok": False}
            return []

    # Run all 8 queries concurrently (matching the real endpoint)
    results = await asyncio.gather(
        _timed("bus_stops", osm_transit.fetch_bus_stops(lat, lon, radius_miles)),
        _timed("campus_markers", osm_buildings.fetch_campus_markers(lat, lon, radius_miles)),
        _timed("residential_markers", osm_buildings.fetch_residential_markers(lat, lon, radius_miles)),
        _timed("non_buildable_markers", osm_buildings.fetch_non_buildable_markers(lat, lon, radius_miles)),
        _timed("development_markers", osm_buildings.fetch_development_markers(lat, lon, radius_miles)),
        _timed("commercial_markers", osm_buildings.fetch_commercial_markers(lat, lon, radius_miles)),
        _timed("parking_markers", osm_buildings.fetch_parking_markers(lat, lon, radius_miles)),
        _timed("national_constraints", national_constraints.fetch_national_constraint_points(lat, lon, radius_miles)),
    )

    # Total wall time is the max (since they run concurrently with semaphore=3)
    max_time = max(t["elapsed_s"] for t in timings.values()) if timings else 0
    total_serial = sum(t["elapsed_s"] for t in timings.values())
    timings["_summary"] = {
        "wall_time_s": round(max_time, 2),
        "total_serial_s": round(total_serial, 2),
        "concurrency_factor": round(total_serial / max(max_time, 0.01), 2),
        "failed_count": sum(1 for t in timings.values() if isinstance(t, dict) and not t.get("ok", True)),
    }

    return timings, results


async def full_live_diagnostic(uni: dict, verbose: bool = False) -> dict:
    """Run a full live diagnostic for a single university."""
    name = uni["name"]
    lat = uni["lat"]
    lon = uni["lon"]

    print(f"  [{name}] Starting live diagnostic...")
    result = {"university": name, "lat": lat, "lon": lon}

    # Phase 1: Overpass API timing
    t0 = time.monotonic()
    overpass_timings, (
        bus_stops, campus_markers, residential_markers,
        non_buildable_markers, development_markers,
        commercial_markers, parking_markers, constraint_points,
    ) = await time_overpass_queries(lat, lon, PROBE_RADIUS)
    overpass_wall = time.monotonic() - t0
    result["overpass_timings"] = overpass_timings
    result["overpass_wall_s"] = round(overpass_wall, 2)

    # Phase 2: Effective radius computation
    t1 = time.monotonic()
    from backend.main import _derive_effective_radius_miles
    effective_radius = _derive_effective_radius_miles(
        campus_lat=lat, campus_lng=lon,
        requested_radius_miles=1.5,
        residential_markers=residential_markers,
        non_buildable_markers=non_buildable_markers,
        development_markers=development_markers,
        max_radius_miles=4.5,
    )
    radius_time = time.monotonic() - t1
    result["effective_radius_miles"] = round(effective_radius, 2)
    result["radius_computation_s"] = round(radius_time, 3)

    # Phase 3: Hex grid generation
    t2 = time.monotonic()
    hex_indices = generate_campus_hex_grid(lat, lon, effective_radius, RESOLUTION)
    grid_time = time.monotonic() - t2
    result["hex_count"] = len(hex_indices)
    result["grid_generation_s"] = round(grid_time, 3)

    # Phase 4: Hex feature computation (the heavy part)
    t3 = time.monotonic()
    features = compute_hex_features(
        hex_indices=hex_indices,
        campus_lat=lat, campus_lng=lon,
        base_score=50.0,  # neutral default
        permits_5yr=0,
        housing_units=0,
        radius_miles=effective_radius,
        bus_stops=bus_stops,
        campus_markers=campus_markers,
        residential_markers=residential_markers,
        non_buildable_markers=non_buildable_markers,
        development_markers=development_markers,
        commercial_markers=commercial_markers,
        parking_markers=parking_markers,
        national_constraint_points=constraint_points,
        resolution=RESOLUTION,
    )
    compute_time = time.monotonic() - t3
    result["feature_computation_s"] = round(compute_time, 2)
    result["computation_per_hex_ms"] = round(compute_time / max(len(hex_indices), 1) * 1000, 2)

    # Phase 5: Analyze computed features for quality
    total_time = time.monotonic() - t0
    result["total_cold_start_s"] = round(total_time, 2)

    # Label analysis
    labels = [f.label for f in features]
    label_counts = dict(Counter(labels))
    unique_labels = set(labels)

    pressures = [f.pressure_score for f in features]
    raw_pressures = [f.raw_pressure_score for f in features]
    statuses = [f.development_status for f in features]

    buildable_labels = unique_labels & {"prime", "opportunity", "emerging"}
    buildable_count = sum(1 for f in features if f.buildable_for_housing)
    capped = sum(1 for f in features if f.raw_pressure_score > f.pressure_score + 0.5)

    result["label_distribution"] = label_counts
    result["unique_label_count"] = len(unique_labels)
    result["development_status_counts"] = dict(Counter(statuses))
    result["buildable_count"] = buildable_count
    result["pressure_stats"] = {
        "min": round(min(pressures), 1) if pressures else 0,
        "max": round(max(pressures), 1) if pressures else 0,
        "mean": round(statistics.mean(pressures), 1) if pressures else 0,
        "stdev": round(statistics.stdev(pressures), 1) if len(pressures) > 1 else 0,
    }
    result["capped_ratio"] = round(capped / max(len(features), 1), 3)

    # Marker totals
    result["marker_totals"] = {
        "bus_stops": len(bus_stops),
        "campus": len(campus_markers),
        "residential": len(residential_markers),
        "non_buildable": len(non_buildable_markers),
        "development": len(development_markers),
        "commercial": len(commercial_markers),
        "parking": len(parking_markers),
        "national_constraints": len(constraint_points),
    }

    # Flags
    flags = []
    if len(unique_labels) <= 2:
        flags.append(f"CRITICAL: Only {len(unique_labels)} label(s)")
    elif len(unique_labels) <= 3:
        flags.append(f"WARNING: Only {len(unique_labels)} labels")
    if len(buildable_labels) <= 1 and buildable_count > 5:
        flags.append(f"REGRESSION: {buildable_count} buildable hexes but {len(buildable_labels)} pressure tier(s)")
    if total_time > 40:
        flags.append(f"SLOW: Total cold start {total_time:.1f}s")
    if overpass_wall > 25:
        flags.append(f"OVERPASS_SLOW: Wall time {overpass_wall:.1f}s")
    if compute_time > 10:
        flags.append(f"COMPUTE_SLOW: Feature computation {compute_time:.1f}s")

    result["flags"] = flags

    # Bottleneck analysis
    phases = {
        "overpass_api": overpass_wall,
        "radius_computation": radius_time,
        "grid_generation": grid_time,
        "feature_computation": compute_time,
    }
    bottleneck = max(phases, key=phases.get)
    result["bottleneck"] = bottleneck
    result["phase_breakdown"] = {k: round(v, 2) for k, v in phases.items()}

    print(f"  [{name}] Done in {total_time:.1f}s — {len(unique_labels)} labels, {len(features)} hexes, bottleneck={bottleneck}")
    if flags:
        for flag in flags:
            print(f"    ⚠ {flag}")

    return result


# ── Cache-Only Analysis ───────────────────────────────────────────────────────

def run_cache_analysis(cache_dir: Path, university_filter: list[str] | None = None) -> list[dict]:
    """Analyze all hex cache files on disk."""
    hex_dir = cache_dir / "hex"
    if not hex_dir.exists():
        print(f"Cache directory not found: {hex_dir}")
        return []

    results = []
    for path in sorted(hex_dir.glob("*.json")):
        analysis = analyze_cache_file(path)
        uni_name = analysis.get("university", "")

        # Filter if specified
        if university_filter:
            if not any(f.lower() in uni_name.lower() for f in university_filter):
                continue

        results.append(analysis)

    return results


# ── Report Generation ─────────────────────────────────────────────────────────

def generate_report(results: list[dict], mode: str) -> dict:
    """Generate a summary report from individual university results."""
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "total_universities": len(results),
        "universities": results,
    }

    # Aggregate stats
    flagged = [r for r in results if r.get("flags")]
    critical = [r for r in results if any("CRITICAL" in f for f in r.get("flags", []))]
    regressions = [r for r in results if any("REGRESSION" in f for f in r.get("flags", []))]
    slow = [r for r in results if any("SLOW" in f for f in r.get("flags", []))]

    report["summary"] = {
        "flagged_count": len(flagged),
        "critical_count": len(critical),
        "regression_count": len(regressions),
        "slow_count": len(slow),
        "flagged_universities": [r.get("university", "?") for r in flagged],
        "critical_universities": [r.get("university", "?") for r in critical],
        "regression_universities": [r.get("university", "?") for r in regressions],
    }

    if mode == "live":
        times = [r.get("total_cold_start_s", 0) for r in results if "total_cold_start_s" in r]
        if times:
            report["summary"]["timing"] = {
                "min_s": round(min(times), 1),
                "max_s": round(max(times), 1),
                "mean_s": round(statistics.mean(times), 1),
                "median_s": round(statistics.median(times), 1),
                "p90_s": round(sorted(times)[int(len(times) * 0.9)], 1),
                "over_40s": [r["university"] for r in results if r.get("total_cold_start_s", 0) > 40],
                "over_60s": [r["university"] for r in results if r.get("total_cold_start_s", 0) > 60],
            }
            bottlenecks = Counter(r.get("bottleneck", "?") for r in results)
            report["summary"]["bottleneck_distribution"] = dict(bottlenecks)

    # Quality distribution
    quality_scores = [r.get("quality_score", -1) for r in results if "quality_score" in r]
    if quality_scores:
        report["summary"]["quality"] = {
            "min": min(quality_scores),
            "max": max(quality_scores),
            "mean": round(statistics.mean(quality_scores), 1),
            "below_50": [r["university"] for r in results if r.get("quality_score", 100) < 50],
            "below_70": [r["university"] for r in results if r.get("quality_score", 100) < 70],
        }

    # Label diversity distribution
    label_counts = [r.get("unique_label_count", 0) for r in results if "unique_label_count" in r]
    if label_counts:
        report["summary"]["label_diversity"] = {
            "min_labels": min(label_counts),
            "max_labels": max(label_counts),
            "mean_labels": round(statistics.mean(label_counts), 1),
            "universities_with_2_or_fewer": [
                r["university"] for r in results if r.get("unique_label_count", 99) <= 2
            ],
            "universities_with_3_or_fewer": [
                r["university"] for r in results if r.get("unique_label_count", 99) <= 3
            ],
        }

    return report


# ── Known Code Issues ─────────────────────────────────────────────────────────

def check_code_issues() -> list[dict]:
    """Static analysis of known code issues found during review."""
    issues = []

    # 1. Broken precompute script — check if it can actually import
    precompute_path = PROJECT_ROOT / "backend" / "scripts" / "precompute_hex.py"
    if precompute_path.exists():
        content = precompute_path.read_text()
        # Check for imports from main.py that don't exist there
        main_content = (PROJECT_ROOT / "backend" / "main.py").read_text()
        missing_imports = []
        for fn in ["_hex_disk_cache_path", "_load_hex_disk_cache", "_write_hex_disk_cache"]:
            # Only flag if it's imported FROM main (not defined locally in precompute)
            if f"from backend.main import" in content and fn in content.split("from backend.main import")[1].split(")")[0]:
                if f"def {fn}" not in main_content:
                    missing_imports.append(fn)
        if missing_imports:
            issues.append({
                "severity": "CRITICAL",
                "file": "backend/scripts/precompute_hex.py",
                "issue": f"Imports non-existent functions from main.py: {missing_imports}",
                "impact": "Precompute script cannot run — no background hex caching",
            })

    # 2. debug_trace sample_side mismatch
    h3_hex_path = PROJECT_ROOT / "backend" / "scoring" / "h3_hex.py"
    if h3_hex_path.exists():
        content = h3_hex_path.read_text()
        if 'sample_side=5' in content and '"sample_side": 9' in content:
            issues.append({
                "severity": "WARNING",
                "file": "backend/scoring/h3_hex.py",
                "issue": "debug_trace reports sample_side=9 but actual sampling uses sample_side=5",
                "impact": "Debug output misleading — coverage numbers from 25 samples labeled as 81",
            })

    # 3. Stale cache pollution
    main_path = PROJECT_ROOT / "backend" / "main.py"
    if main_path.exists():
        content = main_path.read_text()
        if "get_hex_any_version" in content and "_register_hex_cache(cache_key, stale_hit" in content:
            issues.append({
                "severity": "HIGH",
                "file": "backend/main.py",
                "issue": "Stale fallback registers old hex data under NEW cache key",
                "impact": "Permanently poisons cache — stale data served as 'current' forever",
            })

    # 4. 5x5 sampling regression
    if h3_hex_path.exists():
        content = h3_hex_path.read_text()
        if 'sample_side=5' in content:
            issues.append({
                "severity": "HIGH",
                "file": "backend/scoring/h3_hex.py",
                "issue": "Sampling reduced from 9x9 (81 pts) to 5x5 (25 pts) — 69% fewer samples",
                "impact": "Coverage ratios are noisier, borderline hexes flip classifications, fewer distinct labels",
            })

    return issues


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="CampusLens hex diagnostic tool")
    parser.add_argument("--live", action="store_true", help="Hit Overpass APIs for live timing + quality")
    parser.add_argument("--university", action="append", help="Filter to specific university (repeatable)")
    parser.add_argument("--cache-only", action="store_true", help="Only analyze disk cache files")
    parser.add_argument("--output", default="backend/cache/hex_diagnostic_report.json", help="Output path")
    parser.add_argument("--verbose", action="store_true", help="Show per-hex details for flagged unis")
    parser.add_argument("--batch-size", type=int, default=2, help="Concurrent universities for live mode")
    parser.add_argument("--batch-sleep", type=float, default=5.0, help="Sleep between batches (Overpass rate limit)")
    args = parser.parse_args()

    cache_dir = Path(PROJECT_ROOT / "backend" / "cache")
    output_path = PROJECT_ROOT / args.output

    print("=" * 70)
    print("CampusLens Hex Diagnostic Tool")
    print("=" * 70)

    # Step 1: Static code analysis
    print("\n── Code Issues ──")
    code_issues = check_code_issues()
    for issue in code_issues:
        print(f"  [{issue['severity']}] {issue['file']}: {issue['issue']}")
        print(f"    Impact: {issue['impact']}")
    if not code_issues:
        print("  No code issues detected.")

    # Step 2: Cache analysis (always runs)
    print(f"\n── Cache Analysis ({cache_dir / 'hex'}) ──")
    cache_results = run_cache_analysis(cache_dir, args.university)
    print(f"  Analyzed {len(cache_results)} cache files.")

    flagged_cache = [r for r in cache_results if r.get("flags")]
    if flagged_cache:
        print(f"  {len(flagged_cache)} flagged:")
        for r in flagged_cache:
            print(f"    {r['university']}: {'; '.join(r['flags'])}")

    # Step 3: Live performance test (if requested)
    live_results = []
    if args.live and not args.cache_only:
        unis = UNIVERSITIES
        if args.university:
            unis = [u for u in UNIVERSITIES if any(f.lower() in u["name"].lower() for f in args.university)]

        print(f"\n── Live Performance Test ({len(unis)} universities) ──")
        print(f"  Batch size: {args.batch_size}, sleep: {args.batch_sleep}s")

        for i in range(0, len(unis), args.batch_size):
            batch = unis[i:i + args.batch_size]
            batch_results = await asyncio.gather(
                *[full_live_diagnostic(u, verbose=args.verbose) for u in batch]
            )
            live_results.extend(batch_results)

            if i + args.batch_size < len(unis):
                print(f"  [batch {i // args.batch_size + 1}] Sleeping {args.batch_sleep}s for rate limit...")
                await asyncio.sleep(args.batch_sleep)

    # Step 4: Generate report
    all_results = live_results if live_results else cache_results
    mode = "live" if live_results else "cache"
    report = generate_report(all_results, mode)
    report["code_issues"] = code_issues

    # If we have cache results alongside live, include cache analysis
    if live_results and cache_results:
        report["cache_analysis"] = generate_report(cache_results, "cache")

    # Write report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2))
    print(f"\n── Report written to {output_path} ──")

    # Print summary
    summary = report.get("summary", {})
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Total universities analyzed: {report['total_universities']}")
    print(f"  Flagged:    {summary.get('flagged_count', 0)}")
    print(f"  Critical:   {summary.get('critical_count', 0)}")
    print(f"  Regressions: {summary.get('regression_count', 0)}")

    if "timing" in summary:
        t = summary["timing"]
        print(f"\n  Timing:")
        print(f"    Mean:   {t['mean_s']}s")
        print(f"    Median: {t['median_s']}s")
        print(f"    P90:    {t['p90_s']}s")
        print(f"    Max:    {t['max_s']}s")
        if t.get("over_40s"):
            print(f"    Over 40s: {', '.join(t['over_40s'])}")

    if "quality" in summary:
        q = summary["quality"]
        print(f"\n  Quality Scores:")
        print(f"    Mean: {q['mean']}/100")
        print(f"    Min:  {q['min']}/100")
        if q.get("below_50"):
            print(f"    Below 50: {', '.join(q['below_50'])}")

    if "label_diversity" in summary:
        ld = summary["label_diversity"]
        print(f"\n  Label Diversity:")
        print(f"    Mean labels: {ld['mean_labels']}")
        if ld.get("universities_with_2_or_fewer"):
            print(f"    ≤2 labels (CRITICAL): {', '.join(ld['universities_with_2_or_fewer'])}")
        if ld.get("universities_with_3_or_fewer"):
            print(f"    ≤3 labels (WARNING):  {', '.join(ld['universities_with_3_or_fewer'])}")

    if code_issues:
        print(f"\n  Code Issues: {len(code_issues)}")
        for issue in code_issues:
            print(f"    [{issue['severity']}] {issue['issue']}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
