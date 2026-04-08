"""H3 hexagonal grid generation for CampusLens city-level choropleth.

Generates a hex grid at H3 resolution 8 (~0.74 km² per cell) centered on a
university campus. Each hex is assigned a pressure score based on:
  - Proximity to campus (distance decay)
  - Base Housing Pressure Score from the university-level calculation
  - Permit density distribution (closer to campus = higher expected density)

Returns a GeoJSON FeatureCollection ready for Google Maps Data Layer.

H3 v3/v4 compatibility: auto-detects installed version.
"""

import math
from dataclasses import dataclass

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

# Resolution 8 hex edge length in km (average)
RES8_EDGE_KM = 0.461
# Resolution 8 hex area in km²
RES8_AREA_KM2 = 0.737


@dataclass
class HexFeature:
    h3_index: str
    center_lat: float
    center_lng: float
    boundary: list[list[float]]  # GeoJSON [[lng, lat], ...] closed ring
    distance_km: float
    distance_to_campus_miles: float
    pressure_score: float
    permit_density: float        # estimated permits per km²
    unit_density: float          # estimated housing units per km²
    bus_stop_count: int          # OSM transit nodes whose H3 cell == this hex
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


def _radius_to_k(radius_km: float) -> int:
    """Number of hex rings needed to cover a given radius at resolution 8.

    Each ring adds approximately one edge length (~0.46 km) of coverage.
    Add 1 extra ring as buffer.
    """
    k = math.ceil(radius_km / RES8_EDGE_KM) + 1
    return max(2, min(k, 10))


def generate_campus_hex_grid(
    campus_lat: float,
    campus_lng: float,
    radius_miles: float = 1.5,
    resolution: int = 8,
) -> list[str]:
    """Return H3 cell indices covering a radius around campus.

    Args:
        campus_lat: Campus latitude.
        campus_lng: Campus longitude.
        radius_miles: Search radius in miles.
        resolution: H3 resolution (default 8, ~0.74 km² per cell).

    Returns:
        List of H3 cell index strings within the radius.
    """
    radius_km = radius_miles * 1.60934
    k = _radius_to_k(radius_km)

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
    resolution: int = 8,
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
        resolution: H3 resolution to use when bucketing bus stops into hexes.

    Returns:
        List of HexFeature, sorted by distance from campus.
    """
    radius_km = radius_miles * 1.60934

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
    if bus_stops:
        hex_set = set(hex_indices)
        for slat, slng in bus_stops:
            cell = _latlng_to_cell(slat, slng, resolution)
            if cell in hex_set:
                bus_stop_counts[cell] = bus_stop_counts.get(cell, 0) + 1

    features: list[HexFeature] = []
    for hex_id in hex_indices:
        c_lat, c_lng = _cell_to_latlng(hex_id)
        distance_km = hex_distances[hex_id]
        distance_miles = distance_km * 0.621371
        proximity = proximities[hex_id]

        # ── Spatial distribution of permits and housing units ──
        # Weight this hex by its share of total proximity (closer → more weight)
        proximity_share = proximity / total_proximity

        # Permit density: permits attributed to this hex / hex area
        hex_permits = permits_5yr * proximity_share
        permit_density = round(hex_permits / RES8_AREA_KM2, 2)

        # Unit density: total county units spread uniformly (we lack tract resolution)
        unit_density = round(
            (housing_units / max(len(hex_indices), 1)) / RES8_AREA_KM2, 2
        ) if housing_units > 0 else 0.0

        # ── Hex pressure score ──
        # Near-campus hexes inherit more of the base score.
        # Formula: score scales linearly from base_score (at campus) to
        # base_score * 0.4 (at radius edge), creating a visible gradient.
        hex_pressure = base_score * (0.4 + 0.6 * proximity)

        # ── Transit boost ──
        # Hexes with concentrated transit get a pressure bump because students
        # will rent there even at distance. Cap the boost so it can't overpower
        # the geometric gradient entirely.
        stop_count = bus_stop_counts.get(hex_id, 0)
        if stop_count >= 3:
            hex_pressure += 10.0   # transit hub
        elif stop_count >= 1:
            hex_pressure += 4.0    # at least one stop in this cell

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
        raw_boundary = _cell_to_boundary(hex_id)
        boundary = [[float(lng), float(lat)] for lat, lng in raw_boundary]
        boundary.append(boundary[0])  # close ring

        features.append(HexFeature(
            h3_index=hex_id,
            center_lat=round(c_lat, 6),
            center_lng=round(c_lng, 6),
            boundary=boundary,
            distance_km=round(distance_km, 3),
            distance_to_campus_miles=round(distance_miles, 3),
            pressure_score=hex_pressure,
            permit_density=permit_density,
            unit_density=unit_density,
            bus_stop_count=stop_count,
            transit_label=transit_label,
            label=label,
        ))

    features.sort(key=lambda f: f.distance_km)
    return features


def to_geojson(features: list[HexFeature]) -> dict:
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
                    "h3_index": feat.h3_index,
                    "center_lat": feat.center_lat,
                    "center_lng": feat.center_lng,
                    "distance_km": feat.distance_km,
                    "distance_to_campus_miles": feat.distance_to_campus_miles,
                    "pressure_score": feat.pressure_score,
                    "permit_density": feat.permit_density,
                    "unit_density": feat.unit_density,
                    "bus_stop_count": feat.bus_stop_count,
                    "transit_label": feat.transit_label,
                    "label": feat.label,
                },
            }
            for feat in features
        ],
    }
