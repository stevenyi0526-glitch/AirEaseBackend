"""
AirEase Backend - Aircraft Database API Routes

Provides endpoints to look up aircraft engine type, age, and fleet info
from the OpenSky Network database.
"""

from fastapi import APIRouter, Query, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.services.aircraft_db_service import AircraftDatabaseService
from app.services.safety_profile_service import build_safety_profile
from app.routes.auth import require_auth
from app.database import UserDB

router = APIRouter(prefix="/v1/aircraft", tags=["aircraft"])


# ============================================================
# Admin helper
# ============================================================

ADMIN_EMAIL = "steven.yi@airease.ai"


def require_admin(current_user: UserDB = Depends(require_auth)) -> UserDB:
    """Dependency that requires admin privileges."""
    if current_user.user_email != ADMIN_EMAIL and not getattr(current_user, 'is_admin', False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


# ============================================================
# Public endpoints
# ============================================================


@router.get("/lookup")
async def lookup_aircraft(
    registration: Optional[str] = Query(None, description="Aircraft registration (e.g., B-LRA, JA891A)"),
    typecode: Optional[str] = Query(None, description="ICAO type code (e.g., B789, A359)"),
    model: Optional[str] = Query(None, description="Model name (e.g., Boeing 787-9, Airbus A350-900)"),
    airline: Optional[str] = Query(None, description="Airline IATA code (e.g., CX, NH, JL)"),
):
    """
    Look up aircraft details (engines, age) from the OpenSky database.
    
    Priority: registration > typecode > model name
    """
    result = None

    if registration:
        result = AircraftDatabaseService.lookup_by_registration(registration)

    if not result and typecode:
        result = AircraftDatabaseService.lookup_by_typecode(typecode, airline)

    if not result and model:
        result = AircraftDatabaseService.lookup_by_model_name(model, airline)

    if result:
        return {"status": "found", "aircraft": result}
    else:
        return {"status": "not_found", "aircraft": None}


@router.get("/fleet")
async def get_fleet_stats(
    airline: str = Query(..., description="Airline IATA code (e.g., CX, NH)"),
    typecode: Optional[str] = Query(None, description="Filter by ICAO type code"),
):
    """Get fleet statistics for an airline."""
    stats = AircraftDatabaseService.get_fleet_stats(airline, typecode)
    if stats:
        return {"status": "found", "fleet": stats}
    else:
        return {"status": "not_found", "fleet": None}


# ============================================================
# Admin endpoints - direct DB updates
# ============================================================

class AircraftUpdateRequest(BaseModel):
    """Admin request to update aircraft data in the database."""
    typecode: str
    operator_iata: Optional[str] = None
    engines: Optional[str] = None
    engine_type: Optional[str] = None
    built_year: Optional[int] = None


@router.put("/update")
async def admin_update_aircraft(
    request: AircraftUpdateRequest,
    admin: UserDB = Depends(require_admin),
):
    """
    Admin-only: Update aircraft engine, engine_type, and age data
    directly in the PostgreSQL aircraft_database.
    
    Updates ALL rows matching the typecode (and optionally operator_iata).
    """
    updated = AircraftDatabaseService.admin_update(
        typecode=request.typecode,
        operator_iata=request.operator_iata,
        engines=request.engines,
        engine_type=request.engine_type,
        built_year=request.built_year,
    )
    return {
        "status": "updated",
        "rowsAffected": updated,
        "updatedBy": admin.user_email,
    }


# ============================================================
# Safety Profile endpoint (NTSB data)
# ============================================================


@router.get("/safety-profile")
async def get_safety_profile(
    flight_code: Optional[str] = Query(None, description="Flight code, e.g. UA123"),
    airline: Optional[str] = Query(None, description="Airline name, e.g. United Airlines"),
    airline_iata: Optional[str] = Query(None, description="Airline IATA code, e.g. UA"),
    model: Optional[str] = Query(None, description="Aircraft model, e.g. 737-800"),
):
    """
    Build a full safety profile for a flight.

    1. Resolves flight_code → tail number via FlightRadar24 (real-time).
    2. Queries NTSB database for aircraft specs and accident history.
    3. Falls back to OpenSky aircraft_database for engine & age if NTSB has no data.
    4. Returns engine info, age, per-plane accidents, airline stats, and model stats.
    """
    profile = build_safety_profile(
        flight_code=flight_code,
        airline=airline,
        airline_iata=airline_iata,
        model=model,
    )
    return profile
