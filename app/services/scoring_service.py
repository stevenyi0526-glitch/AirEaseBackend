"""
AirEase Backend - Scoring Service
Calculates overall flight scores with traveler-type specific weights.

Traveler Types:
- Student: Price-sensitive, values direct flights and basic comfort
- Business: Time-sensitive, values reliability, service, and premium amenities
- Family: Comfort-focused, values service, amenities, and overall experience
"""

from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class TravelerType(str, Enum):
    """Traveler personas with different scoring priorities"""
    STUDENT = "student"
    BUSINESS = "business"
    FAMILY = "family"
    DEFAULT = "default"


@dataclass
class DimensionWeights:
    """Weights for each scoring dimension (must sum to 1.0)"""
    reliability: float
    comfort: float
    service: float
    value: float
    amenities: float  # WiFi, power, IFE, meals
    efficiency: float  # Direct flight bonus, duration


# Define weights for each traveler type
TRAVELER_WEIGHTS: Dict[TravelerType, DimensionWeights] = {
    # Students: Most price-sensitive, prefer direct flights to save time/hassle
    TravelerType.STUDENT: DimensionWeights(
        reliability=0.15,  # Less critical, can handle some delays
        comfort=0.15,      # Basic comfort is fine
        service=0.10,      # Service is lower priority
        value=0.35,        # Price is most important!
        amenities=0.10,    # Nice to have but not essential
        efficiency=0.15,   # Prefer direct flights
    ),
    
    # Business travelers: Time is money, need reliability and premium service
    TravelerType.BUSINESS: DimensionWeights(
        reliability=0.30,  # Cannot miss meetings!
        comfort=0.20,      # Need to arrive refreshed
        service=0.20,      # Premium service expected
        value=0.10,        # Price less important
        amenities=0.10,    # WiFi for work
        efficiency=0.10,   # Prefer shortest route
    ),
    
    # Families: Comfort and service matter most for kids
    TravelerType.FAMILY: DimensionWeights(
        reliability=0.20,  # Important with kids
        comfort=0.25,      # Kids need space
        service=0.25,      # Good service for families
        value=0.15,        # Budget conscious but not primary
        amenities=0.10,    # Entertainment for kids
        efficiency=0.05,   # Can handle longer flights
    ),
    
    # Default/General: Balanced weights
    TravelerType.DEFAULT: DimensionWeights(
        reliability=0.20,
        comfort=0.25,
        service=0.20,
        value=0.20,
        amenities=0.10,
        efficiency=0.05,
    ),
}


class ScoringService:
    """
    Service for calculating overall flight scores with traveler-type weighting.
    
    The scoring algorithm:
    1. Takes 4 base dimension scores (reliability, comfort, service, value)
    2. Calculates 2 derived dimensions (amenities, efficiency)
    3. Applies traveler-specific weights
    4. Applies score boosting to ensure competitive display
    """
    
    # Baseline score - minimum score for any dimension (ensures no ultra-low scores)
    BASELINE_SCORE = 6.5
    
    # Score boosting parameters
    # Target: Best flights should score 85-95, average flights 75-85
    SCORE_BOOST_FACTOR = 1.15  # Multiply final score by this
    SCORE_BOOST_OFFSET = 0.5   # Add this to final score
    
    @classmethod
    def calculate_amenities_score(
        cls,
        has_wifi: bool = False,
        has_power: bool = False,
        has_ife: bool = False,
        has_meal: bool = False,
        base_comfort_score: float = 7.0
    ) -> float:
        """
        Calculate amenities score based on available features.
        
        Args:
            has_wifi: WiFi available
            has_power: Power outlets available
            has_ife: In-flight entertainment available
            has_meal: Meal included
            base_comfort_score: Fallback if no amenities data
            
        Returns:
            Amenities score (0-10)
        """
        # Count available amenities
        amenity_scores = []
        
        if has_wifi:
            amenity_scores.append(2.5)
        if has_power:
            amenity_scores.append(2.5)
        if has_ife:
            amenity_scores.append(2.5)
        if has_meal:
            amenity_scores.append(2.5)
        
        if amenity_scores:
            # Sum amenities (max 10 if all present)
            score = sum(amenity_scores)
            # Ensure minimum baseline
            return max(score, cls.BASELINE_SCORE)
        else:
            # No amenity data - use comfort score as proxy
            return base_comfort_score
    
    @classmethod
    def calculate_efficiency_score(
        cls,
        stops: int = 0,
        duration_minutes: Optional[int] = None,
        typical_duration: Optional[int] = None
    ) -> float:
        """
        Calculate efficiency score based on routing.
        
        Args:
            stops: Number of stops
            duration_minutes: Actual flight duration
            typical_duration: Typical duration for this route
            
        Returns:
            Efficiency score (0-10)
        """
        # Base score from number of stops
        if stops == 0:
            base_score = 10.0  # Direct flight = maximum efficiency
        elif stops == 1:
            base_score = 7.5   # One stop is acceptable
        elif stops == 2:
            base_score = 5.0   # Two stops = less efficient
        else:
            base_score = 3.0   # Multiple stops = low efficiency
        
        # Adjust for duration if available
        if duration_minutes and typical_duration and typical_duration > 0:
            ratio = duration_minutes / typical_duration
            if ratio <= 1.0:
                # Faster than typical - bonus
                duration_bonus = min(1.0, (1.0 - ratio) * 5)
            else:
                # Slower than typical - penalty
                duration_bonus = max(-2.0, (1.0 - ratio) * 2)
            base_score = max(2.0, min(10.0, base_score + duration_bonus))
        
        return round(base_score, 1)
    
    @classmethod
    def apply_baseline_boost(cls, score: float) -> float:
        """
        Apply baseline boosting to ensure scores aren't too low.
        
        This transforms raw scores to be more display-friendly:
        - Raw 5.0 -> Displayed ~6.5
        - Raw 7.0 -> Displayed ~7.5
        - Raw 9.0 -> Displayed ~9.0
        
        The formula: max(baseline, score * boost_factor + offset)
        But capped at 10.0
        """
        boosted = score * cls.SCORE_BOOST_FACTOR + cls.SCORE_BOOST_OFFSET
        return min(10.0, max(cls.BASELINE_SCORE, boosted))
    
    @classmethod
    def calculate_overall_score(
        cls,
        reliability: float,
        comfort: float,
        service: float,
        value: float,
        traveler_type: str = "default",
        has_wifi: bool = False,
        has_power: bool = False,
        has_ife: bool = False,
        has_meal: bool = False,
        stops: int = 0,
        duration_minutes: Optional[int] = None,
        typical_duration: Optional[int] = None,
        apply_boost: bool = True
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate overall score with traveler-specific weighting.
        
        Args:
            reliability: Reliability score (0-10)
            comfort: Comfort score (0-10)
            service: Service score (0-10)
            value: Value score (0-10)
            traveler_type: "student", "business", "family", or "default"
            has_wifi, has_power, has_ife, has_meal: Amenity flags
            stops: Number of stops
            duration_minutes: Flight duration
            typical_duration: Typical duration for route
            apply_boost: Whether to apply score boosting
            
        Returns:
            Tuple of (overall_score, details_dict)
        """
        # Get weights for traveler type
        try:
            tt = TravelerType(traveler_type.lower())
        except ValueError:
            tt = TravelerType.DEFAULT
        
        weights = TRAVELER_WEIGHTS[tt]
        
        # Calculate derived dimensions
        amenities = cls.calculate_amenities_score(
            has_wifi, has_power, has_ife, has_meal, comfort
        )
        efficiency = cls.calculate_efficiency_score(
            stops, duration_minutes, typical_duration
        )
        
        # Apply baseline boost to each dimension (prevents ultra-low scores)
        if apply_boost:
            reliability_adj = cls.apply_baseline_boost(reliability)
            comfort_adj = cls.apply_baseline_boost(comfort)
            service_adj = cls.apply_baseline_boost(service)
            value_adj = cls.apply_baseline_boost(value)
            amenities_adj = cls.apply_baseline_boost(amenities)
            efficiency_adj = cls.apply_baseline_boost(efficiency)
        else:
            reliability_adj = reliability
            comfort_adj = comfort
            service_adj = service
            value_adj = value
            amenities_adj = amenities
            efficiency_adj = efficiency
        
        # Calculate weighted overall score
        overall = (
            reliability_adj * weights.reliability +
            comfort_adj * weights.comfort +
            service_adj * weights.service +
            value_adj * weights.value +
            amenities_adj * weights.amenities +
            efficiency_adj * weights.efficiency
        )
        
        # Round to 1 decimal
        overall = round(overall, 1)
        
        # Build details
        details = {
            "traveler_type": tt.value,
            "weights": {
                "reliability": weights.reliability,
                "comfort": weights.comfort,
                "service": weights.service,
                "value": weights.value,
                "amenities": weights.amenities,
                "efficiency": weights.efficiency,
            },
            "raw_scores": {
                "reliability": round(reliability, 1),
                "comfort": round(comfort, 1),
                "service": round(service, 1),
                "value": round(value, 1),
                "amenities": round(amenities, 1),
                "efficiency": round(efficiency, 1),
            },
            "adjusted_scores": {
                "reliability": round(reliability_adj, 1),
                "comfort": round(comfort_adj, 1),
                "service": round(service_adj, 1),
                "value": round(value_adj, 1),
                "amenities": round(amenities_adj, 1),
                "efficiency": round(efficiency_adj, 1),
            },
            "overall_score": overall,
        }
        
        return overall, details
    
    @classmethod
    def get_persona_label(cls, traveler_type: str) -> str:
        """Get display label for traveler type."""
        labels = {
            "student": "Budget Traveler",
            "business": "Business Priority",
            "family": "Family Comfort",
            "default": "Balanced",
        }
        return labels.get(traveler_type.lower(), "Balanced")


# Convenience functions
def calculate_overall_score(
    reliability: float,
    comfort: float,
    service: float,
    value: float,
    traveler_type: str = "default",
    **kwargs
) -> Tuple[float, Dict[str, Any]]:
    """Convenience function to calculate overall score."""
    return ScoringService.calculate_overall_score(
        reliability=reliability,
        comfort=comfort,
        service=service,
        value=value,
        traveler_type=traveler_type,
        **kwargs
    )


def get_traveler_weights(traveler_type: str) -> DimensionWeights:
    """Get weights for a traveler type."""
    try:
        tt = TravelerType(traveler_type.lower())
    except ValueError:
        tt = TravelerType.DEFAULT
    return TRAVELER_WEIGHTS[tt]
