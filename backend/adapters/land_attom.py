"""ATTOM Data adapter — fetches vacant land parcels near campus.

Queries the ATTOM property/expandedprofile endpoint for:
  1. VACANT LAND parcels (primary signal — empty developable lots)
  2. Commercial/industrial parcels where land value ≈ total value
     (underutilized = land-value-dominant = redevelopment candidate)

Returns a list of LandParcel dicts that h3_hex.py assigns to hex cells.

Each parcel has:
  lat / lng           — rooftop-accurate coordinates
  address             — formatted one-line address
  lot_size_acres      — parcel size
  market_value        — assessed market total value ($)
  land_value          — land-only component of market value ($)
  improvement_ratio   — building value / total value (0 = pure land, 1 = all building)
  owner_name          — owner's name from county assessor record
  is_absentee         — True when owner mailing address ≠ property address
  land_use            — ATTOM propLandUse string
  attom_id            — unique ATTOM property identifier

Score contribution:
  Hexes with vacant parcels get a land_availability_score boost of up to +12 pts
  on top of their existing pressure_score. Absentee owners add extra signal
  (motivated seller proxy).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

ATTOM_API_KEY = os.getenv("ATTOM_API_KEY", "")
_BASE = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"

# Land-use strings ATTOM returns for vacant / undeveloped parcels
_VACANT_LAND_USES = {
    "RESIDENTIAL - VACANT LAND",
    "COMMERCIAL - VACANT LAND",
    "INDUSTRIAL - VACANT LAND",
    "AGRICULTURAL - VACANT LAND",
    "VACANT LAND",
}

# Improvement ratio threshold: parcels below this are "land-value dominant"
# (building adds little value → likely underutilised / demo candidate)
_LAND_DOMINANT_RATIO = 0.15

LAYER_DATA_VERSION = "attom_land_v1_2026"

# In-memory cache keyed by (rounded_lat, rounded_lng, radius_miles)
_CACHE: dict[tuple, list[dict]] = {}


class LandParcel(TypedDict):
    lat: float
    lng: float
    address: str
    lot_size_acres: float
    market_value: float       # total assessed market value ($)
    land_value: float         # land-only component ($)
    improvement_ratio: float  # 0 = pure vacant land, 1 = entirely building value
    owner_name: str
    is_absentee: bool
    land_use: str
    attom_id: int
    parcel_type: str          # "vacant" | "land_dominant"


async def fetch_land_parcels(
    lat: float,
    lng: float,
    radius_miles: float,
    university_name: str,
) -> list[LandParcel]:
    """Return all vacant / land-dominant parcels within radius_miles of (lat, lng)."""
    if not ATTOM_API_KEY:
        return []

    cache_key = (round(lat, 3), round(lng, 3), radius_miles)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    headers = {"apikey": ATTOM_API_KEY, "accept": "application/json"}
    results: list[LandParcel] = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        # ── Pass 1: explicit VACANT LAND filter ──────────────────────────────
        try:
            r = await client.get(
                f"{_BASE}/property/expandedprofile",
                headers=headers,
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "radius": radius_miles,
                    "propertytype": "VACANT LAND",
                    "pagesize": 100,
                    "page": 1,
                },
            )
            if r.status_code == 200:
                data = r.json()
                for prop in data.get("property", []):
                    parcel = _parse_parcel(prop, "vacant")
                    if parcel:
                        results.append(parcel)
        except Exception as exc:
            print(f"[land_attom] VACANT LAND fetch failed for {university_name}: {exc}")

        # ── Pass 2: broader snapshot → keep land-dominant non-residential ──
        # Catches underutilised commercial/industrial sites that are
        # effectively "available land" even though they have a structure
        try:
            r2 = await client.get(
                f"{_BASE}/property/expandedprofile",
                headers=headers,
                params={
                    "latitude": lat,
                    "longitude": lng,
                    "radius": radius_miles,
                    "pagesize": 50,
                    "page": 1,
                },
            )
            if r2.status_code == 200:
                data2 = r2.json()
                existing_ids = {p["attom_id"] for p in results}
                for prop in data2.get("property", []):
                    luse = prop.get("summary", {}).get("propLandUse", "")
                    # Skip purely residential (covered by vacant filter or not relevant)
                    if any(k in luse for k in ("SINGLE FAMILY", "CONDO", "TOWNHOUSE")):
                        continue
                    parcel = _parse_parcel(prop, "land_dominant")
                    if parcel and parcel["attom_id"] not in existing_ids:
                        mkt = parcel["market_value"]
                        land = parcel["land_value"]
                        if mkt > 0 and (land / mkt) >= (1 - _LAND_DOMINANT_RATIO):
                            results.append(parcel)
                            existing_ids.add(parcel["attom_id"])
        except Exception as exc:
            print(f"[land_attom] land-dominant fetch failed for {university_name}: {exc}")

    print(f"[land_attom] {len(results)} land parcels for {university_name}")
    _CACHE[cache_key] = results
    return results


def _parse_parcel(prop: dict, parcel_type: str) -> LandParcel | None:
    """Extract a LandParcel from one ATTOM property record. Returns None if unusable."""
    loc = prop.get("location", {})
    try:
        plat = float(loc.get("latitude", 0))
        plng = float(loc.get("longitude", 0))
    except (TypeError, ValueError):
        return None
    if not plat or not plng:
        return None

    assessment = prop.get("assessment", {})
    mkt = assessment.get("market", {})
    mkt_total = float(mkt.get("mktTtlValue") or 0)
    mkt_land = float(mkt.get("mktLandValue") or 0)

    impr_ratio = 0.0
    if mkt_total > 0:
        impr_ratio = max(0.0, min(1.0, (mkt_total - mkt_land) / mkt_total))

    # Skip if clearly a land-dominant pass but ratio doesn't qualify
    if parcel_type == "land_dominant" and impr_ratio > _LAND_DOMINANT_RATIO:
        return None

    owner_block = assessment.get("owner", {})
    owner1 = owner_block.get("owner1", {})
    owner_name = owner1.get("fullName") or owner1.get("lastName") or "Unknown"
    absentee_status = owner_block.get("absenteeOwnerStatus", "")
    is_absentee = absentee_status == "A"  # A = absentee

    lot = prop.get("lot", {})
    lot_size = float(lot.get("lotsize1") or 0)

    summary = prop.get("summary", {})
    land_use = summary.get("propLandUse", "")
    attom_id = prop.get("identifier", {}).get("attomId", 0)

    address = prop.get("address", {}).get("oneLine", "")

    return LandParcel(
        lat=plat,
        lng=plng,
        address=address,
        lot_size_acres=lot_size,
        market_value=mkt_total,
        land_value=mkt_land,
        improvement_ratio=impr_ratio,
        owner_name=owner_name,
        is_absentee=is_absentee,
        land_use=land_use,
        attom_id=attom_id,
        parcel_type=parcel_type,
    )
