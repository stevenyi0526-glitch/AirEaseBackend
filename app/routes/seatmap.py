"""
AirEase Backend - SeatMap API Routes
座位图相关API路由

Fetches seat map data on-demand when user views flight details.
Uses Amadeus SeatMap Display API v1.

When seatmap data is available, Amadeus amenities are used to:
1. Enrich FlightFacilities with accurate WiFi, power, meal, legroom data
2. Recalculate comfort & amenities scores using real API data instead of DB defaults
3. Return updated facilities + score to the frontend for live refresh
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Dict, Any
import logging

from app.services.serpapi_service import serpapi_flight_service
from app.services.amadeus_seatmap_service import amadeus_seatmap_service
from app.services.aircraft_comfort_service import AircraftComfortService
from app.services.airline_reviews_service import AirlineReviewsService
from app.services.scoring_service import ScoringService
from app.services.airline_reliability_service import AirlineReliabilityService
from app.models import FlightFacilities, ScoreDimensions
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/seatmap", tags=["SeatMap"])


def _extract_amenities_from_seatmap(seatmap_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract amenity flags from Amadeus seatmap response for scoring.
    
    Maps Amadeus amenities to our FlightFacilities fields:
    - seat.legSpace → seat_pitch_inches (overrides DB value)
    - seat.tilt → seat tilt category (FULL_FLAT, ANGLE_FLAT, NORMAL)
    - wifi → has_wifi, wifi_free
    - power → has_power, has_usb
    - entertainment → has_ife
    - food → meal_included, meal_type
    - beverage → beverage info
    """
    segments = seatmap_data.get("segments", [])
    if not segments:
        return {}
    
    # Use first segment's amenities (primary flight)
    amenities = segments[0].get("amenities", {})
    if not amenities:
        return {}
    
    result = {}
    
    # Legroom / seat pitch
    seat = amenities.get("seat", {})
    if seat:
        leg_space = seat.get("legSpace")
        if leg_space and isinstance(leg_space, (int, float)):
            result["seat_pitch_inches"] = int(leg_space)
            unit = seat.get("legSpaceUnit", "in")
            result["legroom"] = f"{int(leg_space)} {unit}"
            # Categorize
            if leg_space >= 34:
                result["seat_pitch_category"] = "Above average"
            elif leg_space >= 31:
                result["seat_pitch_category"] = "Average"
            else:
                result["seat_pitch_category"] = "Below average"
        
        tilt = seat.get("tilt")
        if tilt:
            result["seat_tilt"] = tilt  # FULL_FLAT, ANGLE_FLAT, NORMAL
    
    # WiFi
    wifi = amenities.get("wifi", {})
    if wifi:
        result["has_wifi"] = True
        result["wifi_free"] = not wifi.get("isChargeable", True)
        result["wifi_coverage"] = wifi.get("wifiCoverage")  # FULL, PARTIAL
    else:
        result["has_wifi"] = False
    
    # Power
    power = amenities.get("power", {})
    if power:
        result["has_power"] = True
        result["has_usb"] = "USB" in (power.get("usbType") or "").upper()
        result["power_type"] = power.get("powerType")  # PLUG, USB_PORT, PLUG_OR_USB_PORT
    else:
        result["has_power"] = False
    
    # Entertainment
    entertainment = amenities.get("entertainment")
    if entertainment:
        result["has_ife"] = True
        if isinstance(entertainment, list) and entertainment:
            result["ife_type"] = entertainment[0].get("entertainmentType", "In-flight entertainment")
        else:
            result["ife_type"] = "In-flight entertainment"
    else:
        result["has_ife"] = False
    
    # Food / Meals
    food = amenities.get("food", {})
    if food:
        result["meal_included"] = True
        food_type = food.get("foodType", "")
        result["meal_type"] = food_type.replace("_", " ").title() if food_type else "Meal service"
        result["meal_chargeable"] = food.get("isChargeable", False)
    else:
        result["meal_included"] = False
    
    # Beverage
    beverage = amenities.get("beverage", {})
    if beverage:
        result["has_beverage"] = True
        result["beverage_type"] = beverage.get("beverageType", "").replace("_", " ").title()
        result["beverage_chargeable"] = beverage.get("isChargeable", False)
    
    return result


def _recalculate_score_with_amadeus(
    flight_with_score,
    amadeus_amenities: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Recalculate comfort and overall scores using Amadeus amenity data.
    
    This replaces the DB-fetched comfort data with real API data:
    - legroom from Amadeus replaces seat_pitch from aircraft_comfort DB
    - WiFi/power/IFE from Amadeus replaces SerpAPI extension parsing
    - Meal data from Amadeus replaces SerpAPI guessing
    
    Returns dict with updated score dimensions and facilities.
    """
    flight = flight_with_score.flight
    old_score = flight_with_score.score
    old_facilities = flight_with_score.facilities
    
    # Build updated facilities from Amadeus data
    has_wifi = amadeus_amenities.get("has_wifi", old_facilities.has_wifi or False)
    has_power = amadeus_amenities.get("has_power", old_facilities.has_power or False)
    has_ife = amadeus_amenities.get("has_ife", old_facilities.has_ife or False)
    meal_included = amadeus_amenities.get("meal_included", old_facilities.meal_included or False)
    legroom_inches = amadeus_amenities.get("seat_pitch_inches", old_facilities.seat_pitch_inches)
    
    cabin_class = flight.cabin or "economy"
    
    # Recalculate comfort score with Amadeus legroom as override
    comfort, comfort_details = AircraftComfortService.calculate_comfort_score(
        aircraft_model=flight.aircraft_model,
        cabin_class=cabin_class,
        has_wifi=has_wifi,
        has_power=has_power,
        has_ife=has_ife,
        legroom_override=legroom_inches
    )
    comfort = round(comfort, 1)
    
    # Get reliability (unchanged - not from Amadeus)
    reliability = old_score.dimensions.reliability
    
    # Get service (unchanged - from airline reviews DB)
    service = old_score.dimensions.service
    
    # Get value (unchanged - from price insights)
    value = old_score.dimensions.value
    
    # Recalculate overall score with updated amenities
    stops = flight.stops or 0
    duration_minutes = flight.duration_minutes
    
    overall, score_details = ScoringService.calculate_overall_score(
        reliability=reliability,
        comfort=comfort,
        service=service,
        value=value,
        traveler_type=old_score.persona_weights_applied or "default",
        has_wifi=has_wifi,
        has_power=has_power,
        has_ife=has_ife,
        has_meal=meal_included,
        stops=stops,
        duration_minutes=duration_minutes,
        apply_boost=True
    )
    
    # Build updated facilities dict
    updated_facilities = {
        "hasWifi": has_wifi,
        "hasPower": has_power,
        "seatPitchInches": legroom_inches,
        "seatPitchCategory": amadeus_amenities.get("seat_pitch_category", old_facilities.seat_pitch_category),
        "hasIFE": has_ife,
        "ifeType": amadeus_amenities.get("ife_type", old_facilities.ife_type),
        "mealIncluded": meal_included,
        "mealType": amadeus_amenities.get("meal_type", old_facilities.meal_type),
        "wifiFree": amadeus_amenities.get("wifi_free", old_facilities.wifi_free),
        "hasUSB": amadeus_amenities.get("has_usb", old_facilities.has_usb),
        "legroom": amadeus_amenities.get("legroom", old_facilities.legroom),
        "dataSource": "amadeus",  # Mark that this data came from Amadeus API
        # Extra Amadeus-only fields
        "seatTilt": amadeus_amenities.get("seat_tilt"),
        "wifiCoverage": amadeus_amenities.get("wifi_coverage"),
        "powerType": amadeus_amenities.get("power_type"),
        "mealChargeable": amadeus_amenities.get("meal_chargeable"),
        "hasBeverage": amadeus_amenities.get("has_beverage"),
        "beverageType": amadeus_amenities.get("beverage_type"),
        "beverageChargeable": amadeus_amenities.get("beverage_chargeable"),
    }
    
    # Build updated score
    updated_score = {
        "overallScore": overall,
        "dimensions": {
            "reliability": reliability,
            "comfort": comfort,
            "service": service,
            "value": value,
        },
        "comfortDetails": {
            "dataSource": comfort_details.get("data_source", "default"),
            "seatPitch": comfort_details.get("seat_pitch"),
            "seatWidth": comfort_details.get("seat_width"),
            "componentScores": comfort_details.get("component_scores"),
        },
        "amenitiesScore": score_details.get("raw_scores", {}).get("amenities"),
    }
    
    # Also update the cached FlightWithScore so subsequent detail fetches use Amadeus data
    try:
        new_facilities = FlightFacilities(
            has_wifi=has_wifi,
            has_power=has_power,
            seat_pitch_inches=legroom_inches,
            seat_pitch_category=amadeus_amenities.get("seat_pitch_category", old_facilities.seat_pitch_category),
            has_ife=has_ife,
            ife_type=amadeus_amenities.get("ife_type", old_facilities.ife_type),
            meal_included=meal_included,
            meal_type=amadeus_amenities.get("meal_type", old_facilities.meal_type),
            wifi_free=amadeus_amenities.get("wifi_free", old_facilities.wifi_free),
            has_usb=amadeus_amenities.get("has_usb", old_facilities.has_usb),
            legroom=amadeus_amenities.get("legroom", old_facilities.legroom),
            raw_extensions=old_facilities.raw_extensions,
        )
        
        new_dimensions = ScoreDimensions(
            reliability=reliability,
            comfort=comfort,
            service=service,
            value=value
        )
        
        # Update cache in-place
        flight_with_score.facilities = new_facilities
        flight_with_score.score.overall_score = overall
        flight_with_score.score.dimensions = new_dimensions
        
        logger.info(
            f"Updated cached score: comfort {old_score.dimensions.comfort} → {comfort}, "
            f"overall {old_score.overall_score} → {overall}"
        )
    except Exception as e:
        logger.warning(f"Failed to update flight cache: {e}")
    
    return {
        "updatedFacilities": updated_facilities,
        "updatedScore": updated_score,
    }


@router.get(
    "/{flight_id}",
    summary="获取航班座位图",
    description="根据航班ID获取座位图数据。仅在用户查看航班详情时按需调用。"
)
async def get_seatmap(flight_id: str):
    """
    Get seat map for a specific flight.
    
    This endpoint is called ON-DEMAND when a user clicks to view flight details.
    It does NOT fetch seat maps for all search results.
    
    Flow:
    1. Look up the flight from SerpAPI cache to get carrier code, flight number, route, date
    2. Use that data to search Amadeus Flight Offers Search
    3. POST the offer to Amadeus SeatMap Display API
    4. Return parsed seat map with deck layout, seats, amenities, legroom info
    
    Returns:
    - segments[]: Array of seat map segments
      - decks[]: Deck configuration, seats, facilities
      - amenities: power, legroom/seat info, wifi, entertainment, food
    - dictionaries: Code mappings for seat characteristics
    """
    # Step 1: Get flight data from SerpAPI cache
    flight_with_score = serpapi_flight_service._flight_cache.get(flight_id)
    
    if not flight_with_score:
        raise HTTPException(
            status_code=404,
            detail="Flight not found in cache. Please search again to refresh data."
        )
    
    flight = flight_with_score.flight
    
    # Extract needed data for Amadeus API
    carrier_code = flight.airline_code
    raw_flight_number = flight.flight_number  # e.g., "CX 520" or "CX520"
    
    # Extract just the numeric part of flight number
    # SerpAPI gives "CX 520" format, Amadeus needs carrier="CX" and number="520"
    flight_num_only = raw_flight_number
    if carrier_code and raw_flight_number.startswith(carrier_code):
        flight_num_only = raw_flight_number[len(carrier_code):].strip()
    else:
        # Try to split on space
        parts = raw_flight_number.split()
        if len(parts) >= 2:
            flight_num_only = parts[-1]
    
    origin = flight.departure_airport_code
    destination = flight.arrival_airport_code
    
    # Extract departure date from datetime
    departure_date = flight.departure_time.strftime("%Y-%m-%d")
    cabin = flight.cabin or "economy"
    
    logger.info(
        f"Fetching seatmap for flight {carrier_code}{flight_num_only} "
        f"({origin} → {destination}) on {departure_date}"
    )
    
    # Step 2: Check if Amadeus is configured
    if not settings.amadeus_api_key:
        raise HTTPException(
            status_code=503,
            detail="Amadeus API not configured. Seat map unavailable."
        )
    
    # Step 3: Fetch seat map from Amadeus
    try:
        seatmap_data = await amadeus_seatmap_service.get_seatmap(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            carrier_code=carrier_code,
            flight_number=flight_num_only,
            cabin=cabin
        )
        
        if not seatmap_data:
            return {
                "available": False,
                "message": "Seat map not available for this flight. This may be due to the airline or route not being supported.",
                "flightInfo": {
                    "flightNumber": f"{carrier_code}{flight_num_only}",
                    "route": f"{origin} → {destination}",
                    "date": departure_date,
                    "carrier": carrier_code,
                }
            }
        
        # Extract Amadeus amenities and recalculate score
        amadeus_amenities = _extract_amenities_from_seatmap(seatmap_data)
        enrichment = {}
        if amadeus_amenities:
            enrichment = _recalculate_score_with_amadeus(flight_with_score, amadeus_amenities)
            logger.info(
                f"Enriched flight {carrier_code}{flight_num_only} with Amadeus amenities: "
                f"wifi={amadeus_amenities.get('has_wifi')}, power={amadeus_amenities.get('has_power')}, "
                f"ife={amadeus_amenities.get('has_ife')}, meal={amadeus_amenities.get('meal_included')}, "
                f"legroom={amadeus_amenities.get('seat_pitch_inches')}"
            )
        
        return {
            "available": True,
            "flightInfo": {
                "flightNumber": f"{carrier_code}{flight_num_only}",
                "route": f"{origin} → {destination}",
                "date": departure_date,
                "carrier": carrier_code,
                "aircraft": flight.aircraft_model,
            },
            "seatmap": seatmap_data,
            **enrichment,  # includes updatedFacilities + updatedScore
        }
        
    except Exception as e:
        logger.error(f"Error fetching seatmap: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch seat map: {str(e)}"
        )


@router.get(
    "/search/by-flight",
    summary="按航班号获取座位图",
    description="直接使用航班号和日期获取座位图（不需要先搜索航班）"
)
async def get_seatmap_by_flight(
    carrier: str = Query(..., description="航空公司IATA代码 (e.g., CX, AA, UA)"),
    flight_number: str = Query(..., description="航班号 (e.g., 520, 100)"),
    origin: str = Query(..., description="出发机场IATA代码 (e.g., HKG)"),
    destination: str = Query(..., description="到达机场IATA代码 (e.g., NRT)"),
    date: str = Query(..., description="出发日期 (YYYY-MM-DD)"),
    cabin: str = Query("economy", description="舱位: economy/business/first"),
):
    """
    Get seat map by flight number without needing a cached flight.
    Useful for direct lookups.
    """
    if not settings.amadeus_api_key:
        raise HTTPException(
            status_code=503,
            detail="Amadeus API not configured."
        )
    
    try:
        seatmap_data = await amadeus_seatmap_service.get_seatmap(
            origin=origin,
            destination=destination,
            departure_date=date,
            carrier_code=carrier,
            flight_number=flight_number,
            cabin=cabin
        )
        
        if not seatmap_data:
            return {
                "available": False,
                "message": "Seat map not available for this flight.",
                "flightInfo": {
                    "flightNumber": f"{carrier}{flight_number}",
                    "route": f"{origin} → {destination}",
                    "date": date,
                    "carrier": carrier,
                }
            }
        
        # Extract amenities from seatmap for display
        amadeus_amenities = _extract_amenities_from_seatmap(seatmap_data)
        
        return {
            "available": True,
            "flightInfo": {
                "flightNumber": f"{carrier}{flight_number}",
                "route": f"{origin} → {destination}",
                "date": date,
                "carrier": carrier,
            },
            "seatmap": seatmap_data,
            "updatedFacilities": amadeus_amenities if amadeus_amenities else None,
        }
    
    except Exception as e:
        logger.error(f"Error fetching seatmap by flight: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch seat map: {str(e)}"
        )
