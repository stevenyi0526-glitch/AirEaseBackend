"""
AirEase Backend - Smart Flight Recommendation Service
Simplified AI recommendations based on 3 core user preferences.

3 Internal Questions:
  Q1: What departure time does the user prefer?
  Q2: What dimensions does the user prefer? (top 2, or top 1 if 2nd is tied)
      Dimensions: duration, price, comfort
  Q3: What specific airline does the user prefer?

Data sources: user_preferences_cache (aggregated from user_sort_actions,
user_time_filter_actions, flight_selections tables) + users table (user_label).
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from app.database import UserDB
from app.services.user_preferences_service import user_preferences_service


# Mapping from sort_dimension names to the 3 core dimensions
SORT_TO_DIMENSION = {
    "price": "price",
    "duration": "duration",
    "score": "comfort",      # "score" / "overall" maps to comfort
    "overall": "comfort",
    "comfort": "comfort",
    "departure": "duration",  # departure time sorting → efficiency-minded → duration
    "arrival": "duration",
}


class RecommendationService:
    """
    Simplified recommendation engine.
    
    Answers 3 questions from user data, then scores flights accordingly.
    """

    def __init__(self):
        pass

    # ================================================================
    # Core: derive the 3 answers from DB data
    # ================================================================

    def get_three_answers(self, db: Session, user_id: int) -> Dict[str, Any]:
        """
        Derive the 3 recommendation answers from the user's preference data.

        Returns:
        {
            "preferred_time": "6-12",          # Q1
            "preferred_dimensions": ["price"], # Q2 – top 1 or top 2
            "preferred_airline": "ANA",        # Q3 – top airline or None
            "has_data": True/False,
            "user_label": "business"
        }
        """
        user = db.query(UserDB).filter(UserDB.user_id == user_id).first()
        user_label = user.user_label if user else "business"

        cached = user_preferences_service.get_user_preferences(db, user_id)

        if not cached.get("has_preferences", False):
            # No user data at all → return label-based defaults
            return self._defaults_from_label(user_label)

        # --- Q1: Preferred departure time ---
        preferred_time = cached.get("preferred_time_range", "6-12")

        # --- Q2: Preferred dimensions (top 2, or top 1 if 2nd tied) ---
        preferred_dimensions = self._derive_dimensions(cached)

        # --- Q3: Preferred airline ---
        airlines_list = cached.get("preferred_airlines", [])
        preferred_airline = airlines_list[0] if airlines_list else None

        return {
            "preferred_time": preferred_time,
            "preferred_dimensions": preferred_dimensions,
            "preferred_airline": preferred_airline,
            "has_data": True,
            "user_label": user_label,
        }

    def _derive_dimensions(self, cached: Dict[str, Any]) -> List[str]:
        """
        Derive top dimensions from sort_counts.
        
        Maps sort actions to 3 buckets: price, duration, comfort.
        Returns top 2 dimensions, or top 1 if the 2nd-place count is tied
        with all other 2nd-place candidates.
        """
        sort_counts = cached.get("sort_counts", {})
        if not sort_counts:
            return ["comfort"]  # default

        # Aggregate into 3 buckets
        buckets: Dict[str, int] = {"price": 0, "duration": 0, "comfort": 0}
        for dim, count in sort_counts.items():
            mapped = SORT_TO_DIMENSION.get(dim, "comfort")
            buckets[mapped] += count

        # Sort descending by count
        ranked = sorted(buckets.items(), key=lambda x: x[1], reverse=True)

        if len(ranked) == 0:
            return ["comfort"]

        top_name, top_count = ranked[0]

        if top_count == 0:
            return ["comfort"]

        if len(ranked) == 1:
            return [top_name]

        second_name, second_count = ranked[1]

        if second_count == 0:
            return [top_name]

        # Check if 2nd and 3rd are the same count → only return top 1
        if len(ranked) >= 3:
            third_count = ranked[2][1]
            if second_count == third_count and second_count > 0:
                # 2nd place is tied with 3rd → ambiguous, return only top 1
                return [top_name]

        # Otherwise return top 2
        return [top_name, second_name]

    def _defaults_from_label(self, user_label: str) -> Dict[str, Any]:
        """Return sensible defaults based on user_label when no behavior data."""
        label_defaults = {
            "student":  {"preferred_time": "6-12", "preferred_dimensions": ["price"],              "preferred_airline": None},
            "business": {"preferred_time": "6-12", "preferred_dimensions": ["comfort", "duration"], "preferred_airline": None},
            "family":   {"preferred_time": "6-12", "preferred_dimensions": ["comfort", "price"],    "preferred_airline": None},
        }
        defaults = label_defaults.get(user_label, label_defaults["business"])
        return {**defaults, "has_data": False, "user_label": user_label}

    # ================================================================
    # Scoring: rank flights using the 3 answers
    # ================================================================

    def filter_and_rank_recommendations(
        self,
        flights: List[Dict[str, Any]],
        preferences: Dict[str, Any],
        search_params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Score and rank flights using the 3 simple preference answers.
        Returns top 3 flights.
        """
        if not flights:
            return []

        # Extract the 3 answers (already computed in preferences)
        preferred_time = preferences.get("preferred_time", "6-12")
        preferred_dims = preferences.get("preferred_dimensions", ["comfort"])
        preferred_airline = preferences.get("preferred_airline")
        user_label = preferences.get("user_label", "business")

        # Parse time range
        try:
            parts = preferred_time.split("-")
            time_start, time_end = int(parts[0]), int(parts[1])
        except Exception:
            time_start, time_end = 6, 12

        scored = []
        for flight in flights:
            pts = 0.0
            reasons: List[str] = []

            fd = flight.get("flight", flight)
            sd = flight.get("score", {})
            dims = sd.get("dimensions", {})

            # --- Q1: Time match (max +25) ---
            dep_time = fd.get("departureTime") or fd.get("departure_time")
            if dep_time:
                hour = self._extract_hour(dep_time)
                if time_start <= hour < time_end:
                    pts += 25
                    reasons.append(f"Departs {time_start}:00–{time_end}:00 ✓")

            # --- Q2: Dimension match (max +40 total) ---
            for i, dim in enumerate(preferred_dims):
                weight = 25 if i == 0 else 15  # primary dim gets more weight
                if dim == "price":
                    # Lower price = higher points; normalize against flight set
                    price = fd.get("price", 9999)
                    # Value dimension score from our scoring (0-10)
                    value_score = dims.get("value", 5)
                    pts += (value_score / 10) * weight
                    if value_score >= 7:
                        reasons.append("Great value" if i == 0 else "Good price")
                elif dim == "duration":
                    efficiency = dims.get("efficiency", 5)
                    pts += (efficiency / 10) * weight
                    if efficiency >= 7:
                        reasons.append("Short duration" if i == 0 else "Efficient")
                elif dim == "comfort":
                    comfort = dims.get("comfort", 5)
                    pts += (comfort / 10) * weight
                    if comfort >= 7:
                        reasons.append("High comfort" if i == 0 else "Comfortable")

            # --- Q3: Airline match (max +20) ---
            if preferred_airline:
                airline_name = fd.get("airline", "")
                airline_code = fd.get("airlineCode") or fd.get("airline_code", "")
                if (preferred_airline.lower() in airline_name.lower()
                        or preferred_airline.upper() == airline_code.upper()):
                    pts += 20
                    reasons.append(f"Your airline: {airline_name}")

            # --- Baseline: overall score bonus (max +15) ---
            overall = sd.get("overallScore", 70)
            pts += (overall / 100) * 15

            scored.append({
                **flight,
                "recommendation_score": round(pts, 1),
                "recommendation_reasons": reasons[:3],
            })

        scored.sort(key=lambda x: x["recommendation_score"], reverse=True)
        return scored[:3]

    # ================================================================
    # Explanation: generate a short one-liner (no Gemini needed)
    # ================================================================

    def generate_explanation(self, preferences: Dict[str, Any]) -> str:
        """
        Build a short, deterministic explanation string from the 3 answers.
        No API call needed — keeps it fast and simple.
        """
        if not preferences.get("has_data"):
            label = preferences.get("user_label", "traveler")
            return f"Recommended for {label} travelers based on our scoring."

        parts = []

        # Time
        t = preferences.get("preferred_time", "6-12")
        time_labels = {"0-6": "red-eye", "6-12": "morning", "12-18": "afternoon", "18-24": "evening"}
        t_label = time_labels.get(t, t)
        parts.append(f"{t_label} departures")

        # Dimensions
        dims = preferences.get("preferred_dimensions", [])
        dim_labels = {"price": "best value", "duration": "shortest flights", "comfort": "highest comfort"}
        dim_strs = [dim_labels.get(d, d) for d in dims]
        if dim_strs:
            parts.append(" & ".join(dim_strs))

        # Airline
        airline = preferences.get("preferred_airline")
        if airline:
            parts.append(airline)

        return "Picked for you: " + ", ".join(parts) + "."

    # ================================================================
    # Legacy compat: keep get_user_preferences for the /preferences endpoint
    # ================================================================

    def get_user_preferences(self, db: Session, user_id: int) -> Dict[str, Any]:
        """Get user preferences (legacy endpoint compat)."""
        answers = self.get_three_answers(db, user_id)
        user = db.query(UserDB).filter(UserDB.user_id == user_id).first()
        cached = user_preferences_service.get_user_preferences(db, user_id)

        return {
            "preferred_sort": cached.get("preferred_sort", "score"),
            "preferred_time_range": answers["preferred_time"],
            "preferred_airlines": cached.get("preferred_airlines", []),
            "preferred_dimensions": answers["preferred_dimensions"],
            "preferred_airline": answers["preferred_airline"],
            "price_sensitivity": cached.get("price_sensitivity", "medium"),
            "time_range_preferences": cached.get("time_range_counts", {}),
            "sort_preferences": cached.get("sort_counts", {}),
            "has_preferences": cached.get("has_preferences", False),
            "user_label": user.user_label if user else "business",
            "top_routes": [],
        }

    def update_sort_preference(self, db: Session, user_id: int, sort_by: str) -> bool:
        """Increment sort preference counter (legacy)."""
        user = db.query(UserDB).filter(UserDB.user_id == user_id).first()
        if not user:
            return False
        column_map = {
            "score": "sort_by_overall_count", "overall": "sort_by_overall_count",
            "price": "sort_by_price_count", "comfort": "sort_by_comfort_count",
            "duration": "sort_by_duration_count",
            "departure": "sort_by_departure_count", "arrival": "sort_by_arrival_count",
        }
        col = column_map.get(sort_by)
        if col:
            setattr(user, col, (getattr(user, col, 0) or 0) + 1)
            db.commit()
            return True
        return False

    # ================================================================
    # Helpers
    # ================================================================

    @staticmethod
    def _extract_hour(dep_time) -> int:
        if isinstance(dep_time, str):
            try:
                return datetime.fromisoformat(dep_time.replace("Z", "+00:00")).hour
            except Exception:
                return 12
        if hasattr(dep_time, "hour"):
            return dep_time.hour
        return 12


# Singleton
recommendation_service = RecommendationService()
