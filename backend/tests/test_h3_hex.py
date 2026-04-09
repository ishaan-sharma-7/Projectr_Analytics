import h3

from backend.scoring.h3_hex import (
    HARD_WATER_THRESHOLD,
    _classify_development_status,
    _point_in_polygon,
    _sample_points_in_polygon,
    compute_hex_features,
    to_geojson,
)


def _latlng_to_cell(lat: float, lng: float, resolution: int) -> str:
    if hasattr(h3, "latlng_to_cell"):
        return h3.latlng_to_cell(lat, lng, resolution)
    return h3.geo_to_h3(lat, lng, resolution)


def _cell_to_boundary(cell: str) -> list[tuple[float, float]]:
    if hasattr(h3, "cell_to_boundary"):
        return [(float(lat), float(lng)) for lat, lng in h3.cell_to_boundary(cell)]
    return [(float(lat), float(lng)) for lat, lng in h3.h3_to_geo_boundary(cell)]


def _make_feature(
    *,
    water_count: int = 0,
    wetland_count: int = 0,
    campus_count: int = 0,
    residential_count: int = 0,
    commercial_count: int = 0,
    parking_count: int = 0,
    open_recreation_count: int = 0,
) -> tuple[object, list[tuple[float, float]]]:
    campus_lat = 37.2296
    campus_lng = -80.4139
    hex_id = _latlng_to_cell(campus_lat, campus_lng, 9)
    boundary = _cell_to_boundary(hex_id)
    samples = _sample_points_in_polygon(boundary, sample_side=9)

    def pts(count: int) -> list[tuple[float, float]]:
        return samples[: min(count, len(samples))]

    non_buildable = (
        [(lat, lng, "water") for lat, lng in pts(water_count)]
        + [(lat, lng, "wetland") for lat, lng in pts(wetland_count)]
        + [(lat, lng, "golf_course") for lat, lng in pts(open_recreation_count)]
    )
    campus_markers = [(lat, lng, "campus") for lat, lng in pts(campus_count)]
    residential = [(lat, lng, "residential") for lat, lng in pts(residential_count)]
    commercial = [(lat, lng, "commercial") for lat, lng in pts(commercial_count)]
    parking = [(lat, lng, "parking") for lat, lng in pts(parking_count)]
    development = [(lat, lng, "structure") for lat, lng in pts(residential_count + commercial_count)]

    features = compute_hex_features(
        hex_indices=[hex_id],
        campus_lat=campus_lat,
        campus_lng=campus_lng,
        base_score=73.0,
        permits_5yr=2400,
        housing_units=52000,
        radius_miles=1.5,
        bus_stops=[],
        campus_markers=campus_markers,
        residential_markers=residential,
        non_buildable_markers=non_buildable,
        development_markers=development,
        commercial_markers=commercial,
        parking_markers=parking,
        national_constraint_points=[],
        resolution=9,
    )
    return features[0], samples


def test_point_in_polygon_and_sampling_are_consistent() -> None:
    polygon = [(0.0, 0.0), (0.0, 2.0), (2.0, 2.0), (2.0, 0.0)]
    assert _point_in_polygon(1.0, 1.0, polygon)
    assert not _point_in_polygon(3.0, 1.0, polygon)

    samples = _sample_points_in_polygon(polygon, sample_side=7)
    assert len(samples) > 0
    assert all(_point_in_polygon(lat, lng, polygon) for lat, lng in samples)


def test_hard_non_buildable_has_highest_precedence() -> None:
    feature, _ = _make_feature(
        water_count=999,
        campus_count=999,
        residential_count=999,
        commercial_count=999,
    )
    assert feature.development_status == "Hard non-buildable"
    assert feature.buildable_for_housing is False
    assert "water_majority" in feature.classification_reason_codes


def test_campus_constrained_beats_already_developed_when_no_hard_constraints() -> None:
    feature, samples = _make_feature(
        campus_count=999,
        residential_count=999,
        commercial_count=999,
        parking_count=999,
    )
    assert len(samples) > 0
    assert feature.development_status == "On-campus constrained"
    assert feature.on_campus_constrained is True


def test_already_developed_when_built_coverage_is_high() -> None:
    feature, _ = _make_feature(
        residential_count=999,
        commercial_count=999,
        parking_count=999,
    )
    assert feature.development_status == "Already developed (infill/redevelopment only)"
    assert feature.already_developed_for_housing is True


def test_water_threshold_boundary_behavior() -> None:
    below = _classify_development_status(
        coverage_pct={
            "water": HARD_WATER_THRESHOLD - 0.01,
            "wetland": 0.0,
            "campus": 0.0,
            "residential_built": 0.0,
            "commercial_built": 0.0,
            "parking_infrastructure": 0.0,
            "open_recreation": 0.0,
        },
        distance_miles=1.0,
        campus_share=0.0,
        campus_feature_count=0,
        dormitory_count=0,
        off_campus_housing_count=0,
        development_marker_count=0,
        commercial_marker_count=0,
        water_marker_count=0,
        wetland_marker_count=0,
        floodplain_marker_count=0,
        golf_marker_count=0,
        field_marker_count=0,
        park_marker_count=0,
        development_density=0.0,
    )
    above = _classify_development_status(
        coverage_pct={
            "water": HARD_WATER_THRESHOLD + 0.01,
            "wetland": 0.0,
            "campus": 0.0,
            "residential_built": 0.0,
            "commercial_built": 0.0,
            "parking_infrastructure": 0.0,
            "open_recreation": 0.0,
        },
        distance_miles=1.0,
        campus_share=0.0,
        campus_feature_count=0,
        dormitory_count=0,
        off_campus_housing_count=0,
        development_marker_count=0,
        commercial_marker_count=0,
        water_marker_count=0,
        wetland_marker_count=0,
        floodplain_marker_count=0,
        golf_marker_count=0,
        field_marker_count=0,
        park_marker_count=0,
        development_density=0.0,
    )

    assert below[0] == "Potentially buildable"
    assert above[0] == "Hard non-buildable"


def test_geojson_contains_v15_evidence_fields() -> None:
    feature, _ = _make_feature(residential_count=999)
    geojson = to_geojson([feature])
    props = geojson["features"][0]["properties"]

    assert "pressure_score" in props
    assert "buildability_score" in props
    assert "development_status" in props
    assert "coverage_pct" in props
    assert "classification_reason_codes" in props
    assert "dominant_land_use" in props
    assert "classification_confidence" in props
