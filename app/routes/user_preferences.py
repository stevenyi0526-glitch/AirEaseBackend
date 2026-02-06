"""
AirEase Backend - User Preferences API Routes
Endpoints for tracking user behavior and retrieving preferences.

These endpoints are called by the frontend to:
1. Track sort actions
2. Track time filter selections
3. Track flight selections
4. Retrieve user preferences for UI personalization
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from pydantic import BaseModel

from app.database import get_db, UserDB
from app.services.user_preferences_service import user_preferences_service
from app.routes.auth import get_current_user, require_auth


router = APIRouter(prefix="/v1/preferences", tags=["User Preferences"])


# ============================================================
# Request Models
# ============================================================

class SortActionRequest(BaseModel):
    """Request to track a sort action"""
    sort_by: str  # price, duration, score, departure, arrival


class TimeFilterRequest(BaseModel):
    """Request to track a time filter action"""
    time_range: str  # "6-12", "morning", etc.


class FlightSelectionRequest(BaseModel):
    """Request to track a flight selection"""
    flight_id: str
    flight_number: Optional[str] = None
    airline: str
    airline_code: Optional[str] = None
    departure_city: str
    arrival_city: str
    departure_time: str  # ISO format
    price: float
    overall_score: float
    cabin: Optional[str] = "economy"


# ============================================================
# Tracking Endpoints (POST)
# ============================================================

@router.post("/track/sort")
async def track_sort_action(
    request: SortActionRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_auth)
):
    """
    Track when user clicks a sort option.
    
    Called from frontend when user changes sort selection.
    This data is used to determine the user's preferred sort dimension.
    
    Args:
        sort_by: The sort option selected (price, duration, score, departure, arrival)
    """
    success = user_preferences_service.track_sort_action(
        db, 
        current_user.user_id, 
        request.sort_by
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to track sort action")
    
    return {
        "message": "Sort action tracked",
        "sort_by": request.sort_by
    }


@router.post("/track/time-filter")
async def track_time_filter(
    request: TimeFilterRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_auth)
):
    """
    Track when user applies a time filter.
    
    Called from frontend when user selects a departure time range filter.
    This data is used to determine the user's preferred departure times.
    
    Args:
        time_range: The time range selected (e.g., "6-12", "morning")
    """
    success = user_preferences_service.track_time_filter(
        db, 
        current_user.user_id, 
        request.time_range
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to track time filter")
    
    return {
        "message": "Time filter tracked",
        "time_range": request.time_range
    }


@router.post("/track/flight-selection")
async def track_flight_selection(
    request: FlightSelectionRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_auth)
):
    """
    Track when user selects/clicks on a flight.
    
    Called from frontend when user clicks "View Details" on a flight.
    This data is used to determine:
    - Preferred airlines
    - Preferred departure times (extracted from the selected flight)
    
    Args:
        flight_id: Unique flight identifier
        airline: Airline name
        airline_code: Airline IATA code (optional)
        departure_city: Departure airport code
        arrival_city: Arrival airport code
        departure_time: ISO format datetime
        price: Flight price
        overall_score: AirEase score
    """
    flight_data = {
        "flight_id": request.flight_id,
        "flight_number": request.flight_number,
        "airline": request.airline,
        "airline_code": request.airline_code,
        "departure_city": request.departure_city,
        "arrival_city": request.arrival_city,
        "departure_time": request.departure_time,
        "price": request.price,
        "overall_score": request.overall_score,
        "cabin": request.cabin,
    }
    
    success = user_preferences_service.track_flight_selection(
        db, 
        current_user.user_id, 
        flight_data
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to track flight selection")
    
    return {
        "message": "Flight selection tracked",
        "flight_id": request.flight_id,
        "airline": request.airline
    }


# ============================================================
# Retrieval Endpoints (GET)
# ============================================================

@router.get("/my-preferences")
async def get_my_preferences(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_auth)
):
    """
    Get current user's aggregated preferences.
    
    Returns the full preference profile including:
    - Preferred sort dimension
    - Preferred time ranges
    - Preferred airlines
    - Price sensitivity
    - Detailed counts for all tracked actions
    
    Used for debugging and preference management UI.
    """
    preferences = user_preferences_service.get_user_preferences(
        db, 
        current_user.user_id
    )
    
    return preferences


@router.get("/for-recommendations")
async def get_preferences_for_recommendations(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
):
    """
    Get minimal preference data for the recommendation engine.
    
    Returns only the fields needed by the recommendation system:
    - preferred_sort
    - preferred_time_range
    - preferred_airlines (top 3)
    - price_sensitivity
    - has_preferences (boolean)
    
    This is the primary endpoint called by the recommendation service.
    """
    if not current_user:
        return {
            "preferred_sort": "score",
            "preferred_time_range": "6-12",
            "preferred_airlines": [],
            "price_sensitivity": "medium",
            "has_preferences": False,
        }
    
    preferences = user_preferences_service.get_preferences_for_recommendation(
        db, 
        current_user.user_id
    )
    
    return preferences


@router.delete("/clear")
async def clear_my_preferences(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_auth)
):
    """
    Clear all tracked preferences for the current user.
    
    Useful for testing or when user wants to reset their preferences.
    Deletes:
    - All sort action records
    - All time filter records
    - The preferences cache
    
    Note: Does NOT delete flight selection history.
    """
    from app.database import UserSortActionDB, UserTimeFilterActionDB, UserPreferencesCacheDB
    
    try:
        # Delete sort actions
        db.query(UserSortActionDB).filter(
            UserSortActionDB.user_id == current_user.user_id
        ).delete()
        
        # Delete time filter actions
        db.query(UserTimeFilterActionDB).filter(
            UserTimeFilterActionDB.user_id == current_user.user_id
        ).delete()
        
        # Delete cache
        db.query(UserPreferencesCacheDB).filter(
            UserPreferencesCacheDB.user_id == current_user.user_id
        ).delete()
        
        db.commit()
        
        return {"message": "Preferences cleared successfully"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to clear preferences: {str(e)}")
