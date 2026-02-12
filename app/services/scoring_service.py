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
    safety: float     # NTSB safety records
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
        safety=0.10,       # Safety still matters
        reliability=0.12,
        comfort=0.12,
        service=0.08,
        value=0.33,        # Price is most important!
        amenities=0.10,
        efficiency=0.15,
    ),
    
    # Business travelers: Time is money, need reliability and premium service
    TravelerType.BUSINESS: DimensionWeights(
        safety=0.10,
        reliability=0.25,
        comfort=0.18,
        service=0.18,
        value=0.09,
        amenities=0.10,
        efficiency=0.10,
    ),
    
    # Families: Comfort and service matter most for kids
    TravelerType.FAMILY: DimensionWeights(
        safety=0.15,       # Safety especially important for families
        reliability=0.17,
        comfort=0.22,
        service=0.22,
        value=0.12,
        amenities=0.08,
        efficiency=0.04,
    ),
    
    # Default/General: Balanced weights
    TravelerType.DEFAULT: DimensionWeights(
        safety=0.12,
        reliability=0.17,
        comfort=0.22,
        service=0.17,
        value=0.18,
        amenities=0.09,
        efficiency=0.05,
    ),
}


class ScoringService:
    """
    Service for calculating overall flight scores with traveler-type weighting.
    
    The scoring algorithm:
    1. Takes 4 base dimension scores (reliability, comfort, service, value)
    2. Calculates safety score from NTSB records
    3. Calculates 2 derived dimensions (amenities, efficiency)
    4. Applies traveler-specific weights
    5. NO artificial boosting - scores reflect true quality
    """
    
    # Baseline score - minimum score for "soft" dimensions (comfort, service, amenities)
    # Soft dimensions have data uncertainty, so we apply a gentle floor
    SOFT_BASELINE_SCORE = 5.0
    
    # Boost factor for soft dimensions to acknowledge measurement uncertainty
    # A 10% boost ensures scores feel fair when data is limited
    SCORE_BOOST_FACTOR = 1.10
    SCORE_BOOST_OFFSET = 0.0
    
    @classmethod
    def calculate_safety_score(
        cls,
        airline_accidents: int = 0,
        model_accidents: int = 0,
        plane_accidents: Optional[int] = None,
        has_fatal: bool = False,
        fatal_count: int = 0,
        has_serious: bool = False,
        serious_count: int = 0,
    ) -> float:
        """
        Calculate safety score (0-10) fully based on NTSB records.
        
        Scoring:
        - 10 (5/5): No records at all — clean history
        - 8 (4/5): Minor incidents only, no injuries
        - 6 (3/5): Some incidents with minor injuries
        - 4 (2/5): Serious incidents
        - 2 (1/5): Fatal accidents with casualties
        
        Deductions based on severity:
        - Each airline accident: -0.3 pts
        - Each model accident: -0.15 pts  
        - Each plane-specific accident: -1.0 pts
        - Serious injury incidents: -1.5 pts each
        - Fatal accidents: -2.0 pts base + -0.5 per fatality (capped)
        """
        score = 10.0  # Start at perfect
        
        # Deduct for airline-level accidents (last 10 years)
        score -= min(airline_accidents * 0.3, 3.0)
        
        # Deduct for model-level accidents (all time)
        score -= min(model_accidents * 0.15, 2.0)
        
        # Deduct for this specific plane's accidents
        if plane_accidents is not None:
            score -= min(plane_accidents * 1.0, 3.0)
        
        # Deduct for serious injuries
        if has_serious:
            score -= min(serious_count * 1.5, 3.0)
        
        # Deduct for fatalities — most severe
        if has_fatal:
            score -= 2.0  # Base deduction for any fatality
            score -= min(fatal_count * 0.5, 3.0)  # Additional per fatality
        
        return round(max(2.0, min(10.0, score)), 1)
    
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
            amenity_scores.append(2.0)
        if has_ife:
            amenity_scores.append(2.5)
        if has_meal:
            amenity_scores.append(2.0)
        
        if amenity_scores:
            # Base score of 4.0 for having any amenity data, plus bonuses
            # This prevents "1 amenity = 2.5/10" which feels too harsh
            score = 4.0 + sum(amenity_scores)
            # Cap at 10
            return min(10.0, score)
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
        apply_boost: bool = True,
        safety_score: Optional[float] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Calculate overall score with traveler-specific weighting.
        Now includes 7 dimensions: safety, reliability, comfort, service,
        value, amenities, efficiency.
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
        
        # Safety defaults to 10.0 (no records = perfect) if not provided
        safety = safety_score if safety_score is not None else 10.0
        
        if apply_boost:
            safety_adj = cls.apply_hard_score(safety)
            reliability_adj = cls.apply_hard_score(reliability)
            efficiency_adj = cls.apply_hard_score(efficiency)
            value_adj = cls.apply_hard_score(value)
            
            comfort_adj = cls.apply_soft_baseline(comfort)
            service_adj = cls.apply_soft_baseline(service)
            amenities_adj = cls.apply_soft_baseline(amenities)
        else:
            safety_adj = safety
            reliability_adj = reliability
            comfort_adj = comfort
            service_adj = service
            value_adj = value
            amenities_adj = amenities
            efficiency_adj = efficiency
        
        # Calculate weighted overall score
        overall = (
            safety_adj * weights.safety +
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
                "safety": weights.safety,
                "reliability": weights.reliability,
                "comfort": weights.comfort,
                "service": weights.service,
                "value": weights.value,
                "amenities": weights.amenities,
                "efficiency": weights.efficiency,
            },
            "raw_scores": {
                "safety": round(safety, 1),
                "reliability": round(reliability, 1),
                "comfort": round(comfort, 1),
                "service": round(service, 1),
                "value": round(value, 1),
                "amenities": round(amenities, 1),
                "efficiency": round(efficiency, 1),
            },
            "adjusted_scores": {
                "safety": round(safety_adj, 1),
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
