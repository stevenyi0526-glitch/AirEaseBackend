"""
AirEase Backend - Airline Reviews Service
航空公司评价数据服务

Fetches and aggregates user reviews from the airline_reviews table
to provide service-related dimension ratings.
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from sqlalchemy import text
from app.database import SessionLocal


@dataclass
class AirlineServiceRatings:
    """Aggregated service ratings for an airline + cabin class combination"""
    airline_name: str
    cabin_type: str
    food_rating: float
    ground_service_rating: float
    seat_comfort_rating: float
    service_rating: float
    review_count: int
    recommendation_rate: float  # Percentage of "yes" recommendations


@dataclass
class UserReview:
    """Individual user review"""
    airline_name: str
    cabin_type: str
    title: str
    review: str
    food_rating: int
    ground_service_rating: int
    seat_comfort_rating: int
    service_rating: int
    recommended: bool
    travel_type: str
    route: str
    aircraft: Optional[str]


class AirlineReviewsService:
    """
    Service for retrieving airline reviews and calculating service scores.
    
    Ratings from database are on 1-5 scale, we convert to 0-10 scale.
    """
    
    # Cache for aggregated ratings
    _ratings_cache: Dict[str, AirlineServiceRatings] = {}
    _cache_loaded: bool = False
    
    # Baseline score (70% = 7.0 on 0-10 scale)
    BASELINE_SCORE = 7.0
    
    # Scale conversion: DB uses 1-5, we need 0-10
    @staticmethod
    def scale_rating(rating_1_to_5: float) -> float:
        """Convert 1-5 rating to 0-10 scale"""
        if rating_1_to_5 is None or rating_1_to_5 == 0:
            return 0
        # 1 -> 2, 2 -> 4, 3 -> 6, 4 -> 8, 5 -> 10
        return rating_1_to_5 * 2
    
    @classmethod
    def _load_cache(cls):
        """Load aggregated ratings from database into cache."""
        if cls._cache_loaded:
            return
        
        try:
            db = SessionLocal()
            
            # Aggregate ratings by airline and cabin type
            result = db.execute(text("""
                SELECT 
                    "AirlineName",
                    "CabinType",
                    AVG(NULLIF("FoodRating", 0)) as avg_food,
                    AVG(NULLIF("GroundServiceRating", 0)) as avg_ground,
                    AVG(NULLIF("SeatComfortRating", 0)) as avg_seat,
                    AVG(NULLIF("ServiceRating", 0)) as avg_service,
                    COUNT(*) as review_count,
                    SUM(CASE WHEN "Recommended" = 'yes' THEN 1 ELSE 0 END)::float / COUNT(*) * 100 as rec_rate
                FROM airline_reviews
                WHERE "AirlineName" IS NOT NULL
                GROUP BY "AirlineName", "CabinType"
                HAVING COUNT(*) >= 1
            """))
            
            for row in result:
                airline = row[0]
                cabin = row[1] or "Economy Class"
                
                # Normalize cabin type
                cabin_normalized = cls._normalize_cabin_type(cabin)
                
                key = f"{airline.lower()}|{cabin_normalized}"
                
                cls._ratings_cache[key] = AirlineServiceRatings(
                    airline_name=airline,
                    cabin_type=cabin_normalized,
                    food_rating=cls.scale_rating(float(row[2])) if row[2] else 0,
                    ground_service_rating=cls.scale_rating(float(row[3])) if row[3] else 0,
                    seat_comfort_rating=cls.scale_rating(float(row[4])) if row[4] else 0,
                    service_rating=cls.scale_rating(float(row[5])) if row[5] else 0,
                    review_count=int(row[6]),
                    recommendation_rate=float(row[7]) if row[7] else 0
                )
            
            db.close()
            cls._cache_loaded = True
            print(f"✅ Airline reviews cache loaded: {len(cls._ratings_cache)} entries")
            
        except Exception as e:
            print(f"⚠️ Failed to load airline reviews data: {e}")
            cls._cache_loaded = True
    
    @staticmethod
    def _normalize_cabin_type(cabin: str) -> str:
        """Normalize cabin type to 'economy' or 'business'"""
        if not cabin:
            return "economy"
        cabin_lower = cabin.lower()
        if "business" in cabin_lower or "first" in cabin_lower or "premium" in cabin_lower:
            return "business"
        return "economy"
    
    @staticmethod
    def _normalize_airline_name(airline: str) -> str:
        """Normalize airline name for matching"""
        if not airline:
            return ""
        
        # Common mappings
        mappings = {
            "中国国航": "Air China",
            "国航": "Air China",
            "东方航空": "China Eastern",
            "东航": "China Eastern",
            "南方航空": "China Southern",
            "南航": "China Southern",
            "海南航空": "Hainan Airlines",
            "海航": "Hainan Airlines",
            "四川航空": "Sichuan Airlines",
            "川航": "Sichuan Airlines",
            "深圳航空": "Shenzhen Airlines",
            "深航": "Shenzhen Airlines",
            "厦门航空": "Xiamen Airlines",
            "厦航": "Xiamen Airlines",
            "上海航空": "Shanghai Airlines",
        }
        
        # Check direct mapping
        if airline in mappings:
            return mappings[airline].lower()
        
        return airline.lower()
    
    @classmethod
    def get_ratings(
        cls,
        airline_name: str,
        cabin_class: str = "economy"
    ) -> Optional[AirlineServiceRatings]:
        """
        Get aggregated ratings for an airline + cabin class.
        
        Args:
            airline_name: Airline name (Chinese or English)
            cabin_class: "economy" or "business"
            
        Returns:
            AirlineServiceRatings if found, None otherwise
        """
        cls._load_cache()
        
        normalized_airline = cls._normalize_airline_name(airline_name)
        normalized_cabin = cls._normalize_cabin_type(cabin_class)
        
        # Try exact match
        key = f"{normalized_airline}|{normalized_cabin}"
        if key in cls._ratings_cache:
            return cls._ratings_cache[key]
        
        # Try partial match on airline name
        for cache_key, ratings in cls._ratings_cache.items():
            cache_airline, cache_cabin = cache_key.split("|")
            if cache_cabin == normalized_cabin:
                if normalized_airline in cache_airline or cache_airline in normalized_airline:
                    return ratings
        
        return None
    
    @classmethod
    def get_user_reviews(
        cls,
        airline_name: str,
        cabin_class: str = "economy",
        limit: int = 10
    ) -> List[UserReview]:
        """
        Get individual user reviews for an airline.
        
        NOTE: This performs a DB query and should only be called on-demand
        when user selects a specific flight (not during initial parsing).
        
        Args:
            airline_name: Airline name
            cabin_class: "economy" or "business"
            limit: Maximum number of reviews to return
            
        Returns:
            List of UserReview objects
        """
        try:
            db = SessionLocal()
            
            normalized_cabin = cls._normalize_cabin_type(cabin_class)
            cabin_filter = "Business" if normalized_cabin == "business" else "Economy"
            
            result = db.execute(text("""
                SELECT 
                    "AirlineName",
                    "CabinType",
                    "Title",
                    "Review",
                    "FoodRating",
                    "GroundServiceRating",
                    "SeatComfortRating",
                    "ServiceRating",
                    "Recommended",
                    "TravelType",
                    "Route",
                    "Aircraft"
                FROM airline_reviews
                WHERE "AirlineName" ILIKE :airline_pattern
                  AND "CabinType" ILIKE :cabin_pattern
                ORDER BY 
                    CASE WHEN "Recommended" = 'yes' THEN 0 ELSE 1 END,
                    ("FoodRating" + "GroundServiceRating" + "SeatComfortRating" + "ServiceRating") DESC
                LIMIT :limit
            """), {
                "airline_pattern": f"%{airline_name}%",
                "cabin_pattern": f"%{cabin_filter}%",
                "limit": limit
            })
            
            reviews = []
            for row in result:
                reviews.append(UserReview(
                    airline_name=row[0],
                    cabin_type=row[1],
                    title=row[2] or "",
                    review=row[3] or "",
                    food_rating=row[4] or 0,
                    ground_service_rating=row[5] or 0,
                    seat_comfort_rating=row[6] or 0,
                    service_rating=row[7] or 0,
                    recommended=row[8] == "yes",
                    travel_type=row[9] or "",
                    route=row[10] or "",
                    aircraft=row[11]
                ))
            
            db.close()
            return reviews
            
        except Exception as e:
            print(f"⚠️ Failed to fetch user reviews: {e}")
            return []
    
    @classmethod
    def calculate_service_score(
        cls,
        airline_name: str,
        cabin_class: str = "economy"
    ) -> tuple[float, Dict[str, Any]]:
        """
        Calculate service score (0-10) for an airline.
        
        Returns:
            Tuple of (score, details_dict)
        """
        ratings = cls.get_ratings(airline_name, cabin_class)
        
        details = {
            "airline_name": airline_name,
            "cabin_class": cabin_class,
            "data_source": "database" if ratings else "default",
            "food_rating": None,
            "ground_service_rating": None,
            "seat_comfort_rating": None,
            "service_rating": None,
            "review_count": 0,
            "recommendation_rate": 0,
            "highlights": [],
        }
        
        if ratings:
            details["food_rating"] = round(ratings.food_rating, 1)
            details["ground_service_rating"] = round(ratings.ground_service_rating, 1)
            details["seat_comfort_rating"] = round(ratings.seat_comfort_rating, 1)
            details["service_rating"] = round(ratings.service_rating, 1)
            details["review_count"] = ratings.review_count
            details["recommendation_rate"] = round(ratings.recommendation_rate, 1)
            
            # Calculate weighted service score
            # Food: 25%, Ground Service: 20%, Seat Comfort: 25%, In-flight Service: 30%
            valid_ratings = []
            weights = []
            
            if ratings.food_rating > 0:
                valid_ratings.append(ratings.food_rating)
                weights.append(0.25)
            if ratings.ground_service_rating > 0:
                valid_ratings.append(ratings.ground_service_rating)
                weights.append(0.20)
            if ratings.seat_comfort_rating > 0:
                valid_ratings.append(ratings.seat_comfort_rating)
                weights.append(0.25)
            if ratings.service_rating > 0:
                valid_ratings.append(ratings.service_rating)
                weights.append(0.30)
            
            if valid_ratings:
                # Normalize weights
                total_weight = sum(weights)
                normalized_weights = [w / total_weight for w in weights]
                score = sum(r * w for r, w in zip(valid_ratings, normalized_weights))
            else:
                score = cls.BASELINE_SCORE
            
            # Apply baseline (minimum 7.0)
            score = max(score, cls.BASELINE_SCORE)
            
            # Generate highlights (ratings >= 7.0)
            highlights = []
            rating_names = {
                "food_rating": ("Food & Beverage", ratings.food_rating),
                "ground_service_rating": ("Ground Service", ratings.ground_service_rating),
                "seat_comfort_rating": ("Seat Comfort", ratings.seat_comfort_rating),
                "service_rating": ("In-flight Service", ratings.service_rating),
            }
            
            # Find all ratings >= 7.0 (70%)
            good_ratings = [(name, val) for key, (name, val) in rating_names.items() if val >= 7.0]
            
            if good_ratings:
                # Sort by rating descending
                good_ratings.sort(key=lambda x: x[1], reverse=True)
                for name, val in good_ratings:
                    highlights.append(f"{name}: {val:.1f}/10")
            else:
                # All below 7.0, show the highest one
                all_ratings = [(name, val) for key, (name, val) in rating_names.items() if val > 0]
                if all_ratings:
                    all_ratings.sort(key=lambda x: x[1], reverse=True)
                    best_name, best_val = all_ratings[0]
                    highlights.append(f"Good {best_name.lower()}")
            
            details["highlights"] = highlights
            details["final_score"] = round(score, 1)
            
            return round(score, 1), details
        
        # No data found - return baseline
        details["final_score"] = cls.BASELINE_SCORE
        return cls.BASELINE_SCORE, details
    
    @classmethod
    def get_service_explanations(
        cls,
        airline_name: str,
        cabin_class: str = "economy",
        service_score: float = 7.0
    ) -> List[Dict[str, Any]]:
        """
        Generate service-related explanations for the score breakdown.
        
        Returns list of explanation dicts.
        """
        explanations = []
        ratings = cls.get_ratings(airline_name, cabin_class)
        
        if ratings:
            # Food rating explanation
            if ratings.food_rating > 0:
                is_positive = ratings.food_rating >= 7.0
                explanations.append({
                    "title": "Food & Beverage",
                    "detail": f"Rated {ratings.food_rating:.1f}/10 by {ratings.review_count} travelers",
                    "is_positive": is_positive
                })
            
            # Ground service explanation
            if ratings.ground_service_rating > 0:
                is_positive = ratings.ground_service_rating >= 7.0
                explanations.append({
                    "title": "Ground Service",
                    "detail": f"Check-in and boarding rated {ratings.ground_service_rating:.1f}/10",
                    "is_positive": is_positive
                })
            
            # In-flight service explanation
            if ratings.service_rating > 0:
                is_positive = ratings.service_rating >= 7.0
                explanations.append({
                    "title": "Cabin Crew Service",
                    "detail": f"In-flight service rated {ratings.service_rating:.1f}/10",
                    "is_positive": is_positive
                })
            
            # Recommendation rate
            if ratings.recommendation_rate > 0:
                is_positive = ratings.recommendation_rate >= 70
                explanations.append({
                    "title": "Traveler Recommendations",
                    "detail": f"{ratings.recommendation_rate:.0f}% of travelers recommend this airline",
                    "is_positive": is_positive
                })
        else:
            # No data
            explanations.append({
                "title": "Service Quality",
                "detail": "Standard airline service",
                "is_positive": service_score >= 7.0
            })
        
        return explanations


# Module-level convenience functions
def get_service_score(airline_name: str, cabin_class: str = "economy") -> float:
    """Get service score for an airline."""
    score, _ = AirlineReviewsService.calculate_service_score(airline_name, cabin_class)
    return score


def get_user_reviews(airline_name: str, cabin_class: str = "economy", limit: int = 10) -> List[UserReview]:
    """Get user reviews for an airline."""
    return AirlineReviewsService.get_user_reviews(airline_name, cabin_class, limit)
