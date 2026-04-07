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
    pressure_score: float
    permit_density: float        # estimated permits per km²
    unit_density: float          # estimated housing units per km²
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
) -> list[HexFeature]:
    """Compute pressure features for each hex in the grid.

    Pressure is highest at the campus core and decays toward the radius edge.
    Permit and unit density are spatially distributed using proximity weighting
    (student housing activity concentrates near campus).

    Args:
        hex_indices: H3 cell indices from generate_campus_hex_grid.
        campus_lat / campus_lng: Campus coordinates.
        base_score: University-level Housing Pressure Score (0–100).
        permits_5yr: Total residential permits filed in county over 5 years.
        housing_units: Total housing units in county from ACS.
        radius_miles: Max radius (for normalization).

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

    features: list[HexFeature] = []
    for hex_id in hex_indices:
        c_lat, c_lng = _cell_to_latlng(hex_id)
        distance_km = hex_distances[hex_id]
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
        hex_pressure = round(base_score * (0.4 + 0.6 * proximity), 1)
        hex_pressure = max(0.0, min(100.0, hex_pressure))

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
            pressure_score=hex_pressure,
            permit_density=permit_density,
            unit_density=unit_density,
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
                    "pressure_score": feat.pressure_score,
                    "permit_density": feat.permit_density,
                    "unit_density": feat.unit_density,
                    "label": feat.label,
                },
            }
            for feat in features
        ],
    }
