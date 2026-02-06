"""
AirEase Backend - User Preferences Service
Tracks user behavior and aggregates preferences for AI recommendations.

Uses Pandas for efficient data aggregation and preprocessing.
"""

import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import pandas as pd

from app.database import (
    UserDB, 
    UserSortActionDB, 
    UserTimeFilterActionDB, 
    FlightSelectionDB,
    UserPreferencesCacheDB
)


class UserPreferencesService:
    """
    Service for tracking and aggregating user preferences.
    
    Tracks:
    1. Sort actions (which dimension user sorts by)
    2. Time filter actions (which time ranges user prefers)
    3. Flight selections (which airlines user selects)
    
    Aggregates data using Pandas and caches in user_preferences_cache table.
    """
    
    # Time range mappings
    TIME_RANGES = {
        "morning": "6-12",
        "afternoon": "12-18",
        "evening": "18-24",
        "night": "0-6",
    }
    
    # Price sensitivity thresholds
    PRICE_SENSITIVITY_HIGH_THRESHOLD = 0.5  # >50% of sorts are by price
    PRICE_SENSITIVITY_MEDIUM_THRESHOLD = 0.25  # >25% of sorts are by price
    
    def __init__(self):
        pass
    
    # ============================================================
    # Tracking Methods (POST data to DB)
    # ============================================================
    
    def track_sort_action(self, db: Session, user_id: int, sort_dimension: str) -> bool:
        """
        Track when a user clicks a sort option.
        
        Args:
            user_id: User's ID
            sort_dimension: The sort option clicked (price, duration, score, departure, arrival)
        
        Returns:
            True if successfully tracked
        """
        try:
            # Normalize sort dimension
            sort_dimension = sort_dimension.lower().strip()
            if sort_dimension == "overall":
                sort_dimension = "score"
            
            # Create tracking record
            action = UserSortActionDB(
                user_id=user_id,
                sort_dimension=sort_dimension
            )
            db.add(action)
            db.commit()
            
            # Trigger cache update (async in production, sync here for simplicity)
            self._update_preferences_cache(db, user_id)
            
            return True
        except Exception as e:
            print(f"Error tracking sort action: {e}")
            db.rollback()
            return False
    
    def track_time_filter(self, db: Session, user_id: int, time_range: str) -> bool:
        """
        Track when a user applies a time filter.
        
        Args:
            user_id: User's ID
            time_range: The time range selected (e.g., "6-12", "morning")
        
        Returns:
            True if successfully tracked
        """
        try:
            # Normalize time range
            time_range = self._normalize_time_range(time_range)
            
            if not time_range:
                return False
            
            # Create tracking record
            action = UserTimeFilterActionDB(
                user_id=user_id,
                time_range=time_range
            )
            db.add(action)
            db.commit()
            
            # Trigger cache update
            self._update_preferences_cache(db, user_id)
            
            return True
        except Exception as e:
            print(f"Error tracking time filter: {e}")
            db.rollback()
            return False
    
    def track_flight_selection(
        self, 
        db: Session, 
        user_id: int, 
        flight_data: Dict[str, Any]
    ) -> bool:
        """
        Track when a user selects/clicks on a flight.
        Extracts airline and departure time for preference learning.
        
        Args:
            user_id: User's ID
            flight_data: Flight information dict
        
        Returns:
            True if successfully tracked
        """
        try:
            # Extract flight info
            departure_time = flight_data.get("departure_time") or flight_data.get("departureTime")
            if isinstance(departure_time, str):
                try:
                    departure_time = datetime.fromisoformat(departure_time.replace("Z", "+00:00"))
                except:
                    departure_time = datetime.now()
            
            # Extract airline code
            airline = flight_data.get("airline", "Unknown")
            airline_code = flight_data.get("airline_code") or flight_data.get("airlineCode")
            if not airline_code:
                # Try to extract from flight number
                flight_number = flight_data.get("flight_number") or flight_data.get("flightNumber", "")
                airline_code = ''.join(c for c in flight_number[:3] if c.isalpha()).upper()
            
            # Create selection record
            selection = FlightSelectionDB(
                user_id=user_id,
                flight_id=flight_data.get("flight_id") or flight_data.get("id", f"unknown-{datetime.now().timestamp()}"),
                departure_city=flight_data.get("departure_city") or flight_data.get("departureCityCode", ""),
                arrival_city=flight_data.get("arrival_city") or flight_data.get("arrivalCityCode", ""),
                departure_time=departure_time,
                airline=airline,
                price=int(flight_data.get("price", 0)),
                overall_score=int(flight_data.get("overall_score") or flight_data.get("overallScore", 0)),
                cabin_class=flight_data.get("cabin_class") or flight_data.get("cabin", "economy"),
            )
            
            # Add airline_code if column exists
            if hasattr(selection, 'airline_code'):
                selection.airline_code = airline_code
            
            db.add(selection)
            db.commit()
            
            # Also track the time range from the selection
            if departure_time:
                hour = departure_time.hour
                time_range = self._hour_to_time_range(hour)
                self.track_time_filter(db, user_id, time_range)
            
            # Trigger cache update
            self._update_preferences_cache(db, user_id)
            
            return True
        except Exception as e:
            print(f"Error tracking flight selection: {e}")
            db.rollback()
            return False
    
    # ============================================================
    # Aggregation Methods (Using Pandas)
    # ============================================================
    
    def _update_preferences_cache(self, db: Session, user_id: int) -> None:
        """
        Aggregate user actions using Pandas and update the cache table.
        
        This is the core aggregation logic that:
        1. Loads all tracking data for the user
        2. Uses Pandas to compute aggregates
        3. Determines preferences and sensitivity levels
        4. Updates the cache table
        """
        try:
            # 1. Aggregate sort actions
            sort_counts, preferred_sort, total_sorts = self._aggregate_sort_actions(db, user_id)
            
            # 2. Aggregate time filter actions
            time_range_counts, preferred_time_range = self._aggregate_time_filters(db, user_id)
            
            # 3. Aggregate airline selections
            airline_counts, preferred_airlines, total_selections = self._aggregate_airline_selections(db, user_id)
            
            # 4. Calculate price sensitivity
            price_sensitivity = self._calculate_price_sensitivity(sort_counts, total_sorts)
            
            # 5. Update or create cache record
            cache = db.query(UserPreferencesCacheDB).filter(
                UserPreferencesCacheDB.user_id == user_id
            ).first()
            
            if not cache:
                cache = UserPreferencesCacheDB(user_id=user_id)
                db.add(cache)
            
            # Update cache fields
            cache.sort_counts = json.dumps(sort_counts)
            cache.time_range_counts = json.dumps(time_range_counts)
            cache.airline_counts = json.dumps(airline_counts)
            cache.preferred_sort_dimension = preferred_sort
            cache.time_range_preferences = json.dumps(time_range_counts)
            cache.preferred_airlines = json.dumps(preferred_airlines[:5])  # Top 5 airlines
            cache.price_sensitivity = price_sensitivity
            cache.total_sort_actions = total_sorts
            cache.total_selections = total_selections
            cache.updated_at = datetime.utcnow()
            
            db.commit()
            
        except Exception as e:
            print(f"Error updating preferences cache: {e}")
            db.rollback()
    
    def _aggregate_sort_actions(self, db: Session, user_id: int) -> tuple:
        """
        Aggregate sort actions using Pandas.
        
        Returns:
            (sort_counts_dict, preferred_sort, total_count)
        """
        # Query all sort actions for user
        actions = db.query(
            UserSortActionDB.sort_dimension,
            func.count(UserSortActionDB.id).label("count")
        ).filter(
            UserSortActionDB.user_id == user_id
        ).group_by(
            UserSortActionDB.sort_dimension
        ).all()
        
        if not actions:
            return {}, "score", 0
        
        # Convert to DataFrame for processing
        df = pd.DataFrame(actions, columns=["sort_dimension", "count"])
        
        # Calculate totals
        total_count = int(df["count"].sum())
        
        # Get counts as dict
        sort_counts = df.set_index("sort_dimension")["count"].to_dict()
        sort_counts = {k: int(v) for k, v in sort_counts.items()}
        
        # Find preferred sort (most frequent)
        preferred_sort = df.loc[df["count"].idxmax(), "sort_dimension"]
        
        return sort_counts, preferred_sort, total_count
    
    def _aggregate_time_filters(self, db: Session, user_id: int) -> tuple:
        """
        Aggregate time filter actions using Pandas.
        
        Returns:
            (time_range_counts_dict, preferred_time_range)
        """
        # Query all time filter actions for user
        actions = db.query(
            UserTimeFilterActionDB.time_range,
            func.count(UserTimeFilterActionDB.id).label("count")
        ).filter(
            UserTimeFilterActionDB.user_id == user_id
        ).group_by(
            UserTimeFilterActionDB.time_range
        ).all()
        
        if not actions:
            return {}, "6-12"
        
        # Convert to DataFrame
        df = pd.DataFrame(actions, columns=["time_range", "count"])
        
        # Get counts as dict
        time_range_counts = df.set_index("time_range")["count"].to_dict()
        time_range_counts = {k: int(v) for k, v in time_range_counts.items()}
        
        # Find preferred time range (most frequent)
        preferred_time_range = df.loc[df["count"].idxmax(), "time_range"]
        
        return time_range_counts, preferred_time_range
    
    def _aggregate_airline_selections(self, db: Session, user_id: int) -> tuple:
        """
        Aggregate airline selections from flight_selections using Pandas.
        
        Returns:
            (airline_counts_dict, preferred_airlines_list, total_selections)
        """
        # Query airline counts from flight selections
        selections = db.query(
            FlightSelectionDB.airline,
            func.count(FlightSelectionDB.id).label("count")
        ).filter(
            FlightSelectionDB.user_id == user_id
        ).group_by(
            FlightSelectionDB.airline
        ).all()
        
        if not selections:
            return {}, [], 0
        
        # Convert to DataFrame
        df = pd.DataFrame(selections, columns=["airline", "count"])
        
        # Calculate total
        total_selections = int(df["count"].sum())
        
        # Get counts as dict
        airline_counts = df.set_index("airline")["count"].to_dict()
        airline_counts = {k: int(v) for k, v in airline_counts.items()}
        
        # Get preferred airlines (sorted by count, descending)
        df_sorted = df.sort_values("count", ascending=False)
        preferred_airlines = df_sorted["airline"].tolist()
        
        return airline_counts, preferred_airlines, total_selections
    
    def _calculate_price_sensitivity(self, sort_counts: Dict[str, int], total_sorts: int) -> str:
        """
        Calculate price sensitivity based on sort actions.
        
        Returns:
            "high" if >50% sorts by price
            "medium" if >25% sorts by price
            "low" otherwise
        """
        if total_sorts == 0:
            return "medium"  # Default
        
        price_count = sort_counts.get("price", 0)
        price_ratio = price_count / total_sorts
        
        if price_ratio >= self.PRICE_SENSITIVITY_HIGH_THRESHOLD:
            return "high"
        elif price_ratio >= self.PRICE_SENSITIVITY_MEDIUM_THRESHOLD:
            return "medium"
        else:
            return "low"
    
    # ============================================================
    # Retrieval Methods (GET data from DB)
    # ============================================================
    
    def get_user_preferences(self, db: Session, user_id: int) -> Dict[str, Any]:
        """
        Get cached user preferences for recommendation engine.
        
        Returns preprocessed data ready for the recommendation agent.
        """
        cache = db.query(UserPreferencesCacheDB).filter(
            UserPreferencesCacheDB.user_id == user_id
        ).first()
        
        if not cache:
            return self._get_default_preferences()
        
        return {
            "preferred_sort": cache.preferred_sort_dimension or "score",
            "preferred_time_range": self._get_preferred_time_range_from_cache(cache),
            "preferred_airlines": self._safe_json_load(cache.preferred_airlines, []),
            "price_sensitivity": cache.price_sensitivity or "medium",
            "sort_counts": self._safe_json_load(cache.sort_counts, {}),
            "time_range_counts": self._safe_json_load(cache.time_range_counts, {}),
            "airline_counts": self._safe_json_load(cache.airline_counts, {}),
            "total_sort_actions": cache.total_sort_actions or 0,
            "total_selections": cache.total_selections or 0,
            "has_preferences": (cache.total_sort_actions or 0) + (cache.total_selections or 0) > 0,
        }
    
    def get_preferences_for_recommendation(self, db: Session, user_id: int) -> Dict[str, Any]:
        """
        Get ONLY the fields needed by the recommendation agent.
        Preprocessed and filtered for minimal data transfer.
        
        This is the primary method called by the recommendation system.
        """
        prefs = self.get_user_preferences(db, user_id)
        
        # Return only what's needed for recommendations
        return {
            "preferred_sort": prefs["preferred_sort"],
            "preferred_time_range": prefs["preferred_time_range"],
            "preferred_airlines": prefs["preferred_airlines"][:3],  # Top 3 only
            "price_sensitivity": prefs["price_sensitivity"],
            "has_preferences": prefs["has_preferences"],
        }
    
    # ============================================================
    # Helper Methods
    # ============================================================
    
    def _normalize_time_range(self, time_range: str) -> Optional[str]:
        """Normalize time range to standard format (e.g., '6-12')"""
        if not time_range:
            return None
        
        time_range = time_range.lower().strip()
        
        # Check if it's a named range
        if time_range in self.TIME_RANGES:
            return self.TIME_RANGES[time_range]
        
        # Check if it's already in correct format
        if "-" in time_range:
            parts = time_range.split("-")
            if len(parts) == 2:
                try:
                    start = int(parts[0])
                    end = int(parts[1])
                    if 0 <= start <= 24 and 0 <= end <= 24:
                        return f"{start}-{end}"
                except ValueError:
                    pass
        
        return None
    
    def _hour_to_time_range(self, hour: int) -> str:
        """Convert an hour (0-23) to a time range string."""
        if 0 <= hour < 6:
            return "0-6"
        elif 6 <= hour < 12:
            return "6-12"
        elif 12 <= hour < 18:
            return "12-18"
        else:
            return "18-24"
    
    def _get_preferred_time_range_from_cache(self, cache: UserPreferencesCacheDB) -> str:
        """Get preferred time range from cache data."""
        time_counts = self._safe_json_load(cache.time_range_counts, {})
        if not time_counts:
            return "6-12"  # Default morning
        
        # Find range with highest count
        return max(time_counts.items(), key=lambda x: x[1])[0]
    
    def _safe_json_load(self, value: Optional[str], default: Any) -> Any:
        """
        Safely load JSON string or return native Python object.
        
        PostgreSQL may return native Python types (list, dict) directly
        when using JSONB columns, so we need to handle both cases:
        1. Already a native Python object (list, dict) -> return as-is
        2. JSON string -> parse and return
        3. None or error -> return default
        """
        if value is None:
            return default
        
        # If already a Python list or dict, return as-is
        if isinstance(value, (list, dict)):
            return value
        
        # If it's a string, try to parse as JSON
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return default
        
        return default
    
    def _get_default_preferences(self) -> Dict[str, Any]:
        """Return default preferences for users with no history."""
        return {
            "preferred_sort": "score",
            "preferred_time_range": "6-12",
            "preferred_airlines": [],
            "price_sensitivity": "medium",
            "sort_counts": {},
            "time_range_counts": {},
            "airline_counts": {},
            "total_sort_actions": 0,
            "total_selections": 0,
            "has_preferences": False,
        }


# Singleton instance
user_preferences_service = UserPreferencesService()
