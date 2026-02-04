"""
AirEase Backend - Smart Flight Recommendation Service
AI-powered flight recommendations based on user behavior
"""

import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database import UserDB, SearchHistoryDB
from app.services.gemini_service import GeminiService


class RecommendationService:
    """
    Smart Flight Recommendation Service
    
    Analyzes user behavior to provide personalized flight recommendations:
    1. Top 3 most frequent routes
    2. Preferred departure time ranges
    3. Preferred sort dimensions (price, comfort, etc.)
    4. Use Gemini AI to generate recommendation explanations
    """
    
    # Time range mappings
    TIME_RANGES = {
        "0-4": (0, 4),
        "4-8": (4, 8),
        "8-12": (8, 12),
        "12-16": (12, 16),
        "16-20": (16, 20),
        "20-24": (20, 24),
    }
    
    def __init__(self):
        self.gemini = GeminiService()
    
    def get_user_preferences(self, db: Session, user_id: int) -> Dict[str, Any]:
        """
        Analyze user's search history and sort preferences to build a preference profile.
        
        Returns:
        {
            "top_routes": [{"from": "HKG", "to": "NRT", "count": 15}, ...],
            "time_range_preferences": {"8-12": 10, "16-20": 8, ...},
            "sort_preferences": {"overall": 5, "price": 12, "comfort": 3, ...},
            "preferred_sort": "price",
            "preferred_time_range": "8-12"
        }
        """
        user = db.query(UserDB).filter(UserDB.user_id == user_id).first()
        if not user:
            return self._get_default_preferences()
        
        # 1. Get top routes from search history
        top_routes = self._get_top_routes(db, user_id)
        
        # 2. Get time range preferences from search history
        time_range_prefs = self._get_time_range_preferences(db, user_id)
        
        # 3. Get sort preferences from user table
        sort_prefs = self._get_sort_preferences(user)
        
        # 4. Determine the most preferred sort dimension
        preferred_sort = max(sort_prefs.items(), key=lambda x: x[1])[0] if any(sort_prefs.values()) else "overall"
        
        # 5. Determine the most preferred time range
        preferred_time_range = max(time_range_prefs.items(), key=lambda x: x[1])[0] if any(time_range_prefs.values()) else "8-12"
        
        return {
            "top_routes": top_routes,
            "time_range_preferences": time_range_prefs,
            "sort_preferences": sort_prefs,
            "preferred_sort": preferred_sort,
            "preferred_time_range": preferred_time_range,
            "user_label": user.user_label or "business",
        }
    
    def _get_top_routes(self, db: Session, user_id: int, limit: int = 3) -> List[Dict[str, Any]]:
        """Get top N most searched routes for a user"""
        results = (
            db.query(
                SearchHistoryDB.departure_city,
                SearchHistoryDB.arrival_city,
                func.count(SearchHistoryDB.id).label("count")
            )
            .filter(SearchHistoryDB.user_id == user_id)
            .group_by(SearchHistoryDB.departure_city, SearchHistoryDB.arrival_city)
            .order_by(desc("count"))
            .limit(limit)
            .all()
        )
        
        return [
            {"from": r.departure_city, "to": r.arrival_city, "count": r.count}
            for r in results
        ]
    
    def _get_time_range_preferences(self, db: Session, user_id: int) -> Dict[str, int]:
        """
        Get time range preferences from search history.
        Since we store departure_time_range, count occurrences.
        """
        # Initialize all time ranges with 0
        time_prefs = {tr: 0 for tr in self.TIME_RANGES.keys()}
        
        results = (
            db.query(
                SearchHistoryDB.departure_time_range,
                func.count(SearchHistoryDB.id).label("count")
            )
            .filter(
                SearchHistoryDB.user_id == user_id,
                SearchHistoryDB.departure_time_range.isnot(None)
            )
            .group_by(SearchHistoryDB.departure_time_range)
            .all()
        )
        
        for r in results:
            if r.departure_time_range in time_prefs:
                time_prefs[r.departure_time_range] = r.count
        
        return time_prefs
    
    def _get_sort_preferences(self, user: UserDB) -> Dict[str, int]:
        """Get sort preferences from user's sort counters"""
        return {
            "overall": getattr(user, "sort_by_overall_count", 0) or 0,
            "price": getattr(user, "sort_by_price_count", 0) or 0,
            "comfort": getattr(user, "sort_by_comfort_count", 0) or 0,
            "duration": getattr(user, "sort_by_duration_count", 0) or 0,
            "departure": getattr(user, "sort_by_departure_count", 0) or 0,
            "arrival": getattr(user, "sort_by_arrival_count", 0) or 0,
        }
    
    def _get_default_preferences(self) -> Dict[str, Any]:
        """Return default preferences for new users"""
        return {
            "top_routes": [],
            "time_range_preferences": {tr: 0 for tr in self.TIME_RANGES.keys()},
            "sort_preferences": {"overall": 0, "price": 0, "comfort": 0, "duration": 0, "departure": 0, "arrival": 0},
            "preferred_sort": "overall",
            "preferred_time_range": "8-12",
            "user_label": "business",
        }
    
    def update_sort_preference(self, db: Session, user_id: int, sort_by: str) -> bool:
        """
        Increment the sort preference counter for a user.
        Called when user changes sort option in the UI.
        """
        user = db.query(UserDB).filter(UserDB.user_id == user_id).first()
        if not user:
            return False
        
        column_map = {
            "score": "sort_by_overall_count",
            "overall": "sort_by_overall_count",
            "price": "sort_by_price_count",
            "comfort": "sort_by_comfort_count",
            "duration": "sort_by_duration_count",
            "departure": "sort_by_departure_count",
            "arrival": "sort_by_arrival_count",
        }
        
        column_name = column_map.get(sort_by)
        if column_name:
            current_value = getattr(user, column_name, 0) or 0
            setattr(user, column_name, current_value + 1)
            db.commit()
            return True
        
        return False
    
    def filter_and_rank_recommendations(
        self,
        flights: List[Dict[str, Any]],
        preferences: Dict[str, Any],
        search_params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Filter and rank flights based on user preferences to get top 3 recommendations.
        
        Scoring factors:
        1. Route match with top routes (+30 points)
        2. Time range match (+20 points)
        3. Sort preference alignment (+25 points)
        4. User label (business/student/family) alignment (+15 points)
        5. Overall score normalization (+10 points)
        """
        if not flights:
            return []
        
        scored_flights = []
        
        preferred_time_range = preferences.get("preferred_time_range", "8-12")
        preferred_sort = preferences.get("preferred_sort", "overall")
        user_label = preferences.get("user_label", "business")
        top_routes = preferences.get("top_routes", [])
        
        # Get time range bounds
        time_start, time_end = self.TIME_RANGES.get(preferred_time_range, (8, 12))
        
        for flight in flights:
            score = 0
            reasons = []
            
            flight_data = flight.get("flight", flight)
            score_data = flight.get("score", {})
            
            # 1. Route match with top routes
            dep_city = flight_data.get("departureCityCode") or flight_data.get("departure_city_code", "")
            arr_city = flight_data.get("arrivalCityCode") or flight_data.get("arrival_city_code", "")
            
            for i, route in enumerate(top_routes):
                if route["from"] == dep_city and route["to"] == arr_city:
                    score += 30 - (i * 5)  # Top route gets 30, second 25, third 20
                    reasons.append(f"Matches your frequent route #{i+1}")
                    break
            
            # 2. Time range match
            departure_time = flight_data.get("departureTime") or flight_data.get("departure_time")
            if departure_time:
                if isinstance(departure_time, str):
                    try:
                        dt = datetime.fromisoformat(departure_time.replace("Z", "+00:00"))
                        hour = dt.hour
                    except:
                        hour = 12
                else:
                    hour = departure_time.hour
                
                if time_start <= hour < time_end:
                    score += 20
                    reasons.append(f"Departs in your preferred time ({preferred_time_range})")
            
            # 3. Sort preference alignment
            if preferred_sort == "price":
                # Lower price = higher score
                price = flight_data.get("price", 0)
                if price > 0:
                    # Normalize: assume price range 500-5000
                    price_score = max(0, 25 - (price / 200))
                    score += price_score
                    if price_score > 15:
                        reasons.append("Great price match")
            elif preferred_sort == "overall":
                overall = score_data.get("overallScore", 70)
                score += (overall / 100) * 25
                if overall >= 80:
                    reasons.append("High overall score")
            elif preferred_sort == "duration":
                duration = flight_data.get("durationMinutes") or flight_data.get("duration_minutes", 300)
                # Shorter = better
                duration_score = max(0, 25 - (duration / 60))
                score += duration_score
                if duration_score > 15:
                    reasons.append("Short flight duration")
            
            # 4. User label alignment
            if user_label == "student":
                # Students prefer low prices
                price = flight_data.get("price", 0)
                if price < 1000:
                    score += 15
                    reasons.append("Budget-friendly for students")
            elif user_label == "business":
                # Business travelers prefer comfort and reliability
                comfort = score_data.get("dimensions", {}).get("comfort", 5)
                reliability = score_data.get("dimensions", {}).get("reliability", 5)
                if comfort >= 7 or reliability >= 7:
                    score += 15
                    reasons.append("High comfort/reliability for business")
            elif user_label == "family":
                # Families prefer direct flights and good timing
                stops = flight_data.get("stops", 0)
                if stops == 0:
                    score += 15
                    reasons.append("Direct flight - great for families")
            
            # 5. Overall score bonus
            overall = score_data.get("overallScore", 70)
            score += (overall / 100) * 10
            
            scored_flights.append({
                **flight,
                "recommendation_score": round(score, 1),
                "recommendation_reasons": reasons[:3],  # Top 3 reasons
            })
        
        # Sort by recommendation score
        scored_flights.sort(key=lambda x: x["recommendation_score"], reverse=True)
        
        return scored_flights[:3]
    
    async def generate_recommendation_explanation(
        self,
        recommendations: List[Dict[str, Any]],
        preferences: Dict[str, Any]
    ) -> str:
        """
        Use Gemini AI to generate a natural language explanation
        for why these flights are recommended.
        """
        if not recommendations:
            return "No recommendations available based on your search history."
        
        # Build context for Gemini
        user_label = preferences.get("user_label", "traveler")
        preferred_sort = preferences.get("preferred_sort", "overall")
        top_routes = preferences.get("top_routes", [])
        
        flights_summary = []
        for i, rec in enumerate(recommendations[:3]):
            flight = rec.get("flight", rec)
            score = rec.get("score", {})
            reasons = rec.get("recommendation_reasons", [])
            
            flights_summary.append(
                f"{i+1}. {flight.get('airline', 'Unknown')} - "
                f"{flight.get('departureCityCode', '')} to {flight.get('arrivalCityCode', '')} - "
                f"Score: {score.get('overallScore', 0)} - "
                f"Reasons: {', '.join(reasons)}"
            )
        
        prompt = f"""Based on this {user_label} traveler's preferences:
- They often sort by: {preferred_sort}
- Their top routes: {', '.join([f"{r['from']}->{r['to']}" for r in top_routes]) if top_routes else 'No history yet'}

We recommend these flights:
{chr(10).join(flights_summary)}

Generate a brief, friendly 2-sentence explanation of why these are good recommendations.
Focus on how they match the user's travel patterns."""

        try:
            explanation = await self.gemini._generate_text(prompt, max_tokens=150)
            return explanation
        except Exception as e:
            print(f"Gemini recommendation explanation error: {e}")
            return "These flights are recommended based on your search history and preferences."


# Singleton instance
recommendation_service = RecommendationService()
