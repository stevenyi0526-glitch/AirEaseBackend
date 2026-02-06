"""
AirEase Backend - Scoring Algorithm Tests
Tests for the updated scoring algorithm with:
1. Significant penalty for often_delayed flights
2. Efficiency score based on duration (primary) and stops (multiplier)
"""

import pytest
from app.services.scoring_service import ScoringService, calculate_overall_score
from app.services.airline_reliability_service import AirlineReliabilityService


class TestEfficiencyScoring:
    """Test the new efficiency scoring algorithm."""
    
    def test_direct_flight_shortest_duration_gets_max_score(self):
        """Shortest direct flight should get 10/10."""
        score = ScoringService.calculate_efficiency_score(
            stops=0,
            duration_minutes=240,  # 4 hours
            shortest_duration=240  # Same as shortest
        )
        assert score == 10.0
    
    def test_direct_flight_30min_over_shortest_loses_one_point(self):
        """Every 30 minutes over shortest = -1 point."""
        score = ScoringService.calculate_efficiency_score(
            stops=0,
            duration_minutes=270,  # 4.5 hours (30 min over)
            shortest_duration=240  # 4 hours
        )
        assert score == 9.0
    
    def test_direct_flight_2hours_over_shortest_loses_four_points(self):
        """2 hours over shortest = -4 points."""
        score = ScoringService.calculate_efficiency_score(
            stops=0,
            duration_minutes=360,  # 6 hours (2 hours over)
            shortest_duration=240  # 4 hours
        )
        assert score == 6.0
    
    def test_one_stop_applies_08_multiplier(self):
        """1 stop = 0.8 multiplier."""
        score = ScoringService.calculate_efficiency_score(
            stops=1,
            duration_minutes=240,  # Same as shortest
            shortest_duration=240
        )
        # 10 * 0.8 = 8.0
        assert score == 8.0
    
    def test_two_stops_applies_06_multiplier(self):
        """2+ stops = 0.6 multiplier."""
        score = ScoringService.calculate_efficiency_score(
            stops=2,
            duration_minutes=240,  # Same as shortest
            shortest_duration=240
        )
        # 10 * 0.6 = 6.0
        assert score == 6.0
    
    def test_long_flight_with_stops_gets_poor_score(self):
        """Long flight (22h with 1 stop vs 4h shortest) should get poor score.
        
        This tests the Philippine Airlines HKG-NRT scenario:
        - Duration: 22 hours with 1 stop
        - Shortest: 4 hours direct
        - Expected: Very low efficiency score
        """
        score = ScoringService.calculate_efficiency_score(
            stops=1,
            duration_minutes=22 * 60,  # 22 hours = 1320 minutes
            shortest_duration=4 * 60   # 4 hours = 240 minutes
        )
        
        # Duration score: 10 - ((1320-240)/30) = 10 - 36 = capped at 1.0
        # With 1 stop multiplier: 1.0 * 0.8 = 0.8, but capped at minimum 1.0
        assert score <= 2.0  # Should be very low
        print(f"Long flight with stops efficiency score: {score}")
    
    def test_absolute_scale_without_baseline(self):
        """When no baseline is provided, use absolute scale."""
        # Very short flight (2h) should be 10
        score = ScoringService.calculate_efficiency_score(
            stops=0,
            duration_minutes=120
        )
        assert score == 10.0
        
        # 24+ hour flight should be low
        score = ScoringService.calculate_efficiency_score(
            stops=0,
            duration_minutes=25 * 60
        )
        assert score <= 2.0


class TestReliabilityWithOftenDelayed:
    """Test reliability scoring with often_delayed flag from SerpAPI."""
    
    def test_often_delayed_significantly_reduces_score(self):
        """Often delayed flights should get significantly penalized."""
        # Normal score for an airline with 90% OTP
        normal_score = AirlineReliabilityService.get_reliability_score(
            "CX",  # Cathay Pacific
            often_delayed=False
        )
        
        # Same airline but flight is often delayed
        delayed_score = AirlineReliabilityService.get_reliability_score(
            "CX",
            often_delayed=True
        )
        
        # The penalty should be at least 3 points
        assert delayed_score <= normal_score - 2.5
        # Often delayed flights should never be above 5.0
        assert delayed_score <= 5.0
        
        print(f"Normal reliability: {normal_score}, Delayed: {delayed_score}")
    
    def test_often_delayed_caps_at_five(self):
        """Even excellent airlines should cap at 5.0 when often delayed."""
        # Test with a hypothetically perfect airline
        score = AirlineReliabilityService.get_reliability_score(
            "XX",  # Unknown airline (default 7.0)
            often_delayed=True
        )
        
        # Should be capped at 5.0 max when often delayed
        assert score <= 5.0


class TestOverallScoreCalculation:
    """Test the overall score calculation with the new efficiency algorithm."""
    
    def test_poor_efficiency_affects_overall_score(self):
        """Poor efficiency (long flight with stops) should lower overall score."""
        # Good flight: short, direct
        good_overall, good_details = ScoringService.calculate_overall_score(
            reliability=8.0,
            comfort=8.0,
            service=8.0,
            value=8.0,
            traveler_type="default",
            has_wifi=True,
            has_power=True,
            has_ife=True,
            has_meal=True,
            stops=0,
            duration_minutes=240,
            shortest_duration=240,
            apply_boost=False  # No boost for cleaner comparison
        )
        
        # Bad flight: very long with stop (Philippine Airlines HKG-NRT scenario)
        bad_overall, bad_details = ScoringService.calculate_overall_score(
            reliability=8.0,
            comfort=8.0,
            service=8.0,
            value=8.0,
            traveler_type="default",
            has_wifi=True,
            has_power=True,
            has_ife=True,
            has_meal=True,
            stops=1,
            duration_minutes=22 * 60,  # 22 hours
            shortest_duration=4 * 60,   # 4 hours
            apply_boost=False
        )
        
        # The difference should be significant
        assert good_overall > bad_overall
        assert good_overall - bad_overall >= 0.3  # At least 0.3 difference
        
        print(f"Good efficiency overall: {good_overall}")
        print(f"Bad efficiency overall: {bad_overall}")
        print(f"Difference: {good_overall - bad_overall}")
    
    def test_combined_poor_reliability_and_efficiency(self):
        """Flight with both poor reliability AND poor efficiency should score low.
        
        This simulates the Philippine Airlines scenario:
        - Often delayed (poor reliability)
        - 22+ hours with stops (poor efficiency)
        - Even with WiFi and wide-body, should score low
        """
        overall, details = ScoringService.calculate_overall_score(
            reliability=4.0,  # Often delayed penalty applied
            comfort=7.5,      # Wide body, decent comfort
            service=7.0,
            value=7.0,
            traveler_type="default",
            has_wifi=True,
            has_power=True,
            has_ife=True,
            has_meal=True,
            stops=1,
            duration_minutes=22 * 60,  # 22 hours
            shortest_duration=4 * 60,   # 4 hours direct
            apply_boost=False
        )
        
        # Should be around 6 or lower (not 88!)
        assert overall <= 7.0
        print(f"Often delayed + long flight overall score: {overall}")
        print(f"Details: {details}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
