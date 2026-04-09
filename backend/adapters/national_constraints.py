"""National U.S. constraint overlays for per-hex classification.

This adapter fetches lightweight point samples for:
  - FEMA floodplain polygons (NFHL ArcGIS service)
  - National wetlands polygons (USFWS ArcGIS service)

The API shape intentionally mirrors other adapters:
  ``[(lat, lon, kind), ...]`` where ``kind`` is ``floodplain`` or ``wetland``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import httpx

LAYER_DATA_VERSION = "us_constraints_2026_v1"

_CACHE: dict[tuple[float, float, float, str], list[tuple[float, float, str]]] = {}

_FEMA_NFHL_QUERY = (
    "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query"
)
_USFWS_WETLANDS_QUERY = (
    "https://www.fws.gov/wetlands/arcgis/rest/services/Wetlands/MapServer/0/query"
)


@dataclass
class _BBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def as_arcgis_envelope(self) -> str:
        return f"{self.xmin},{self.ymin},{self.xmax},{self.ymax}"


def _bbox_from_radius(lat: float, lon: float, radius_miles: float) -> _BBox:
    # Approximate conversion valid for small campus radii.
    dlat = radius_miles / 69.0
    dlng = radius_miles / max(1e-6, 69.172 * max(0.2, abs(math.cos(math.radians(lat)))))
    return _BBox(
        xmin=lon - dlng,
        ymin=lat - dlat,
        xmax=lon + dlng,
        ymax=lat + dlat,
    )


def _feature_centroid_latlon(feature: dict) -> tuple[float, float] | None:
    geom = feature.get("geometry") or {}

    x = geom.get("x")
    y = geom.get("y")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return float(y), float(x)

    rings = geom.get("rings")
    if isinstance(rings, list) and rings:
        pts = [pt for ring in rings for pt in ring if isinstance(pt, list) and len(pt) >= 2]
        if pts:
            xs = [float(pt[0]) for pt in pts]
            ys = [float(pt[1]) for pt in pts]
            return (sum(ys) / len(ys), sum(xs) / len(xs))

    paths = geom.get("paths")
    if isinstance(paths, list) and paths:
        pts = [pt for path in paths for pt in path if isinstance(pt, list) and len(pt) >= 2]
        if pts:
            xs = [float(pt[0]) for pt in pts]
            ys = [float(pt[1]) for pt in pts]
            return (sum(ys) / len(ys), sum(xs) / len(xs))

    return None


async def _fetch_arcgis_overlay_points(
    url: str,
    bbox: _BBox,
    kind: str,
) -> list[tuple[float, float, str]]:
    params = {
        "where": "1=1",
        "geometry": bbox.as_arcgis_envelope(),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "json",
    }

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"{url} HTTP {resp.status_code}")
        payload = resp.json()

    markers: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, str]] = set()
    for feat in payload.get("features", []):
        latlon = _feature_centroid_latlon(feat)
        if not latlon:
            continue
        lat, lon = latlon
        key = (round(lat, 5), round(lon, 5), kind)
        if key in seen:
            continue
        seen.add(key)
        markers.append((lat, lon, kind))

    return markers


async def fetch_national_constraint_points(
    lat: float,
    lon: float,
    radius_miles: float = 1.5,
) -> list[tuple[float, float, str]]:
    """Return national overlay constraints as ``[(lat, lon, kind), ...]``.

    ``kind``:
      - ``wetland``
      - ``floodplain``
    """
    cache_key = (
        round(lat, 4),
        round(lon, 4),
        round(radius_miles, 2),
        LAYER_DATA_VERSION,
    )
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    bbox = _bbox_from_radius(lat, lon, radius_miles)
    points: list[tuple[float, float, str]] = []

    for url, kind in (
        (_USFWS_WETLANDS_QUERY, "wetland"),
        (_FEMA_NFHL_QUERY, "floodplain"),
    ):
        try:
            points.extend(await _fetch_arcgis_overlay_points(url, bbox, kind))
        except Exception as exc:
            print(f"[NationalConstraints] {kind} overlay failed: {exc}")

    _CACHE[cache_key] = points
    return points
