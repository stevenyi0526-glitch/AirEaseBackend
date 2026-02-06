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
    4. NO artificial boosting - scores reflect true quality
    """
    
    # Baseline score - minimum score for "soft" dimensions (comfort, service, amenities)
    # Hard dimensions (reliability, efficiency, value) use actual scores
    SOFT_BASELINE_SCORE = 5.0
    
    # Score boosting parameters - REDUCED to be more honest
    # Target: Best flights 85-95, average 65-80, poor 50-65
    SCORE_BOOST_FACTOR = 1.05  # Slight boost only
    SCORE_BOOST_OFFSET = 0.0   # No offset - use actual scores
    
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
            # Return actual score - no artificial floor
            return score
        else:
            # No amenity data - use comfort score as proxy
            return base_comfort_score
    
    @classmethod
    def calculate_efficiency_score(
        cls,
        stops: int = 0,
        duration_minutes: Optional[int] = None,
        shortest_duration: Optional[int] = None
    ) -> float:
        """
        Calculate efficiency score based on duration and stops.
        
        NEW ALGORITHM:
        1. Duration is the PRIMARY factor - shorter = better
        2. If shortest_duration is provided, score is relative to that baseline
        3. Stops act as a MULTIPLIER (0 stop = 1.0, 1 stop = 0.8, 2+ stops = 0.6)
        4. Final efficiency = duration_score * stop_multiplier
        
        Args:
            stops: Number of stops
            duration_minutes: Actual flight duration in minutes
            shortest_duration: Shortest flight duration for this route (baseline = 10)
            
        Returns:
            Efficiency score (0-10)
        """
        # Step 1: Calculate duration score (primary factor)
        if duration_minutes and shortest_duration and shortest_duration > 0:
            # Duration score: shortest flight = 10, deduct based on difference
            # Every 30 minutes over shortest = -1 point
            extra_minutes = duration_minutes - shortest_duration
            if extra_minutes <= 0:
                duration_score = 10.0
            else:
                # Penalty: -1 point per 30 minutes over shortest
                penalty = extra_minutes / 30.0
                duration_score = max(1.0, 10.0 - penalty)
        elif duration_minutes:
            # No baseline provided - use absolute scale
            hours = duration_minutes / 60.0
            if hours <= 2:
                duration_score = 10.0
            elif hours <= 4:
                duration_score = 9.0
            elif hours <= 6:
                duration_score = 8.0
            elif hours <= 10:
                duration_score = 6.0
            elif hours <= 15:
                duration_score = 4.0
            elif hours <= 24:
                duration_score = 2.5
            else:
                duration_score = 1.5  # Very long flights (>24h)
        else:
            # No duration data - neutral score
            duration_score = 7.0
        
        # Step 2: Apply stop multiplier (secondary factor)
        # Direct flights preserve the duration score
        # Stops reduce it because they add hassle
        if stops == 0:
            stop_multiplier = 1.0  # Direct flight - full score
        elif stops == 1:
            stop_multiplier = 0.8  # 1 stop - 20% reduction
        else:
            stop_multiplier = 0.6  # 2+ stops - 40% reduction
        
        # Step 3: Calculate final efficiency
        efficiency = duration_score * stop_multiplier
        
        return round(max(1.0, min(10.0, efficiency)), 1)
    
    @classmethod
    def apply_soft_baseline(cls, score: float) -> float:
        """
        Apply soft baseline for comfort/service/amenities dimensions.
        These are harder to measure accurately, so we apply a minimum floor.
        
        Args:
            score: Raw score (0-10)
            
        Returns:
            Score with soft minimum applied
        """
        # Only apply minimal boosting for soft dimensions
        boosted = score * cls.SCORE_BOOST_FACTOR
        return min(10.0, max(cls.SOFT_BASELINE_SCORE, boosted))
    
    @classmethod
    def apply_hard_score(cls, score: float) -> float:
        """
        Apply hard scoring for reliability/efficiency/value dimensions.
        These have objective data, so we use actual scores with no floor.
        
        Args:
            score: Raw score (0-10)
            
        Returns:
            Score capped at 10, minimum 1
        """
        return min(10.0, max(1.0, score))
    
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
        shortest_duration: Optional[int] = None,
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
            shortest_duration: Shortest flight duration for this route (baseline for scoring)
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
            stops, duration_minutes, shortest_duration
        )
        
        # Apply different scoring approaches:
        # - Hard dimensions (reliability, efficiency, value): Use ACTUAL scores
        #   These have objective data and should reflect true performance
        # - Soft dimensions (comfort, service, amenities): Apply soft baseline
        #   These are harder to measure and may need a minimum floor
        if apply_boost:
            # HARD scoring - no floor, use actual values
            reliability_adj = cls.apply_hard_score(reliability)
            efficiency_adj = cls.apply_hard_score(efficiency)
            value_adj = cls.apply_hard_score(value)
            
            # SOFT scoring - apply minimal baseline
            comfort_adj = cls.apply_soft_baseline(comfort)
            service_adj = cls.apply_soft_baseline(service)
            amenities_adj = cls.apply_soft_baseline(amenities)
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
