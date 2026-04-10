"""Firestore abstraction layer for CampusLens.

Collections:
  scores  — HousingPressureScore docs keyed by unitid (string)
  hexes   — Hex GeoJSON docs keyed by {unitid}_{hash}

Falls back gracefully when Firestore is not configured (GCP_PROJECT_ID unset).
"""

import gzip
import hashlib
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_db = None
_init_attempted = False


def _get_db():
    global _db, _init_attempted
    if _init_attempted:
        return _db

    _init_attempted = True

    from backend.config import config

    if not config.gcp_project_id:
        logger.info("[Firestore] GCP_PROJECT_ID not set — file-cache fallback active")
        return None

    try:
        from google.cloud.firestore_v1 import AsyncClient

        _db = AsyncClient(project=config.gcp_project_id)
        logger.info(f"[Firestore] Connected to project {config.gcp_project_id}")
    except Exception as exc:
        logger.warning(f"[Firestore] Init failed ({exc}) — file-cache fallback active")
        _db = None

    return _db


def is_available() -> bool:
    return _get_db() is not None


# ── Scores ──────────────────────────────────────────────────────────────────


async def get_score(unitid: int) -> dict | None:
    db = _get_db()
    if not db:
        return None
    try:
        doc = await db.collection("scores").document(str(unitid)).get()
        return doc.to_dict() if doc.exists else None
    except Exception as exc:
        logger.warning(f"[Firestore] get_score({unitid}): {exc}")
        return None


async def set_score(unitid: int, score_data: dict) -> bool:
    db = _get_db()
    if not db:
        return False
    try:
        await db.collection("scores").document(str(unitid)).set(score_data)
        return True
    except Exception as exc:
        logger.warning(f"[Firestore] set_score({unitid}): {exc}")
        return False


async def get_all_scores() -> dict[int, dict]:
    db = _get_db()
    if not db:
        return {}
    try:
        scores: dict[int, dict] = {}
        async for doc in db.collection("scores").stream():
            try:
                scores[int(doc.id)] = doc.to_dict()
            except (ValueError, TypeError):
                continue
        return scores
    except Exception as exc:
        logger.warning(f"[Firestore] get_all_scores: {exc}")
        return {}


async def search_scores_by_name(name: str) -> list[dict]:
    """Partial case-insensitive name search across all scored universities."""
    db = _get_db()
    if not db:
        return []
    try:
        results = []
        query_lower = name.lower()
        async for doc in db.collection("scores").stream():
            data = doc.to_dict()
            uni = data.get("university", {})
            if query_lower in uni.get("name", "").lower():
                results.append(data)
        return results
    except Exception as exc:
        logger.warning(f"[Firestore] search_scores_by_name: {exc}")
        return []


async def bulk_set_scores(scores: dict[int, dict]) -> int:
    """Batch-write multiple score documents. Returns count written."""
    db = _get_db()
    if not db:
        return 0
    written = 0
    try:
        batch = db.batch()
        for i, (unitid, data) in enumerate(scores.items()):
            ref = db.collection("scores").document(str(unitid))
            batch.set(ref, data)
            written += 1
            if (i + 1) % 400 == 0:  # Firestore batch limit is 500
                await batch.commit()
                batch = db.batch()
        if written % 400 != 0:
            await batch.commit()
        logger.info(f"[Firestore] Synced {written} scores")
    except Exception as exc:
        logger.warning(f"[Firestore] bulk_set_scores: {exc}")
    return written


# ── Hexes ───────────────────────────────────────────────────────────────────


def _hex_doc_id(cache_key: tuple) -> str:
    slug = hashlib.md5(str(cache_key).encode()).hexdigest()[:16]
    return f"{cache_key[0]}_{slug}"


async def get_hex(cache_key: tuple) -> dict | None:
    db = _get_db()
    if not db:
        return None
    try:
        doc_id = _hex_doc_id(cache_key)
        doc = await db.collection("hexes").document(doc_id).get()
        if not doc.exists:
            return None

        data = doc.to_dict()

        cached_at = data.get("_cached_at", "")
        if cached_at:
            saved = datetime.fromisoformat(cached_at)
            if (datetime.now(timezone.utc) - saved).days > 7:
                return None

        if "_features_gz" in data:
            raw = data.pop("_features_gz")
            data["features"] = json.loads(gzip.decompress(raw).decode())
        return data
    except Exception as exc:
        logger.warning(f"[Firestore] get_hex: {exc}")
        return None


async def get_hex_any_version(unitid: int) -> dict | None:
    """Return the most recent hex grid for a university, ignoring model version.

    Queries Firestore for any hex doc whose ID starts with the unitid prefix.
    Serves stale-but-fast data while a fresh recompute runs in the background.
    """
    db = _get_db()
    if not db:
        return None
    try:
        prefix = f"{unitid}_"
        query = (
            db.collection("hexes")
            .where("__name__", ">=", prefix)
            .where("__name__", "<", f"{unitid + 1}_")
            .limit(1)
        )
        docs = []
        async for doc in query.stream():
            docs.append(doc)
        if not docs:
            return None
        data = docs[0].to_dict()
        if "_features_gz" in data:
            raw = data.pop("_features_gz")
            data["features"] = json.loads(gzip.decompress(raw).decode())
        return data
    except Exception as exc:
        logger.warning(f"[Firestore] get_hex_any_version({unitid}): {exc}")
        return None


async def set_hex(cache_key: tuple, geojson: dict) -> bool:
    db = _get_db()
    if not db:
        return False
    try:
        doc_id = _hex_doc_id(cache_key)
        store = {k: v for k, v in geojson.items() if k != "features"}
        store["_cached_at"] = datetime.now(timezone.utc).isoformat()
        store["_cache_key"] = list(cache_key)

        features = geojson.get("features", [])
        store["_features_gz"] = gzip.compress(
            json.dumps(features).encode(), compresslevel=6
        )
        store["_feature_count"] = len(features)

        await db.collection("hexes").document(doc_id).set(store)
        return True
    except Exception as exc:
        logger.warning(f"[Firestore] set_hex: {exc}")
        return False
