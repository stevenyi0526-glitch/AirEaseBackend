"""
AirEase Backend - City Search Routes
Google Places API integration for city/airport autocomplete
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import httpx

from app.config import settings
from app.models import CitySearchResult

router = APIRouter(prefix="/v1/cities", tags=["Cities"])

# Airport code mappings for major cities
CITY_AIRPORT_CODES = {
    "hong kong": "HKG",
    "london": "LHR",
    "tokyo": "NRT",
    "new york": "JFK",
    "los angeles": "LAX",
    "singapore": "SIN",
    "dubai": "DXB",
    "paris": "CDG",
    "sydney": "SYD",
    "beijing": "PEK",
    "shanghai": "PVG",
    "seoul": "ICN",
    "bangkok": "BKK",
    "melbourne": "MEL",
    "frankfurt": "FRA",
    "amsterdam": "AMS",
    "toronto": "YYZ",
    "vancouver": "YVR",
    "san francisco": "SFO",
    "chicago": "ORD",
    "miami": "MIA",
    "taipei": "TPE",
    "kuala lumpur": "KUL",
    "manila": "MNL",
    "mumbai": "BOM",
    "delhi": "DEL",
    "madrid": "MAD",
    "barcelona": "BCN",
    "rome": "FCO",
    "zurich": "ZRH",
    "vienna": "VIE",
    "istanbul": "IST",
    "abu dhabi": "AUH",
    "doha": "DOH",
    "munich": "MUC",
    "seattle": "SEA",
    "boston": "BOS",
    "atlanta": "ATL",
    "denver": "DEN",
    "osaka": "KIX",
    "guangzhou": "CAN",
    "shenzhen": "SZX",
    "hangzhou": "HGH",
    "chengdu": "CTU",
    "xi'an": "XIY",
    "taipei": "TPE",
    "ho chi minh": "SGN",
    "hanoi": "HAN",
    "jakarta": "CGK",
    "bali": "DPS",
}


def get_airport_code(city: str) -> Optional[str]:
    """Get airport code for a city name."""
    city_lower = city.lower()
    for city_name, code in CITY_AIRPORT_CODES.items():
        if city_name in city_lower or city_lower in city_name:
            return code
    return None


@router.get(
    "/search",
    response_model=List[CitySearchResult],
    summary="Search cities",
    description="Search for cities using Google Places API or fallback to local data"
)
async def search_cities(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(10, ge=1, le=20, description="Maximum results")
):
    """
    Search for cities with autocomplete.
    Uses Google Places API if configured, otherwise uses local fallback.
    """
    
    # Check if Google Places API is configured
    if settings.google_places_api_key:
        try:
            return await search_cities_google(q, limit)
        except Exception as e:
            # Fallback to local search if Google API fails
            print(f"Google Places API error: {e}")
            return search_cities_local(q, limit)
    else:
        return search_cities_local(q, limit)


async def search_cities_google(query: str, limit: int) -> List[CitySearchResult]:
    """Search cities using Google Places Autocomplete API."""
    
    url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
    params = {
        "input": query,
        "types": "(cities)",
        "key": settings.google_places_api_key,
        "language": "en"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=5.0)
        response.raise_for_status()
        data = response.json()
    
    if data.get("status") != "OK":
        if data.get("status") == "ZERO_RESULTS":
            return []
        raise HTTPException(
            status_code=500,
            detail=f"Google Places API error: {data.get('status')}"
        )
    
    results = []
    for prediction in data.get("predictions", [])[:limit]:
        place_id = prediction.get("place_id", "")
        description = prediction.get("description", "")
        
        # Parse city and country from description
        parts = description.split(", ")
        city = parts[0] if parts else ""
        country = parts[-1] if len(parts) > 1 else ""
        
        # Get airport code
        airport_code = get_airport_code(city)
        
        results.append(CitySearchResult(
            placeId=place_id,
            city=city,
            country=country,
            airportCode=airport_code,
            displayName=f"{city}, {country}" + (f" ({airport_code})" if airport_code else "")
        ))
    
    return results


def search_cities_local(query: str, limit: int) -> List[CitySearchResult]:
    """Search cities using local data (fallback)."""
    
    # Local city database
    cities = [
        {"city": "Hong Kong", "country": "Hong Kong", "code": "HKG"},
        {"city": "London", "country": "United Kingdom", "code": "LHR"},
        {"city": "Tokyo", "country": "Japan", "code": "NRT"},
        {"city": "New York", "country": "United States", "code": "JFK"},
        {"city": "Los Angeles", "country": "United States", "code": "LAX"},
        {"city": "Singapore", "country": "Singapore", "code": "SIN"},
        {"city": "Dubai", "country": "United Arab Emirates", "code": "DXB"},
        {"city": "Paris", "country": "France", "code": "CDG"},
        {"city": "Sydney", "country": "Australia", "code": "SYD"},
        {"city": "Beijing", "country": "China", "code": "PEK"},
        {"city": "Shanghai", "country": "China", "code": "PVG"},
        {"city": "Seoul", "country": "South Korea", "code": "ICN"},
        {"city": "Bangkok", "country": "Thailand", "code": "BKK"},
        {"city": "Melbourne", "country": "Australia", "code": "MEL"},
        {"city": "Frankfurt", "country": "Germany", "code": "FRA"},
        {"city": "Amsterdam", "country": "Netherlands", "code": "AMS"},
        {"city": "Toronto", "country": "Canada", "code": "YYZ"},
        {"city": "Vancouver", "country": "Canada", "code": "YVR"},
        {"city": "San Francisco", "country": "United States", "code": "SFO"},
        {"city": "Chicago", "country": "United States", "code": "ORD"},
        {"city": "Miami", "country": "United States", "code": "MIA"},
        {"city": "Taipei", "country": "Taiwan", "code": "TPE"},
        {"city": "Kuala Lumpur", "country": "Malaysia", "code": "KUL"},
        {"city": "Manila", "country": "Philippines", "code": "MNL"},
        {"city": "Mumbai", "country": "India", "code": "BOM"},
        {"city": "Delhi", "country": "India", "code": "DEL"},
        {"city": "Madrid", "country": "Spain", "code": "MAD"},
        {"city": "Barcelona", "country": "Spain", "code": "BCN"},
        {"city": "Rome", "country": "Italy", "code": "FCO"},
        {"city": "Zurich", "country": "Switzerland", "code": "ZRH"},
        {"city": "Vienna", "country": "Austria", "code": "VIE"},
        {"city": "Istanbul", "country": "Turkey", "code": "IST"},
        {"city": "Abu Dhabi", "country": "United Arab Emirates", "code": "AUH"},
        {"city": "Doha", "country": "Qatar", "code": "DOH"},
        {"city": "Munich", "country": "Germany", "code": "MUC"},
        {"city": "Seattle", "country": "United States", "code": "SEA"},
        {"city": "Boston", "country": "United States", "code": "BOS"},
        {"city": "Atlanta", "country": "United States", "code": "ATL"},
        {"city": "Denver", "country": "United States", "code": "DEN"},
        {"city": "Osaka", "country": "Japan", "code": "KIX"},
        {"city": "Guangzhou", "country": "China", "code": "CAN"},
        {"city": "Shenzhen", "country": "China", "code": "SZX"},
        {"city": "Hangzhou", "country": "China", "code": "HGH"},
        {"city": "Chengdu", "country": "China", "code": "CTU"},
        {"city": "Ho Chi Minh City", "country": "Vietnam", "code": "SGN"},
        {"city": "Hanoi", "country": "Vietnam", "code": "HAN"},
        {"city": "Jakarta", "country": "Indonesia", "code": "CGK"},
        {"city": "Bali", "country": "Indonesia", "code": "DPS"},
    ]
    
    query_lower = query.lower()
    results = []
    
    for city in cities:
        if (query_lower in city["city"].lower() or 
            query_lower in city["country"].lower() or
            query_lower in city["code"].lower()):
            results.append(CitySearchResult(
                placeId=f"local_{city['code']}",
                city=city["city"],
                country=city["country"],
                airportCode=city["code"],
                displayName=f"{city['city']}, {city['country']} ({city['code']})"
            ))
            
            if len(results) >= limit:
                break
    
    return results
