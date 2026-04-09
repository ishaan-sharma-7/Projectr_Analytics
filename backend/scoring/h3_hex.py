"""H3 hexagonal grid generation for CampusLens city-level choropleth.

Generates a hex grid (default H3 resolution 9) centered on a
university campus. Each hex is assigned a pressure score based on:
  - Proximity to campus (distance decay)
  - Base Housing Pressure Score from the university-level calculation
  - Permit density distribution (closer to campus = higher expected density)

Returns a GeoJSON FeatureCollection ready for Google Maps Data Layer.

H3 v3/v4 compatibility: auto-detects installed version.
"""

import math
from dataclasses import dataclass
from typing import Literal

import h3

# ── H3 version compatibility ──
try:
    # h3 v4 API
    h3.latlng_to_cell  # AttributeError if v3
    def _latlng_to_cell(lat: float, lng: float, res: int) -> str:
        return h3.latlng_to_cell(lat, lng, res)
    def _grid_disk(h: str, k: int) -> set:
        return h3.grid_disk(h, k)
    def _cell_to_latlng(h: str) -> tuple[float, float]:
        return h3.cell_to_latlng(h)
    def _cell_to_boundary(h: str) -> tuple:
        return h3.cell_to_boundary(h)
except AttributeError:
    # h3 v3 API
    def _latlng_to_cell(lat: float, lng: float, res: int) -> str:
        return h3.geo_to_h3(lat, lng, res)
    def _grid_disk(h: str, k: int) -> set:
        return h3.k_ring(h, k)
    def _cell_to_latlng(h: str) -> tuple[float, float]:
        return h3.h3_to_geo(h)
    def _cell_to_boundary(h: str) -> tuple:
        return h3.h3_to_geo_boundary(h)

def _avg_hex_edge_km(resolution: int) -> float:
    """Average H3 edge length in km for a given resolution."""
    try:
        return float(h3.average_hexagon_edge_length(resolution, unit="km"))  # h3 v4
    except AttributeError:
        return float(h3.edge_length(resolution, unit="km"))  # h3 v3


def _avg_hex_area_km2(resolution: int) -> float:
    """Average H3 hexagon area in km² for a given resolution."""
    try:
        return float(h3.average_hexagon_area(resolution, unit="km^2"))  # h3 v4
    except AttributeError:
        if hasattr(h3, "hex_area"):
            return float(h3.hex_area(resolution, unit="km^2"))  # h3 v3
        # Best-effort fallback for older mixed bindings.
        return float(h3.average_hexagon_area(resolution, unit="km^2"))


@dataclass
class HexFeature:
    hex_number: int
    h3_index: str
    center_lat: float
    center_lng: float
    boundary: list[list[float]]  # GeoJSON [[lng, lat], ...] closed ring
    distance_km: float
    distance_to_campus_miles: float
    pressure_score: float
    raw_pressure_score: float
    permit_density: float        # estimated permits per km²
    unit_density: float          # estimated housing units per km²
    bus_stop_count: int          # OSM transit nodes whose H3 cell == this hex
    campus_feature_count: int    # OSM campus/education markers inside this hex
    dormitory_count: int         # subset of campus_feature_count tagged dormitory
    off_campus_housing_count: int  # apartments/residential/house markers
    development_marker_count: int  # existing built structures (all building tags)
    already_developed_for_housing: bool  # redevelopment-only signal
    campus_share: float          # campus marker share of land-use markers
    non_buildable_marker_count: int  # non-buildable land-use markers in hex
    water_marker_count: int      # water/wetland markers in hex
    wetland_marker_count: int    # explicit wetland markers in hex
    golf_marker_count: int       # golf-course markers in hex
    forest_marker_count: int     # forest/wood markers in hex
    field_marker_count: int      # athletic field markers in hex
    buildable_for_housing: bool  # False when hex is likely not developable
    buildability_score: float    # 0–100 feasibility score (higher = better)
    on_campus_constrained: bool  # True when likely campus-controlled land
    development_status: str      # includes campus/non-buildable/off-campus statuses
    coverage_pct: dict[str, float]  # per-category hex coverage ratios (0–1)
    classification_reason_codes: list[str]
    dominant_land_use: str
    classification_confidence: Literal["high", "medium", "low"]
    debug_trace: dict[str, object]
    transit_label: str           # "Transit Hub" | "Walkable" | "Isolated"
    label: str                   # "high" | "medium" | "low"


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def _point_in_polygon(lat: float, lng: float, polygon_latlng: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test for (lat, lng)."""
    if len(polygon_latlng) < 3:
        return False

    inside = False
    j = len(polygon_latlng) - 1
    for i, (ilat, ilng) in enumerate(polygon_latlng):
        jlat, jlng = polygon_latlng[j]
        intersects = ((ilng > lng) != (jlng > lng)) and (
            lat < (jlat - ilat) * (lng - ilng) / max(1e-12, (jlng - ilng)) + ilat
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _sample_points_in_polygon(
    polygon_latlng: list[tuple[float, float]],
    sample_side: int = 9,
) -> list[tuple[float, float]]:
    """Deterministic interior sampling points over a polygon envelope."""
    if not polygon_latlng:
        return []

    lats = [p[0] for p in polygon_latlng]
    lngs = [p[1] for p in polygon_latlng]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)

    samples: list[tuple[float, float]] = []
    for i in range(sample_side):
        for j in range(sample_side):
            lat = min_lat + ((i + 0.5) / sample_side) * (max_lat - min_lat)
            lng = min_lng + ((j + 0.5) / sample_side) * (max_lng - min_lng)
            if _point_in_polygon(lat, lng, polygon_latlng):
                samples.append((lat, lng))

    if samples:
        return samples

    # Fallback to centroid when tiny polygons miss grid cells.
    return [(sum(lats) / len(lats), sum(lngs) / len(lngs))]


def _marker_coverage_ratio(
    samples: list[tuple[float, float]],
    candidate_markers: list[tuple[float, float]],
    radius_km: float,
) -> float:
    """Estimate category coverage as sample-hit ratio within marker radius."""
    if not samples or not candidate_markers:
        return 0.0
    hit_count = 0
    for slat, slng in samples:
        covered = False
        for mlat, mlng in candidate_markers:
            if _haversine_km(slat, slng, mlat, mlng) <= radius_km:
                covered = True
                break
        if covered:
            hit_count += 1
    return hit_count / len(samples)


def _bucket_marker_points(
    markers: list[tuple[float, float, str]] | None,
    accepted_kinds: set[str],
    resolution: int,
) -> dict[str, list[tuple[float, float]]]:
    """Bucket marker points by H3 cell for local candidate lookup."""
    bucket: dict[str, list[tuple[float, float]]] = {}
    if not markers:
        return bucket
    for lat, lng, kind in markers:
        if kind not in accepted_kinds:
            continue
        cell = _latlng_to_cell(lat, lng, resolution)
        bucket.setdefault(cell, []).append((lat, lng))
    return bucket


def _neighbor_bucket_points(
    bucket: dict[str, list[tuple[float, float]]],
    hex_id: str,
    rings: int = 1,
) -> list[tuple[float, float]]:
    """Return marker points from a hex and nearby rings."""
    if not bucket:
        return []
    pts: list[tuple[float, float]] = []
    for cell in _grid_disk(hex_id, rings):
        pts.extend(bucket.get(cell, []))
    return pts


HARD_WATER_THRESHOLD = 0.14
HARD_WETLAND_THRESHOLD = 0.12
HARD_COMBINED_THRESHOLD = 0.30
HARD_FLOODPLAIN_MARKERS = 2
HARD_HYDRO_MIX_THRESHOLD = 0.12
HARD_HYDRO_MIN_MARKERS = 6

CAMPUS_COVERAGE_THRESHOLD = 0.18
CAMPUS_SHARE_THRESHOLD = 0.58
CAMPUS_DISTANCE_MILES = 1.35
CAMPUS_MIN_MARKERS = 4

DEVELOPED_BUILT_COVERAGE_THRESHOLD = 0.34
DEVELOPED_COMMERCIAL_THRESHOLD = 0.15
DEVELOPED_DENSITY_THRESHOLD = 110.0
DEVELOPED_STRUCTURE_MARKERS = 16
DEVELOPED_MIXED_MARKERS = 10


def _classify_development_status(
    *,
    coverage_pct: dict[str, float],
    distance_miles: float,
    campus_share: float,
    campus_feature_count: int,
    dormitory_count: int,
    off_campus_housing_count: int,
    development_marker_count: int,
    commercial_marker_count: int,
    water_marker_count: int,
    wetland_marker_count: int,
    floodplain_marker_count: int,
    golf_marker_count: int,
    field_marker_count: int,
    park_marker_count: int,
    development_density: float,
) -> tuple[str, bool, bool, bool, list[str], float, dict[str, bool]]:
    """Classify a hex into one status using strict precedence rules."""
    built_total_coverage = (
        coverage_pct["residential_built"]
        + coverage_pct["commercial_built"]
        + coverage_pct["parking_infrastructure"]
    )
    hard_non_buildable_coverage = (
        coverage_pct["water"]
        + coverage_pct["wetland"]
        + coverage_pct["open_recreation"]
    )

    hard_non_buildable = (
        coverage_pct["water"] >= HARD_WATER_THRESHOLD
        or coverage_pct["wetland"] >= HARD_WETLAND_THRESHOLD
        or hard_non_buildable_coverage >= HARD_COMBINED_THRESHOLD
        or floodplain_marker_count >= HARD_FLOODPLAIN_MARKERS
        or water_marker_count >= 10
        or wetland_marker_count >= 8
        or golf_marker_count >= 12
        or (golf_marker_count + field_marker_count + park_marker_count) >= 20
        or (
            (coverage_pct["water"] + coverage_pct["wetland"]) >= HARD_HYDRO_MIX_THRESHOLD
            and (water_marker_count + wetland_marker_count) >= HARD_HYDRO_MIN_MARKERS
        )
    )
    campus_constrained = (
        coverage_pct["campus"] >= CAMPUS_COVERAGE_THRESHOLD
        or (
            distance_miles <= CAMPUS_DISTANCE_MILES
            and campus_share >= CAMPUS_SHARE_THRESHOLD
            and campus_feature_count >= CAMPUS_MIN_MARKERS
        )
        or (distance_miles <= 1.6 and campus_feature_count >= 14)
    )
    already_developed = (
        built_total_coverage >= DEVELOPED_BUILT_COVERAGE_THRESHOLD
        or coverage_pct["commercial_built"] >= DEVELOPED_COMMERCIAL_THRESHOLD
        or (
            coverage_pct["residential_built"] >= 0.24
            and coverage_pct["commercial_built"] >= 0.08
        )
        or development_density >= DEVELOPED_DENSITY_THRESHOLD
        or off_campus_housing_count >= 14
        or (
            development_marker_count >= DEVELOPED_STRUCTURE_MARKERS
            and (off_campus_housing_count + commercial_marker_count) >= DEVELOPED_MIXED_MARKERS
        )
    )
    decision_flags = {
        "hard_non_buildable": hard_non_buildable,
        "campus_constrained": campus_constrained,
        "already_developed": already_developed,
    }

    classification_reason_codes: list[str] = []
    if hard_non_buildable:
        if coverage_pct["water"] >= HARD_WATER_THRESHOLD:
            classification_reason_codes.append("water_majority")
        if coverage_pct["wetland"] >= HARD_WETLAND_THRESHOLD:
            classification_reason_codes.append("wetland_majority")
        if floodplain_marker_count >= HARD_FLOODPLAIN_MARKERS:
            classification_reason_codes.append("floodplain_major")
        if coverage_pct["open_recreation"] >= 0.30:
            classification_reason_codes.append("open_recreation_major")
        if golf_marker_count >= 12:
            classification_reason_codes.append("golf_course_dominant")
        return (
            "Hard non-buildable",
            False,
            False,
            False,
            classification_reason_codes,
            8.0,
            decision_flags,
        )

    if campus_constrained:
        classification_reason_codes.append("campus_dominant")
        if dormitory_count >= 1:
            classification_reason_codes.append("dormitory_present")
        return (
            "On-campus constrained",
            False,
            False,
            True,
            classification_reason_codes,
            14.0,
            decision_flags,
        )

    if already_developed:
        if coverage_pct["commercial_built"] >= DEVELOPED_COMMERCIAL_THRESHOLD:
            classification_reason_codes.append("commercial_dense")
        if coverage_pct["residential_built"] >= 0.30:
            classification_reason_codes.append("residential_dense")
        if coverage_pct["parking_infrastructure"] >= 0.18:
            classification_reason_codes.append("parking_dense")
        return (
            "Already developed (infill/redevelopment only)",
            False,
            True,
            False,
            classification_reason_codes,
            22.0,
            decision_flags,
        )

    classification_reason_codes.append("limited_constraints")
    return (
        "Potentially buildable",
        True,
        False,
        False,
        classification_reason_codes,
        100.0,
        decision_flags,
    )


def _radius_to_k(radius_km: float, resolution: int) -> int:
    """Number of hex rings needed to cover a given radius at a resolution.

    Each ring adds approximately one average edge length of coverage.
    Add 1 extra ring as buffer.
    """
    edge_km = max(_avg_hex_edge_km(resolution), 0.05)
    k = math.ceil(radius_km / edge_km) + 1
    return max(2, min(k, 25))


def generate_campus_hex_grid(
    campus_lat: float,
    campus_lng: float,
    radius_miles: float = 1.5,
    resolution: int = 9,
) -> list[str]:
    """Return H3 cell indices covering a radius around campus.

    Args:
        campus_lat: Campus latitude.
        campus_lng: Campus longitude.
        radius_miles: Search radius in miles.
        resolution: H3 resolution (default 9 for finer per-hex granularity).

    Returns:
        List of H3 cell index strings within the radius.
    """
    radius_km = radius_miles * 1.60934
    k = _radius_to_k(radius_km, resolution)

    center_hex = _latlng_to_cell(campus_lat, campus_lng, resolution)
    candidate_hexes = _grid_disk(center_hex, k)

    result: list[str] = []
    for hex_id in candidate_hexes:
        c_lat, c_lng = _cell_to_latlng(hex_id)
        if _haversine_km(campus_lat, campus_lng, c_lat, c_lng) <= radius_km:
            result.append(hex_id)

    return result


def compute_hex_features(
    hex_indices: list[str],
    campus_lat: float,
    campus_lng: float,
    base_score: float,
    permits_5yr: int,
    housing_units: int,
    radius_miles: float = 1.5,
    bus_stops: list[tuple[float, float]] | None = None,
    campus_markers: list[tuple[float, float, str]] | None = None,
    residential_markers: list[tuple[float, float, str]] | None = None,
    non_buildable_markers: list[tuple[float, float, str]] | None = None,
    development_markers: list[tuple[float, float, str]] | None = None,
    commercial_markers: list[tuple[float, float, str]] | None = None,
    parking_markers: list[tuple[float, float, str]] | None = None,
    national_constraint_points: list[tuple[float, float, str]] | None = None,
    resolution: int = 9,
) -> list[HexFeature]:
    """Compute pressure features for each hex in the grid.

    Pressure is highest at the campus core and decays toward the radius edge.
    Permit and unit density are spatially distributed using proximity weighting
    (student housing activity concentrates near campus).

    Transit access (``bus_stops``) is layered on top: hexes that contain at
    least one OSM transit node get a small pressure boost, modelling the fact
    that an apartment two miles out on a dedicated bus route effectively
    behaves like one a few blocks from campus.

    Args:
        hex_indices: H3 cell indices from generate_campus_hex_grid.
        campus_lat / campus_lng: Campus coordinates.
        base_score: University-level Housing Pressure Score (0–100).
        permits_5yr: Total residential permits filed in county over 5 years.
        housing_units: Total housing units in county from ACS.
        radius_miles: Max radius (for normalization).
        bus_stops: Optional list of (lat, lon) for OSM transit nodes nearby.
        campus_markers: Optional list of (lat, lon, kind) where kind is
            "dormitory" or "campus" from OSM campus land-use tagging.
        residential_markers: Optional list of (lat, lon, building) where
            building comes from OSM residential building tags.
        non_buildable_markers: Optional list of (lat, lon, kind) where kind
            includes water|golf_course|field|forest|park|protected|restricted|
            infrastructure.
        development_markers: Optional list of (lat, lon, kind) where kind is
            "structure" or "minor" from generic building-tag extraction.
        commercial_markers: Optional list of (lat, lon, kind) for commercial
            footprints/POIs ("commercial").
        parking_markers: Optional list of (lat, lon, kind) for parking-heavy
            built land ("parking").
        national_constraint_points: Optional list of (lat, lon, kind) from
            U.S.-wide overlays such as wetland/floodplain layers.
        resolution: H3 resolution to use when bucketing bus stops into hexes.

    Returns:
        List of HexFeature, sorted by distance from campus.
    """
    radius_km = radius_miles * 1.60934
    hex_area_km2 = _avg_hex_area_km2(resolution)

    # First pass: compute proximity factors for spatial weighting
    hex_distances: dict[str, float] = {}
    for hex_id in hex_indices:
        c_lat, c_lng = _cell_to_latlng(hex_id)
        hex_distances[hex_id] = _haversine_km(campus_lat, campus_lng, c_lat, c_lng)

    proximities = {
        h: max(0.0, 1.0 - (d / radius_km))
        for h, d in hex_distances.items()
    }
    total_proximity = sum(proximities.values()) or 1.0

    # ── Bucket bus stops into hex cells at the same resolution ──
    bus_stop_counts: dict[str, int] = {}
    campus_marker_counts: dict[str, int] = {}
    dormitory_counts: dict[str, int] = {}
    off_campus_housing_counts: dict[str, int] = {}
    development_counts: dict[str, int] = {}
    water_counts: dict[str, int] = {}
    wetland_counts: dict[str, int] = {}
    golf_counts: dict[str, int] = {}
    forest_counts: dict[str, int] = {}
    field_counts: dict[str, int] = {}
    park_counts: dict[str, int] = {}
    protected_counts: dict[str, int] = {}
    infrastructure_counts: dict[str, int] = {}
    restricted_counts: dict[str, int] = {}
    commercial_counts: dict[str, int] = {}
    parking_counts: dict[str, int] = {}
    floodplain_counts: dict[str, int] = {}
    if bus_stops:
        hex_set = set(hex_indices)
        for slat, slng in bus_stops:
            cell = _latlng_to_cell(slat, slng, resolution)
            if cell in hex_set:
                bus_stop_counts[cell] = bus_stop_counts.get(cell, 0) + 1
    else:
        hex_set = set(hex_indices)

    # ── Bucket campus-control markers into hex cells ──
    if campus_markers:
        for mlat, mlng, kind in campus_markers:
            cell = _latlng_to_cell(mlat, mlng, resolution)
            if cell not in hex_set:
                continue
            campus_marker_counts[cell] = campus_marker_counts.get(cell, 0) + 1
            if kind == "dormitory":
                dormitory_counts[cell] = dormitory_counts.get(cell, 0) + 1

    # ── Bucket residential markers for mixed-use checks ──
    if residential_markers:
        for mlat, mlng, building in residential_markers:
            cell = _latlng_to_cell(mlat, mlng, resolution)
            if cell not in hex_set:
                continue
            if building in {"apartments", "residential", "house"}:
                off_campus_housing_counts[cell] = off_campus_housing_counts.get(cell, 0) + 1

    # ── Bucket existing development markers ──
    if development_markers:
        for mlat, mlng, kind in development_markers:
            if kind != "structure":
                continue
            cell = _latlng_to_cell(mlat, mlng, resolution)
            if cell not in hex_set:
                continue
            development_counts[cell] = development_counts.get(cell, 0) + 1

    # ── Bucket non-buildable land-use markers ──
    if non_buildable_markers:
        for mlat, mlng, kind in non_buildable_markers:
            cell = _latlng_to_cell(mlat, mlng, resolution)
            if cell not in hex_set:
                continue
            if kind == "water":
                water_counts[cell] = water_counts.get(cell, 0) + 1
            elif kind == "wetland":
                wetland_counts[cell] = wetland_counts.get(cell, 0) + 1
            elif kind == "golf_course":
                golf_counts[cell] = golf_counts.get(cell, 0) + 1
            elif kind == "forest":
                forest_counts[cell] = forest_counts.get(cell, 0) + 1
            elif kind == "field":
                field_counts[cell] = field_counts.get(cell, 0) + 1
            elif kind == "park":
                park_counts[cell] = park_counts.get(cell, 0) + 1
            elif kind == "protected":
                protected_counts[cell] = protected_counts.get(cell, 0) + 1
            elif kind == "infrastructure":
                infrastructure_counts[cell] = infrastructure_counts.get(cell, 0) + 1
            elif kind == "restricted":
                restricted_counts[cell] = restricted_counts.get(cell, 0) + 1

    if commercial_markers:
        for mlat, mlng, _kind in commercial_markers:
            cell = _latlng_to_cell(mlat, mlng, resolution)
            if cell not in hex_set:
                continue
            commercial_counts[cell] = commercial_counts.get(cell, 0) + 1

    if parking_markers:
        for mlat, mlng, _kind in parking_markers:
            cell = _latlng_to_cell(mlat, mlng, resolution)
            if cell not in hex_set:
                continue
            parking_counts[cell] = parking_counts.get(cell, 0) + 1

    if national_constraint_points:
        for mlat, mlng, kind in national_constraint_points:
            cell = _latlng_to_cell(mlat, mlng, resolution)
            if cell not in hex_set:
                continue
            if kind == "wetland":
                wetland_counts[cell] = wetland_counts.get(cell, 0) + 1
            elif kind == "floodplain":
                floodplain_counts[cell] = floodplain_counts.get(cell, 0) + 1
            elif kind == "water":
                water_counts[cell] = water_counts.get(cell, 0) + 1

    water_bucket = _bucket_marker_points(non_buildable_markers, {"water"}, resolution)
    wetland_bucket = _bucket_marker_points(non_buildable_markers, {"wetland"}, resolution)
    campus_bucket = _bucket_marker_points(campus_markers, {"campus", "dormitory"}, resolution)
    residential_bucket = _bucket_marker_points(
        residential_markers,
        {"apartments", "residential", "house", "dormitory"},
        resolution,
    )
    commercial_bucket = _bucket_marker_points(commercial_markers, {"commercial"}, resolution)
    parking_bucket = _bucket_marker_points(parking_markers, {"parking"}, resolution)
    infrastructure_bucket = _bucket_marker_points(
        non_buildable_markers,
        {"infrastructure", "restricted"},
        resolution,
    )
    open_recreation_bucket = _bucket_marker_points(
        non_buildable_markers,
        {"golf_course", "field", "park"},
        resolution,
    )
    national_water_bucket = _bucket_marker_points(national_constraint_points, {"water"}, resolution)
    national_wetland_bucket = _bucket_marker_points(
        national_constraint_points,
        {"wetland", "floodplain"},
        resolution,
    )

    features: list[HexFeature] = []
    for hex_id in hex_indices:
        c_lat, c_lng = _cell_to_latlng(hex_id)
        distance_km = hex_distances[hex_id]
        distance_miles = distance_km * 0.621371
        proximity = proximities[hex_id]
        raw_boundary = _cell_to_boundary(hex_id)
        polygon_latlng = [(float(lat), float(lng)) for lat, lng in raw_boundary]

        # ── Spatial distribution of permits and housing units ──
        # Weight this hex by its share of total proximity (closer → more weight)
        proximity_share = proximity / total_proximity

        # Permit density: permits attributed to this hex / hex area
        hex_permits = permits_5yr * proximity_share
        permit_density = round(hex_permits / hex_area_km2, 2)

        # Unit density: total county units spread uniformly (we lack tract resolution)
        unit_density = round(
            (housing_units / max(len(hex_indices), 1)) / hex_area_km2, 2
        ) if housing_units > 0 else 0.0

        # ── Hex pressure score (raw demand signal) ──
        # Near-campus hexes inherit more of the base score.
        # Formula: score scales linearly from base_score (at campus) to
        # base_score * 0.4 (at radius edge), creating a visible gradient.
        hex_pressure = base_score * (0.4 + 0.6 * proximity)

        # ── Transit boost ──
        # Hexes with concentrated transit get a pressure bump because students
        # will rent there even at distance. Cap the boost so it can't overpower
        # the geometric gradient entirely.
        stop_count = bus_stop_counts.get(hex_id, 0)
        transit_boost = 0.0
        if stop_count >= 3:
            transit_boost = 10.0
            hex_pressure += transit_boost   # transit hub
        elif stop_count >= 1:
            transit_boost = 4.0
            hex_pressure += transit_boost    # at least one stop in this cell

        raw_pressure = max(0.0, min(100.0, round(hex_pressure, 1)))

        # ── Per-hex evidence layer + classification ──
        campus_feature_count = campus_marker_counts.get(hex_id, 0)
        dormitory_count = dormitory_counts.get(hex_id, 0)
        off_campus_housing_count = off_campus_housing_counts.get(hex_id, 0)
        development_marker_count = development_counts.get(hex_id, 0)
        commercial_marker_count = commercial_counts.get(hex_id, 0)
        parking_marker_count = parking_counts.get(hex_id, 0)
        water_marker_count = water_counts.get(hex_id, 0)
        wetland_marker_count = wetland_counts.get(hex_id, 0)
        floodplain_marker_count = floodplain_counts.get(hex_id, 0)
        golf_marker_count = golf_counts.get(hex_id, 0)
        forest_marker_count = forest_counts.get(hex_id, 0)
        field_marker_count = field_counts.get(hex_id, 0)
        park_marker_count = park_counts.get(hex_id, 0)
        protected_marker_count = protected_counts.get(hex_id, 0)
        infrastructure_marker_count = infrastructure_counts.get(hex_id, 0)
        restricted_marker_count = restricted_counts.get(hex_id, 0)
        non_buildable_marker_count = (
            water_marker_count
            + wetland_marker_count
            + golf_marker_count
            + forest_marker_count
            + field_marker_count
            + park_marker_count
            + protected_marker_count
            + infrastructure_marker_count
            + restricted_marker_count
            + floodplain_marker_count
        )

        samples = _sample_points_in_polygon(polygon_latlng, sample_side=9)
        sample_count = len(samples)
        coverage_radius_km = max(0.085, _avg_hex_edge_km(resolution) * 0.45)

        coverage_raw = {
            "water": _marker_coverage_ratio(
                samples,
                _neighbor_bucket_points(water_bucket, hex_id, rings=2)
                + _neighbor_bucket_points(national_water_bucket, hex_id, rings=2),
                coverage_radius_km,
            ),
            "wetland": _marker_coverage_ratio(
                samples,
                _neighbor_bucket_points(wetland_bucket, hex_id, rings=2)
                + _neighbor_bucket_points(national_wetland_bucket, hex_id, rings=2),
                coverage_radius_km,
            ),
            "campus": _marker_coverage_ratio(
                samples,
                _neighbor_bucket_points(campus_bucket, hex_id, rings=1),
                coverage_radius_km,
            ),
            "residential_built": _marker_coverage_ratio(
                samples,
                _neighbor_bucket_points(residential_bucket, hex_id, rings=1),
                coverage_radius_km,
            ),
            "commercial_built": _marker_coverage_ratio(
                samples,
                _neighbor_bucket_points(commercial_bucket, hex_id, rings=1),
                coverage_radius_km,
            ),
            "parking_infrastructure": _marker_coverage_ratio(
                samples,
                _neighbor_bucket_points(parking_bucket, hex_id, rings=1)
                + _neighbor_bucket_points(infrastructure_bucket, hex_id, rings=1),
                coverage_radius_km,
            ),
            "open_recreation": _marker_coverage_ratio(
                samples,
                _neighbor_bucket_points(open_recreation_bucket, hex_id, rings=2),
                coverage_radius_km,
            ),
        }
        coverage_pct = {k: round(max(0.0, min(1.0, v)), 3) for k, v in coverage_raw.items()}

        land_marker_total = campus_feature_count + off_campus_housing_count
        campus_share = (
            campus_feature_count / land_marker_total
            if land_marker_total > 0
            else 0.0
        )
        development_density = development_marker_count / max(hex_area_km2, 0.01)
        (
            development_status,
            buildable_for_housing,
            already_developed_for_housing,
            on_campus_constrained,
            classification_reason_codes,
            pressure_cap,
            decision_flags,
        ) = _classify_development_status(
            coverage_pct=coverage_pct,
            distance_miles=distance_miles,
            campus_share=campus_share,
            campus_feature_count=campus_feature_count,
            dormitory_count=dormitory_count,
            off_campus_housing_count=off_campus_housing_count,
            development_marker_count=development_marker_count,
            commercial_marker_count=commercial_marker_count,
            water_marker_count=water_marker_count,
            wetland_marker_count=wetland_marker_count,
            floodplain_marker_count=floodplain_marker_count,
            golf_marker_count=golf_marker_count,
            field_marker_count=field_marker_count,
            park_marker_count=park_marker_count,
            development_density=development_density,
        )
        hex_pressure = raw_pressure if pressure_cap >= 99.0 else min(raw_pressure, pressure_cap)

        dominant_land_use = max(
            coverage_pct.keys(),
            key=lambda key: coverage_pct[key],
        )
        observed_markers = (
            campus_feature_count
            + off_campus_housing_count
            + development_marker_count
            + commercial_marker_count
            + parking_marker_count
            + non_buildable_marker_count
        )
        if observed_markers >= 500:
            classification_confidence: Literal["high", "medium", "low"] = "high"
        elif observed_markers >= 140:
            classification_confidence = "medium"
        else:
            classification_confidence = "low"

        weighted_non_buildable = (
            4.0 * coverage_pct["water"]
            + 3.2 * coverage_pct["wetland"]
            + 2.4 * coverage_pct["open_recreation"]
        )
        development_pressure = (
            2.4 * coverage_pct["residential_built"]
            + 2.6 * coverage_pct["commercial_built"]
            + 1.2 * coverage_pct["parking_infrastructure"]
            + 0.04 * development_density
        )
        availability_signal = max(7.5, 7.5 + 0.5 * stop_count)
        buildability_score = 100.0 * (
            availability_signal
            / (availability_signal + weighted_non_buildable + development_pressure)
        )

        coverage_hits = {
            key: int(round(value * sample_count))
            for key, value in coverage_pct.items()
        }

        hex_pressure = max(0.0, min(100.0, round(hex_pressure, 1)))

        # ── Transit label classification ──
        # Walkable = either it has a transit node OR it's already inside the
        # 0.5 mi pedestrian zone. Anything else with no transit is "Isolated".
        if stop_count >= 3:
            transit_label = "Transit Hub"
        elif stop_count >= 1 or distance_miles <= 0.5:
            transit_label = "Walkable"
        else:
            transit_label = "Isolated"

        label = (
            "high" if hex_pressure >= 70
            else "medium" if hex_pressure >= 40
            else "low"
        )

        # ── Boundary in GeoJSON [lng, lat] format ──
        boundary = [[float(lng), float(lat)] for lat, lng in raw_boundary]
        boundary.append(boundary[0])  # close ring

        features.append(HexFeature(
            hex_number=0,
            h3_index=hex_id,
            center_lat=round(c_lat, 6),
            center_lng=round(c_lng, 6),
            boundary=boundary,
            distance_km=round(distance_km, 3),
            distance_to_campus_miles=round(distance_miles, 3),
            pressure_score=hex_pressure,
            raw_pressure_score=raw_pressure,
            permit_density=permit_density,
            unit_density=unit_density,
            bus_stop_count=stop_count,
            campus_feature_count=campus_feature_count,
            dormitory_count=dormitory_count,
            off_campus_housing_count=off_campus_housing_count,
            development_marker_count=development_marker_count,
            already_developed_for_housing=already_developed_for_housing,
            campus_share=round(campus_share, 3),
            non_buildable_marker_count=non_buildable_marker_count,
            water_marker_count=water_marker_count,
            wetland_marker_count=wetland_marker_count,
            golf_marker_count=golf_marker_count,
            forest_marker_count=forest_marker_count,
            field_marker_count=field_marker_count,
            buildable_for_housing=buildable_for_housing,
            buildability_score=round(max(0.0, min(100.0, buildability_score)), 1),
            on_campus_constrained=on_campus_constrained,
            development_status=development_status,
            coverage_pct=coverage_pct,
            classification_reason_codes=classification_reason_codes,
            dominant_land_use=dominant_land_use,
            classification_confidence=classification_confidence,
            debug_trace={
                "sampling": {
                    "sample_side": 9,
                    "sample_count": sample_count,
                    "coverage_radius_km": round(coverage_radius_km, 4),
                    "neighbor_rings": 2,
                },
                "coverage_pct": coverage_pct,
                "coverage_hits": coverage_hits,
                "marker_counts": {
                    "campus_feature_count": campus_feature_count,
                    "dormitory_count": dormitory_count,
                    "off_campus_housing_count": off_campus_housing_count,
                    "development_marker_count": development_marker_count,
                    "commercial_marker_count": commercial_marker_count,
                    "parking_marker_count": parking_marker_count,
                    "water_marker_count": water_marker_count,
                    "wetland_marker_count": wetland_marker_count,
                    "floodplain_marker_count": floodplain_marker_count,
                    "golf_marker_count": golf_marker_count,
                    "forest_marker_count": forest_marker_count,
                    "field_marker_count": field_marker_count,
                    "park_marker_count": park_marker_count,
                    "protected_marker_count": protected_marker_count,
                    "infrastructure_marker_count": infrastructure_marker_count,
                    "restricted_marker_count": restricted_marker_count,
                    "non_buildable_marker_count": non_buildable_marker_count,
                },
                "thresholds": {
                    "hard_water_threshold": HARD_WATER_THRESHOLD,
                    "hard_wetland_threshold": HARD_WETLAND_THRESHOLD,
                    "hard_combined_threshold": HARD_COMBINED_THRESHOLD,
                    "hard_floodplain_markers": HARD_FLOODPLAIN_MARKERS,
                    "hard_hydro_mix_threshold": HARD_HYDRO_MIX_THRESHOLD,
                    "hard_hydro_min_markers": HARD_HYDRO_MIN_MARKERS,
                    "campus_coverage_threshold": CAMPUS_COVERAGE_THRESHOLD,
                    "campus_share_threshold": CAMPUS_SHARE_THRESHOLD,
                    "campus_distance_miles": CAMPUS_DISTANCE_MILES,
                    "campus_min_markers": CAMPUS_MIN_MARKERS,
                    "developed_built_coverage_threshold": DEVELOPED_BUILT_COVERAGE_THRESHOLD,
                    "developed_commercial_threshold": DEVELOPED_COMMERCIAL_THRESHOLD,
                    "developed_density_threshold": DEVELOPED_DENSITY_THRESHOLD,
                    "developed_structure_markers": DEVELOPED_STRUCTURE_MARKERS,
                    "developed_mixed_markers": DEVELOPED_MIXED_MARKERS,
                },
                "decision_flags": decision_flags,
                "classification_reason_codes": classification_reason_codes,
                "pressure_components": {
                    "base_score": base_score,
                    "proximity": round(proximity, 4),
                    "transit_boost": transit_boost,
                    "raw_pressure_score": raw_pressure,
                    "pressure_cap": pressure_cap,
                    "final_pressure_score": round(max(0.0, min(100.0, hex_pressure)), 1),
                },
                "buildability_components": {
                    "weighted_non_buildable": round(weighted_non_buildable, 4),
                    "development_pressure": round(development_pressure, 4),
                    "availability_signal": round(availability_signal, 4),
                    "buildability_score": round(max(0.0, min(100.0, buildability_score)), 1),
                },
                "land_mix": {
                    "campus_share": round(campus_share, 4),
                    "development_density": round(development_density, 4),
                },
            },
            transit_label=transit_label,
            label=label,
        ))

    features.sort(key=lambda f: f.distance_km)
    for idx, feat in enumerate(features, start=1):
        feat.hex_number = idx
        feat.debug_trace["hex_number"] = idx
    return features


def to_geojson(features: list[HexFeature], include_debug: bool = False) -> dict:
    """Serialize hex features to a GeoJSON FeatureCollection.

    The returned dict is JSON-serializable and compatible with
    Google Maps Data Layer.
    """
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [feat.boundary],
                },
                "properties": {
                    "hex_number": feat.hex_number,
                    "h3_index": feat.h3_index,
                    "center_lat": feat.center_lat,
                    "center_lng": feat.center_lng,
                    "distance_km": feat.distance_km,
                    "distance_to_campus_miles": feat.distance_to_campus_miles,
                    "pressure_score": feat.pressure_score,
                    "raw_pressure_score": feat.raw_pressure_score,
                    "permit_density": feat.permit_density,
                    "unit_density": feat.unit_density,
                    "bus_stop_count": feat.bus_stop_count,
                    "campus_feature_count": feat.campus_feature_count,
                    "dormitory_count": feat.dormitory_count,
                    "off_campus_housing_count": feat.off_campus_housing_count,
                    "development_marker_count": feat.development_marker_count,
                    "already_developed_for_housing": feat.already_developed_for_housing,
                    "campus_share": feat.campus_share,
                    "non_buildable_marker_count": feat.non_buildable_marker_count,
                    "water_marker_count": feat.water_marker_count,
                    "wetland_marker_count": feat.wetland_marker_count,
                    "golf_marker_count": feat.golf_marker_count,
                    "forest_marker_count": feat.forest_marker_count,
                    "field_marker_count": feat.field_marker_count,
                    "buildable_for_housing": feat.buildable_for_housing,
                    "buildability_score": feat.buildability_score,
                    "on_campus_constrained": feat.on_campus_constrained,
                    "development_status": feat.development_status,
                    "coverage_pct": feat.coverage_pct,
                    "classification_reason_codes": feat.classification_reason_codes,
                    "dominant_land_use": feat.dominant_land_use,
                    "classification_confidence": feat.classification_confidence,
                    **({"debug_trace": feat.debug_trace} if include_debug else {}),
                    "transit_label": feat.transit_label,
                    "label": feat.label,
                },
            }
            for feat in features
        ],
    }
