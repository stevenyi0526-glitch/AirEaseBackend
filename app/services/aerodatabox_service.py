"""
AirEase Backend – AeroDataBox Service

Third-level fallback for aircraft metadata (engine type, age, image).
Uses AeroDataBox RapidAPI when local OpenSky DB and NTSB have no data.

Strategy to minimise API usage (free plan):
  1. Cache every response in PostgreSQL `aerodatabox_cache` table.
  2. Before calling the API, check the cache first.
  3. Negative results (API returned nothing) are also cached to avoid re-calling.
  4. Cache TTL: 90 days (aircraft data rarely changes).
"""

import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

import httpx
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# RapidAPI config
RAPIDAPI_HOST = "aerodatabox.p.rapidapi.com"
BASE_URL = f"https://{RAPIDAPI_HOST}"
CACHE_TTL_DAYS = 90

# Rate limiting: free plan allows 1 request per second
_last_api_call_time: float = 0.0


def _rate_limit():
    """Ensure at least 1.1 seconds between API calls (free plan: 1 req/sec)."""
    global _last_api_call_time
    elapsed = time.time() - _last_api_call_time
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
    _last_api_call_time = time.time()


# ============================================================
# Cache helpers
# ============================================================

def _ensure_cache_table():
    """Create cache table if it doesn't exist (idempotent)."""
    db = SessionLocal()
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS aerodatabox_cache (
                registration VARCHAR(20) PRIMARY KEY,
                data JSONB,
                image_url TEXT,
                image_attribution TEXT,
                fetched_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"aerodatabox_cache table check failed (may already exist): {e}")
    finally:
        db.close()


# Initialise table on import
_ensure_cache_table()


def _get_cached(registration: str) -> Optional[Dict[str, Any]]:
    """Return cached record if fresh enough, else None."""
    db = SessionLocal()
    try:
        row = db.execute(
            text("""
                SELECT data, image_url, image_attribution, fetched_at
                FROM aerodatabox_cache
                WHERE registration = :reg
            """),
            {"reg": registration.upper().strip()},
        ).fetchone()
        if not row:
            return None
        # Check freshness
        fetched_at = row[3]
        if datetime.utcnow() - fetched_at > timedelta(days=CACHE_TTL_DAYS):
            return None  # Stale
        return {
            "data": row[0],      # JSONB → dict or None
            "image_url": row[1],
            "image_attribution": row[2],
        }
    except Exception as e:
        logger.warning(f"Cache read error for {registration}: {e}")
        return None
    finally:
        db.close()


def _save_cache(
    registration: str,
    data: Optional[Dict[str, Any]],
    image_url: Optional[str] = None,
    image_attribution: Optional[str] = None,
):
    """Upsert a cache row."""
    db = SessionLocal()
    try:
        import json
        data_json = json.dumps(data) if data else None
        db.execute(
            text("""
                INSERT INTO aerodatabox_cache (registration, data, image_url, image_attribution, fetched_at)
                VALUES (:reg, CAST(:data AS jsonb), :img, :attr, NOW())
                ON CONFLICT (registration)
                DO UPDATE SET data = CAST(:data AS jsonb), image_url = :img,
                              image_attribution = :attr, fetched_at = NOW()
            """),
            {
                "reg": registration.upper().strip(),
                "data": data_json,
                "img": image_url,
                "attr": image_attribution,
            },
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Cache write error for {registration}: {e}")
    finally:
        db.close()


# ============================================================
# API callers
# ============================================================

def _headers() -> Dict[str, str]:
    return {
        "x-rapidapi-key": settings.aerodatabox_rapidapi_key,
        "x-rapidapi-host": RAPIDAPI_HOST,
    }


def _fetch_aircraft_by_reg(registration: str) -> Optional[Dict[str, Any]]:
    """GET /aircrafts/reg/{reg} → aircraft metadata."""
    if not settings.aerodatabox_rapidapi_key:
        return None
    try:
        _rate_limit()
        url = f"{BASE_URL}/aircrafts/reg/{registration.strip()}"
        resp = httpx.get(url, headers=_headers(), timeout=8)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"AeroDataBox aircraft API {resp.status_code} for {registration}")
        return None
    except Exception as e:
        logger.warning(f"AeroDataBox aircraft API error for {registration}: {e}")
        return None


def _fetch_image_by_reg(registration: str) -> Optional[Dict[str, Any]]:
    """GET /aircrafts/reg/{reg}/image/beta → image URL + attribution."""
    if not settings.aerodatabox_rapidapi_key:
        return None
    try:
        _rate_limit()
        url = f"{BASE_URL}/aircrafts/reg/{registration.strip()}/image/beta"
        resp = httpx.get(url, headers=_headers(), timeout=8)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        logger.warning(f"AeroDataBox image API error for {registration}: {e}")
        return None


# ============================================================
# Public interface
# ============================================================

def enrich_aircraft(registration: str) -> Optional[Dict[str, Any]]:
    """
    Look up an aircraft by registration via AeroDataBox.
    Returns a normalised dict with engine info, age, and image.
    Uses cache to minimise API calls.
    """
    if not registration:
        return None

    reg = registration.upper().strip()

    # 1. Check cache
    cached = _get_cached(reg)
    if cached is not None:
        raw = cached.get("data")
        if raw is None:
            return None  # Negative cache hit
        return _normalise(raw, cached.get("image_url"), cached.get("image_attribution"))

    # 2. Call API
    logger.info(f"🌐 AeroDataBox: fetching aircraft data for {reg}")
    raw = _fetch_aircraft_by_reg(reg)

    image_url = None
    image_attr = None
    if raw:
        # Also fetch image (only 1 extra call, and we cache it)
        img = _fetch_image_by_reg(reg)
        if img:
            image_url = img.get("url")
            html_attrs = img.get("htmlAttributions", [])
            image_attr = html_attrs[0] if html_attrs else img.get("author")

    # 3. Save to cache (even if None → negative cache)
    _save_cache(reg, raw, image_url, image_attr)

    if not raw:
        return None

    return _normalise(raw, image_url, image_attr)


def _validate_engine_type(engine_type: Optional[str], type_name: str, model_code: str) -> Optional[str]:
    """
    Validate and correct engine_type from AeroDataBox.
    AeroDataBox sometimes returns wrong engine types (e.g. 'Turboprop' for A350).
    We fix obvious errors based on known aircraft families.
    """
    if not engine_type:
        return engine_type

    name_upper = (type_name or "").upper()
    code_upper = (model_code or "").upper()

    # Known wide-body / narrow-body JET aircraft families
    # If AeroDataBox says "Turboprop" for any of these, it's wrong → override to "Jet"
    JET_FAMILIES = [
        # Airbus wide-body
        "A330", "A340", "A350", "A380",
        # Airbus narrow-body
        "A318", "A319", "A320", "A321",
        # Boeing wide-body
        "747", "767", "777", "787", "B747", "B767", "B777", "B787",
        # Boeing narrow-body
        "737", "B737", "757", "B757",
        # Embraer jets
        "E170", "E175", "E190", "E195", "ERJ",
        # Bombardier / Mitsubishi jets
        "CRJ", "CS100", "CS300", "A220",
        # Other jets
        "MD-80", "MD-90", "MD-11", "DC-10", "DC-9",
        "717", "CONCORDE", "TU-204", "TU-214",
        "COMAC", "C919", "ARJ21",
        "SSJ", "SUKHOI",
    ]

    combined = f"{name_upper} {code_upper}"
    if engine_type.lower() in ("turboprop", "piston"):
        for family in JET_FAMILIES:
            if family in combined:
                logger.info(f"🔧 Correcting engineType '{engine_type}' → 'Jet' for {type_name} ({model_code})")
                return "Jet"

    return engine_type


def _normalise(raw: Dict[str, Any], image_url: Optional[str], image_attr: Optional[str]) -> Dict[str, Any]:
    """Convert AeroDataBox raw response to our standard format."""
    type_name = raw.get("typeName", "")
    model_code = raw.get("modelCode", "")
    num_engines = raw.get("numEngines")
    engine_type = _validate_engine_type(raw.get("engineType"), type_name, model_code)
    age_years = raw.get("ageYears")

    # Build engine string like "2x Jet" or just "Jet"
    engine_str = None
    if engine_type:
        if num_engines and num_engines > 0:
            engine_str = f"{num_engines}× {engine_type}"
        else:
            engine_str = engine_type

    # Age label
    age_label = None
    if age_years is not None:
        rounded = round(age_years, 1)
        if rounded < 1:
            age_label = "less than 1 year"
        elif rounded == 1:
            age_label = "1 year old"
        else:
            age_label = f"{rounded} years old"

    # Built year from rolloutDate or registrationDate
    built_year = None
    for date_field in ("rolloutDate", "registrationDate"):
        val = raw.get(date_field)
        if val:
            try:
                built_year = int(val[:4])
                break
            except (ValueError, TypeError):
                pass

    return {
        "registration": raw.get("reg"),
        "typeName": type_name,
        "modelCode": model_code,
        "icaoCode": raw.get("icaoCode"),
        "airlineName": raw.get("airlineName"),
        "numEngines": num_engines,
        "engineType": engine_type,
        "engineStr": engine_str,
        "numSeats": raw.get("numSeats"),
        "ageYears": age_years,
        "ageLabel": age_label,
        "builtYear": built_year,
        "isFreighter": raw.get("isFreighter", False),
        "imageUrl": image_url,
        "imageAttribution": image_attr,
        "source": "aerodatabox",
    }
