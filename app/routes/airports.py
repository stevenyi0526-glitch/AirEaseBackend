"""
AirEase Backend - Airports Route
Provides airport information including coordinates for flight maps
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel, Field
import psycopg2
from app.config import settings

router = APIRouter(prefix="/v1/airports", tags=["airports"])


class AirportCoordinates(BaseModel):
    """Airport coordinates response"""
    iata_code: str = Field(alias="iataCode")
    name: str
    municipality: Optional[str] = None
    country: Optional[str] = Field(default=None, alias="country")
    latitude: float
    longitude: float
    
    class Config:
        populate_by_name = True


class FlightRouteCoordinates(BaseModel):
    """Flight route with departure and arrival coordinates"""
    departure: AirportCoordinates
    arrival: AirportCoordinates
    layovers: List[AirportCoordinates] = []


def get_db_connection():
    """Get PostgreSQL database connection from shared config"""
    return psycopg2.connect(
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=str(settings.postgres_port)
    )


@router.get(
    "/coordinates/{iata_code}",
    response_model=AirportCoordinates,
    summary="Get airport coordinates",
    description="Get coordinates for a specific airport by IATA code"
)
async def get_airport_coordinates(iata_code: str):
    """
    Get airport coordinates by IATA code.
    
    Returns:
        Airport name, location, and lat/lng coordinates
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT iata_code, name, municipality, iso_country, latitude_deg, longitude_deg
            FROM airports
            WHERE iata_code = %s
        """, (iata_code.upper(),))
        
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Airport {iata_code} not found")
        
        return AirportCoordinates(
            iataCode=row[0],
            name=row[1],
            municipality=row[2],
            country=row[3],
            latitude=float(row[4]) if row[4] else 0,
            longitude=float(row[5]) if row[5] else 0
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/route",
    response_model=FlightRouteCoordinates,
    summary="Get flight route coordinates",
    description="Get coordinates for a flight route including layovers"
)
async def get_flight_route_coordinates(
    departure: str = Query(..., description="Departure airport IATA code"),
    arrival: str = Query(..., description="Arrival airport IATA code"),
    layovers: Optional[str] = Query(None, description="Comma-separated layover airport codes")
):
    """
    Get coordinates for a complete flight route.
    
    Args:
        departure: Departure airport IATA code (e.g., HKG)
        arrival: Arrival airport IATA code (e.g., NRT)
        layovers: Optional comma-separated layover codes or airport names (e.g., "TPE,ICN" or "Kaohsiung International Airport")
    
    Returns:
        Coordinates for departure, arrival, and all layovers
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Helper function to resolve airport code or name to coordinates
        def resolve_airport(code_or_name: str) -> Optional[AirportCoordinates]:
            """Try to find airport by IATA code first, then by name search"""
            code = code_or_name.strip().upper()
            
            # First try exact IATA code match
            cursor.execute("""
                SELECT iata_code, name, municipality, iso_country, latitude_deg, longitude_deg
                FROM airports
                WHERE iata_code = %s
            """, (code,))
            row = cursor.fetchone()
            if row:
                return AirportCoordinates(
                    iataCode=row[0],
                    name=row[1],
                    municipality=row[2],
                    country=row[3],
                    latitude=float(row[4]) if row[4] else 0,
                    longitude=float(row[5]) if row[5] else 0
                )
            
            # Then try fuzzy name search
            search_term = code_or_name.strip()
            cursor.execute("""
                SELECT iata_code, name, municipality, iso_country, latitude_deg, longitude_deg
                FROM airports
                WHERE name ILIKE %s OR municipality ILIKE %s
                ORDER BY 
                    CASE WHEN name ILIKE %s THEN 0 ELSE 1 END,
                    LENGTH(name)
                LIMIT 1
            """, (f"%{search_term}%", f"%{search_term}%", f"{search_term}%"))
            row = cursor.fetchone()
            if row:
                return AirportCoordinates(
                    iataCode=row[0],
                    name=row[1],
                    municipality=row[2],
                    country=row[3],
                    latitude=float(row[4]) if row[4] else 0,
                    longitude=float(row[5]) if row[5] else 0
                )
            
            return None
        
        # Resolve departure and arrival
        dep_airport = resolve_airport(departure)
        arr_airport = resolve_airport(arrival)
        
        if not dep_airport:
            raise HTTPException(status_code=404, detail=f"Departure airport '{departure}' not found")
        if not arr_airport:
            raise HTTPException(status_code=404, detail=f"Arrival airport '{arrival}' not found")
        
        # Resolve layovers
        layover_airports = []
        if layovers:
            for code_or_name in layovers.split(","):
                if code_or_name.strip():
                    layover = resolve_airport(code_or_name)
                    if layover:
                        layover_airports.append(layover)
        
        cursor.close()
        conn.close()
        
        return FlightRouteCoordinates(
            departure=dep_airport,
            arrival=arr_airport,
            layovers=layover_airports
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/search",
    response_model=List[AirportCoordinates],
    summary="Search airports",
    description="Search airports by name, city, or IATA code"
)
async def search_airports(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results")
):
    """
    Search for airports by name, city, or code.
    
    Returns:
        List of matching airports with coordinates
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        search_term = f"%{q.upper()}%"
        
        cursor.execute("""
            SELECT iata_code, name, municipality, iso_country, latitude_deg, longitude_deg
            FROM airports
            WHERE (
                UPPER(iata_code) LIKE %s OR
                UPPER(name) LIKE %s OR
                UPPER(municipality) LIKE %s
            )
            AND type IN ('large_airport', 'medium_airport')
            ORDER BY 
                CASE 
                    WHEN UPPER(iata_code) = %s THEN 0
                    WHEN UPPER(iata_code) LIKE %s THEN 1
                    WHEN type = 'large_airport' THEN 2
                    ELSE 3
                END
            LIMIT %s
        """, (search_term, search_term, search_term, q.upper(), search_term, limit))
        
        results = []
        for row in cursor.fetchall():
            results.append(AirportCoordinates(
                iataCode=row[0],
                name=row[1],
                municipality=row[2],
                country=row[3],
                latitude=float(row[4]) if row[4] else 0,
                longitude=float(row[5]) if row[5] else 0
            ))
        
        cursor.close()
        conn.close()
        
        return results
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/nearest",
    response_model=AirportCoordinates,
    summary="Find nearest airport",
    description="Find the nearest airport to given coordinates"
)
async def find_nearest_airport(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    max_distance_km: float = Query(100, description="Maximum distance in km")
):
    """
    Find the nearest airport to given GPS coordinates.
    Uses Haversine formula to calculate distance.
    Only returns large/medium airports within the same city/region.
    
    Returns:
        The nearest airport with coordinates
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Use Haversine formula in SQL to find nearest airports
        # 6371 is Earth's radius in km
        cursor.execute("""
            SELECT 
                iata_code, name, municipality, iso_country, latitude_deg, longitude_deg,
                (6371 * acos(
                    cos(radians(%s)) * cos(radians(latitude_deg)) *
                    cos(radians(longitude_deg) - radians(%s)) +
                    sin(radians(%s)) * sin(radians(latitude_deg))
                )) AS distance_km
            FROM airports
            WHERE type IN ('large_airport', 'medium_airport')
            AND latitude_deg IS NOT NULL 
            AND longitude_deg IS NOT NULL
            AND iata_code IS NOT NULL
            AND iata_code != ''
            ORDER BY distance_km
            LIMIT 5
        """, (lat, lng, lat))
        
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not results:
            raise HTTPException(status_code=404, detail="No airports found nearby")
        
        # Return the closest airport
        row = results[0]
        distance = row[6]
        
        if distance > max_distance_km:
            raise HTTPException(
                status_code=404, 
                detail=f"No airports found within {max_distance_km}km"
            )
        
        return AirportCoordinates(
            iataCode=row[0],
            name=row[1],
            municipality=row[2],
            country=row[3],
            latitude=float(row[4]) if row[4] else 0,
            longitude=float(row[5]) if row[5] else 0
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
