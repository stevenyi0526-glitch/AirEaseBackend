"""
AirEase Backend - Recommendations Routes
AI-powered flight recommendation endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

from app.database import get_db, UserDB, FlightSelectionDB
from app.services.recommendation_service import recommendation_service
from app.routes.auth import get_current_user, require_auth


router = APIRouter(prefix="/v1/recommendations", tags=["recommendations"])


# ============================================================
# Request/Response Models
# ============================================================

class SortPreferenceRequest(BaseModel):
    """Request to update sort preference"""
    sort_by: str  # "score", "price", "duration", "departure", "arrival"


class FlightSelectionRequest(BaseModel):
    """Request to track flight selection"""
    flight_id: str
    departure_city: str
    arrival_city: str
    departure_time: datetime
    airline: str
    price: float
    overall_score: float
    cabin_class: str = "economy"


class UserPreferencesResponse(BaseModel):
    """User preferences for recommendations"""
    top_routes: List[dict]
    time_range_preferences: dict
    sort_preferences: dict
    preferred_sort: str
    preferred_time_range: str
    user_label: str


class RecommendationResponse(BaseModel):
    """AI recommendation response"""
    recommendations: List[dict]
    explanation: str
    preferences_used: dict


# ============================================================
# Endpoints
# ============================================================

@router.get("/preferences", response_model=UserPreferencesResponse)
async def get_user_preferences(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_auth)
):
    """
    Get user's preference profile based on search history and behavior.
    Requires authentication.
    """
    preferences = recommendation_service.get_user_preferences(db, current_user.user_id)
    return preferences


@router.post("/sort-preference")
async def update_sort_preference(
    request: SortPreferenceRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_auth)
):
    """
    Track when user changes sort option.
    Called from frontend when user selects a different sort option.
    """
    success = recommendation_service.update_sort_preference(
        db, 
        current_user.user_id, 
        request.sort_by
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update sort preference")
    
    return {"message": "Sort preference updated", "sort_by": request.sort_by}


@router.post("/flight-selection")
async def track_flight_selection(
    request: FlightSelectionRequest,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_auth)
):
    """
    Track when user clicks to view flight details.
    This data is used to improve recommendations.
    """
    selection = FlightSelectionDB(
        user_id=current_user.user_id,
        flight_id=request.flight_id,
        departure_city=request.departure_city,
        arrival_city=request.arrival_city,
        departure_time=request.departure_time,
        airline=request.airline,
        price=request.price,
        overall_score=request.overall_score,
        cabin_class=request.cabin_class,
    )
    
    db.add(selection)
    db.commit()
    
    return {"message": "Flight selection tracked", "flight_id": request.flight_id}


@router.post("/generate")
async def generate_recommendations(
    flights: List[dict],
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
):
    """
    Generate AI recommendations from a list of flights.
    
    This endpoint receives the search results and returns the top 3 recommended flights
    based on user's preferences and history.
    """
    if not current_user:
        # For non-authenticated users, return top 3 by overall score
        sorted_flights = sorted(
            flights, 
            key=lambda x: x.get("score", {}).get("overallScore", 0), 
            reverse=True
        )
        return {
            "recommendations": sorted_flights[:3],
            "explanation": "Top rated flights based on our scoring algorithm.",
            "preferences_used": {}
        }
    
    # Get user preferences
    preferences = recommendation_service.get_user_preferences(db, current_user.user_id)
    
    # Filter and rank recommendations
    recommendations = recommendation_service.filter_and_rank_recommendations(
        flights,
        preferences,
        {}  # search_params can be added if needed
    )
    
    # Generate AI explanation
    explanation = await recommendation_service.generate_recommendation_explanation(
        recommendations,
        preferences
    )
    
    return {
        "recommendations": recommendations,
        "explanation": explanation,
        "preferences_used": {
            "preferred_sort": preferences.get("preferred_sort"),
            "preferred_time_range": preferences.get("preferred_time_range"),
            "user_label": preferences.get("user_label"),
            "top_routes_count": len(preferences.get("top_routes", [])),
        }
    }


@router.get("/quick")
async def get_quick_recommendations(
    from_city: str = Query(..., description="Departure city code"),
    to_city: str = Query(..., description="Arrival city code"),
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
):
    """
    Get quick recommendation hints for a route.
    Returns user's preferences and suggested filters without actual flight data.
    """
    if not current_user:
        return {
            "has_preferences": False,
            "suggestions": []
        }
    
    preferences = recommendation_service.get_user_preferences(db, current_user.user_id)
    
    # Check if this route is in user's top routes
    is_frequent_route = any(
        r["from"] == from_city and r["to"] == to_city
        for r in preferences.get("top_routes", [])
    )
    
    suggestions = []
    
    if is_frequent_route:
        suggestions.append(f"This is one of your frequent routes!")
    
    preferred_time = preferences.get("preferred_time_range", "8-12")
    suggestions.append(f"You usually prefer departures between {preferred_time}")
    
    preferred_sort = preferences.get("preferred_sort", "overall")
    if preferred_sort == "price":
        suggestions.append("You tend to prioritize price - we'll highlight budget options")
    elif preferred_sort == "duration":
        suggestions.append("You prefer shorter flights - we'll highlight quick options")
    
    return {
        "has_preferences": True,
        "is_frequent_route": is_frequent_route,
        "preferred_time_range": preferred_time,
        "preferred_sort": preferred_sort,
        "user_label": preferences.get("user_label", "business"),
        "suggestions": suggestions
    }
