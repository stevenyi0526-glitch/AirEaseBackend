"""
AirEase Backend - Recommendations Routes
Simplified AI-powered flight recommendation endpoints.

3 Internal Questions:
  Q1: What departure time does the user prefer?
  Q2: What dimensions does the user prefer? (top 2 or top 1)
  Q3: What specific airline does the user prefer?
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
    
    Uses the simplified 3-question approach:
    Q1: Preferred departure time
    Q2: Preferred dimensions (price/duration/comfort)
    Q3: Preferred airline
    
    Returns top 3 recommended flights.
    """
    if not current_user:
        # Non-authenticated: filter to direct flights first, then sort by overall score
        direct_flights = [f for f in flights if f.get("flight", f).get("stops", 0) == 0]
        pool = direct_flights if len(direct_flights) >= 3 else flights
        sorted_flights = sorted(
            pool,
            key=lambda x: x.get("score", {}).get("overallScore", 0),
            reverse=True
        )
        return {
            "recommendations": sorted_flights[:3],
            "explanation": "Top rated direct flights based on our scoring algorithm.",
            "preferences_used": {}
        }
    
    # Get the 3 answers from user data
    answers = recommendation_service.get_three_answers(db, current_user.user_id)
    
    # Score and rank flights
    recommendations = recommendation_service.filter_and_rank_recommendations(
        flights, answers, {}
    )
    
    # Generate simple explanation (no API call)
    explanation = recommendation_service.generate_explanation(answers)
    
    return {
        "recommendations": recommendations,
        "explanation": explanation,
        "preferences_used": {
            "preferred_time": answers.get("preferred_time"),
            "preferred_dimensions": answers.get("preferred_dimensions"),
            "preferred_airline": answers.get("preferred_airline"),
            "user_label": answers.get("user_label"),
            "has_data": answers.get("has_data"),
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
    Returns the 3 answers as suggestions.
    """
    if not current_user:
        return {
            "has_preferences": False,
            "suggestions": []
        }
    
    answers = recommendation_service.get_three_answers(db, current_user.user_id)
    
    suggestions = []
    t = answers.get("preferred_time", "6-12")
    suggestions.append(f"You prefer departures between {t}")
    
    dims = answers.get("preferred_dimensions", [])
    dim_labels = {"price": "price", "duration": "short flights", "comfort": "comfort"}
    if dims:
        suggestions.append(f"You prioritize {' & '.join(dim_labels.get(d, d) for d in dims)}")
    
    airline = answers.get("preferred_airline")
    if airline:
        suggestions.append(f"You like flying {airline}")
    
    return {
        "has_preferences": answers.get("has_data", False),
        "preferred_time": t,
        "preferred_dimensions": dims,
        "preferred_airline": airline,
        "user_label": answers.get("user_label", "business"),
        "suggestions": suggestions
    }
