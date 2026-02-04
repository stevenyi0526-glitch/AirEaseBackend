"""
AirEase Backend - Aircraft Comfort Service
飞机舒适度数据服务

Uses aircraft_comfort table from PostgreSQL database to provide
accurate comfort metrics for different aircraft models.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from functools import lru_cache
import re

from sqlalchemy import text
from app.database import SessionLocal


@dataclass
class AircraftComfortData:
    """Aircraft comfort specifications"""
    aircraft_model: str
    seat_width_economy: float
    seat_pitch_economy: int
    recline_economy: int
    ife_screen_economy: int
    seat_width_business: float
    seat_pitch_business: int
    ife_screen_business: int


class AircraftComfortService:
    """
    Service for retrieving aircraft comfort data from the database.
    
    Data includes:
    - Seat width (inches)
    - Seat pitch (inches) 
    - Recline angle (degrees)
    - IFE screen size (inches)
    
    For both Economy and Business class.
    """
    
    # Cache for aircraft comfort data
    _cache: Dict[str, AircraftComfortData] = {}
    _cache_loaded: bool = False
    
    # Reference values for scoring (industry averages)
    ECONOMY_BENCHMARKS = {
        "seat_width": {"min": 16.5, "avg": 17.3, "max": 18.5},    # inches
        "seat_pitch": {"min": 28, "avg": 31, "max": 34},          # inches
        "recline": {"min": 3, "avg": 5, "max": 7},                # degrees
        "ife_screen": {"min": 6, "avg": 10, "max": 13},           # inches
    }
    
    BUSINESS_BENCHMARKS = {
        "seat_width": {"min": 19, "avg": 21, "max": 24},          # inches
        "seat_pitch": {"min": 36, "avg": 60, "max": 80},          # inches (or lie-flat)
        "ife_screen": {"min": 12, "avg": 16, "max": 24},          # inches
    }
    
    @classmethod
    def _load_cache(cls):
        """Load all aircraft comfort data from database into cache."""
        if cls._cache_loaded:
            return
        
        try:
            db = SessionLocal()
            result = db.execute(text("""
                SELECT 
                    aircraft_model,
                    seat_width_economy,
                    seat_pitch_economy,
                    recline_economy,
                    ife_screen_economy,
                    seat_width_business,
                    seat_pitch_business,
                    ife_screen_business
                FROM aircraft_comfort
            """))
            
            for row in result:
                comfort_data = AircraftComfortData(
                    aircraft_model=row[0],
                    seat_width_economy=float(row[1]) if row[1] else 17.0,
                    seat_pitch_economy=int(row[2]) if row[2] else 31,
                    recline_economy=int(row[3]) if row[3] else 5,
                    ife_screen_economy=int(row[4]) if row[4] else 9,
                    seat_width_business=float(row[5]) if row[5] else 21.0,
                    seat_pitch_business=int(row[6]) if row[6] else 60,
                    ife_screen_business=int(row[7]) if row[7] else 15,
                )
                cls._cache[row[0].lower()] = comfort_data
                
                # Also create aliases for common variations
                model_lower = row[0].lower()
                # E.g., "Boeing 787-9" -> "787-9", "787"
                if "boeing" in model_lower or "airbus" in model_lower:
                    # Extract model number
                    parts = model_lower.replace("boeing", "").replace("airbus", "").strip()
                    cls._cache[parts] = comfort_data
            
            db.close()
            cls._cache_loaded = True
            print(f"✅ Aircraft comfort cache loaded: {len(cls._cache)} entries")
            
        except Exception as e:
            print(f"⚠️ Failed to load aircraft comfort data: {e}")
            cls._cache_loaded = True  # Prevent repeated failures
    
    @classmethod
    def _normalize_aircraft_model(cls, model: str) -> str:
        """
        Normalize aircraft model name for matching.
        E.g., "B787-9", "Boeing 787-9 Dreamliner" -> "boeing 787-9"
        """
        if not model:
            return ""
        
        normalized = model.lower().strip()
        
        # Common abbreviation mappings
        normalized = normalized.replace("b737", "boeing 737")
        normalized = normalized.replace("b747", "boeing 747")
        normalized = normalized.replace("b757", "boeing 757")
        normalized = normalized.replace("b767", "boeing 767")
        normalized = normalized.replace("b777", "boeing 777")
        normalized = normalized.replace("b787", "boeing 787")
        normalized = normalized.replace("a320", "airbus a320")
        normalized = normalized.replace("a321", "airbus a321")
        normalized = normalized.replace("a330", "airbus a330")
        normalized = normalized.replace("a350", "airbus a350")
        normalized = normalized.replace("a380", "airbus a380")
        
        # Remove common suffixes like "Dreamliner", "neo"
        # but keep important variants like "-9", "-300ER"
        
        return normalized
    
    @classmethod
    def _find_best_match(cls, aircraft_model: str) -> Optional[AircraftComfortData]:
        """
        Find the best matching aircraft comfort data.
        Uses fuzzy matching to handle variations in naming.
        """
        cls._load_cache()
        
        if not aircraft_model:
            return None
        
        normalized = cls._normalize_aircraft_model(aircraft_model)
        
        # Direct match
        if normalized in cls._cache:
            return cls._cache[normalized]
        
        # Try to find partial matches
        # Extract key identifiers (e.g., "787-9", "A350-900")
        for key, data in cls._cache.items():
            # Check if the key appears in our normalized model
            if key in normalized:
                return data
            # Check if our normalized model appears in the key
            if normalized in key:
                return data
        
        # Try matching just the main model number
        # E.g., "787" from "Boeing 787-9 Dreamliner"
        model_patterns = [
            r"(787-\d+)",
            r"(777-\d+\w*)",
            r"(767-\d+)",
            r"(747-\d+)",
            r"(737-\d+)",
            r"(737\s*max\s*\d+)",
            r"(a350-\d+)",
            r"(a330-\d+)",
            r"(a321\w*)",
            r"(a320\w*)",
            r"(a380-\d+)",
            r"(e\d{3})",  # Embraer E175, E190
            r"(crj\d+)",  # Bombardier CRJ
        ]
        
        for pattern in model_patterns:
            match = re.search(pattern, normalized)
            if match:
                extracted = match.group(1)
                for key, data in cls._cache.items():
                    if extracted in key or key in extracted:
                        return data
        
        return None
    
    @classmethod
    def get_comfort_data(cls, aircraft_model: str) -> Optional[AircraftComfortData]:
        """
        Get comfort data for an aircraft model.
        
        Args:
            aircraft_model: Aircraft model string (e.g., "Boeing 787-9", "A350-900")
            
        Returns:
            AircraftComfortData if found, None otherwise
        """
        return cls._find_best_match(aircraft_model)
    
    @classmethod
    def calculate_comfort_score(
        cls,
        aircraft_model: Optional[str],
        cabin_class: str = "economy",
        has_wifi: bool = False,
        has_power: bool = False,
        has_ife: bool = False,
        legroom_override: Optional[int] = None  # Override from API if available
    ) -> tuple[float, Dict[str, Any]]:
        """
        Calculate comfort score (0-10) based on aircraft comfort data.
        
        Args:
            aircraft_model: Aircraft model string
            cabin_class: "economy", "business", or "first"
            has_wifi: Whether WiFi is available
            has_power: Whether power outlets are available
            has_ife: Whether in-flight entertainment is available
            legroom_override: Override seat pitch from API data
            
        Returns:
            Tuple of (score, details_dict)
        """
        comfort_data = cls.get_comfort_data(aircraft_model) if aircraft_model else None
        is_business = cabin_class.lower() in ["business", "公务舱", "first", "头等舱"]
        
        # Initialize scoring components
        seat_width_score = 5.0
        seat_pitch_score = 5.0
        recline_score = 5.0
        ife_score = 5.0
        
        details = {
            "aircraft_model": aircraft_model,
            "cabin_class": cabin_class,
            "data_source": "database" if comfort_data else "default",
            "seat_width": None,
            "seat_pitch": None,
            "recline": None,
            "ife_screen": None,
        }
        
        if comfort_data:
            if is_business:
                seat_width = comfort_data.seat_width_business
                seat_pitch = comfort_data.seat_pitch_business
                ife_screen = comfort_data.ife_screen_business
                recline = 15  # Business class typically has much more recline
                benchmarks = cls.BUSINESS_BENCHMARKS
            else:
                seat_width = comfort_data.seat_width_economy
                seat_pitch = comfort_data.seat_pitch_economy
                recline = comfort_data.recline_economy
                ife_screen = comfort_data.ife_screen_economy
                benchmarks = cls.ECONOMY_BENCHMARKS
            
            # Use legroom override if provided (from API data)
            if legroom_override:
                seat_pitch = legroom_override
            
            details["seat_width"] = seat_width
            details["seat_pitch"] = seat_pitch
            details["recline"] = recline
            details["ife_screen"] = ife_screen
            
            # Calculate seat width score (0-10)
            if is_business:
                seat_width_score = cls._normalize_score(
                    seat_width,
                    benchmarks["seat_width"]["min"],
                    benchmarks["seat_width"]["max"]
                )
            else:
                seat_width_score = cls._normalize_score(
                    seat_width,
                    benchmarks["seat_width"]["min"],
                    benchmarks["seat_width"]["max"]
                )
            
            # Calculate seat pitch score (0-10)
            seat_pitch_score = cls._normalize_score(
                seat_pitch,
                benchmarks["seat_pitch"]["min"],
                benchmarks["seat_pitch"]["max"]
            )
            
            # Calculate recline score (economy only, business assumed good)
            if is_business:
                recline_score = 9.0  # Business class recline is typically excellent
            else:
                recline_score = cls._normalize_score(
                    recline,
                    cls.ECONOMY_BENCHMARKS["recline"]["min"],
                    cls.ECONOMY_BENCHMARKS["recline"]["max"]
                )
            
            # Calculate IFE screen score
            if is_business:
                ife_score = cls._normalize_score(
                    ife_screen,
                    benchmarks["ife_screen"]["min"],
                    benchmarks["ife_screen"]["max"]
                )
            else:
                ife_score = cls._normalize_score(
                    ife_screen,
                    cls.ECONOMY_BENCHMARKS["ife_screen"]["min"],
                    cls.ECONOMY_BENCHMARKS["ife_screen"]["max"]
                )
        else:
            # No aircraft data - use default values with legroom override if available
            if legroom_override:
                benchmarks = cls.ECONOMY_BENCHMARKS if not is_business else cls.BUSINESS_BENCHMARKS
                seat_pitch_score = cls._normalize_score(
                    legroom_override,
                    benchmarks["seat_pitch"]["min"],
                    benchmarks["seat_pitch"]["max"]
                )
                details["seat_pitch"] = legroom_override
                details["data_source"] = "api_legroom"
        
        # Weighted average of comfort components
        # Seat pitch is most important for comfort perception
        base_score = (
            seat_width_score * 0.20 +
            seat_pitch_score * 0.40 +
            recline_score * 0.15 +
            ife_score * 0.25
        )
        
        # Amenity bonuses
        amenity_bonus = 0.0
        if has_wifi:
            amenity_bonus += 0.3
        if has_power:
            amenity_bonus += 0.2
        if has_ife:
            amenity_bonus += 0.2
        
        # Final score capped at 10
        final_score = min(10.0, base_score + amenity_bonus)
        final_score = round(final_score, 1)
        
        details["component_scores"] = {
            "seat_width": round(seat_width_score, 1),
            "seat_pitch": round(seat_pitch_score, 1),
            "recline": round(recline_score, 1),
            "ife": round(ife_score, 1),
            "amenity_bonus": round(amenity_bonus, 1),
        }
        details["final_score"] = final_score
        
        return final_score, details
    
    @staticmethod
    def _normalize_score(value: float, min_val: float, max_val: float) -> float:
        """
        Normalize a value to 0-10 score based on min/max range.
        Values at min get 3, at avg get 6, at max get 10.
        """
        if value <= min_val:
            return 3.0
        elif value >= max_val:
            return 10.0
        else:
            # Linear interpolation between min and max
            range_val = max_val - min_val
            normalized = (value - min_val) / range_val
            return 3.0 + normalized * 7.0
    
    @classmethod
    def get_comfort_explanation(
        cls,
        aircraft_model: Optional[str],
        cabin_class: str = "economy",
        comfort_score: float = 7.0
    ) -> list:
        """
        Generate comfort-related explanations for the score breakdown.
        
        Returns list of (title, detail, is_positive) tuples.
        """
        explanations = []
        comfort_data = cls.get_comfort_data(aircraft_model) if aircraft_model else None
        is_business = cabin_class.lower() in ["business", "公务舱", "first", "头等舱"]
        
        if comfort_data:
            if is_business:
                seat_pitch = comfort_data.seat_pitch_business
                seat_width = comfort_data.seat_width_business
                ife_screen = comfort_data.ife_screen_business
            else:
                seat_pitch = comfort_data.seat_pitch_economy
                seat_width = comfort_data.seat_width_economy
                ife_screen = comfort_data.ife_screen_economy
            
            # Seat pitch explanation
            if is_business:
                pitch_positive = seat_pitch >= 60
                pitch_desc = "above average" if pitch_positive else "standard"
            else:
                pitch_positive = seat_pitch >= 32
                pitch_desc = "above average" if pitch_positive else ("standard" if seat_pitch >= 31 else "below average")
            
            explanations.append({
                "title": "Seat Pitch (Legroom)",
                "detail": f"{seat_pitch} inches - {pitch_desc} for {cabin_class}",
                "is_positive": pitch_positive
            })
            
            # Seat width explanation
            width_avg = 17.3 if not is_business else 21.0
            width_positive = seat_width >= width_avg
            explanations.append({
                "title": "Seat Width",
                "detail": f"{seat_width} inches - {'wider than' if width_positive else 'narrower than'} average",
                "is_positive": width_positive
            })
            
            # IFE screen explanation
            ife_avg = 10 if not is_business else 16
            ife_positive = ife_screen >= ife_avg
            if ife_screen > 0:
                explanations.append({
                    "title": "Entertainment Screen",
                    "detail": f"{ife_screen}-inch display - {'larger than' if ife_positive else 'smaller than'} average",
                    "is_positive": ife_positive
                })
        else:
            # No specific aircraft data
            explanations.append({
                "title": "Seat Comfort",
                "detail": f"Standard seating for {cabin_class}",
                "is_positive": comfort_score >= 7.0
            })
        
        # Aircraft type explanation (wide-body vs narrow-body)
        if aircraft_model:
            is_widebody = any(x in aircraft_model.lower() for x in 
                            ["787", "777", "767", "747", "350", "330", "380", "340"])
            if is_widebody:
                explanations.append({
                    "title": "Wide-body Aircraft",
                    "detail": f"{aircraft_model} offers a more spacious cabin with lower noise levels",
                    "is_positive": True
                })
        
        return explanations


# Module-level convenience functions
def get_comfort_score(
    aircraft_model: Optional[str],
    cabin_class: str = "economy",
    has_wifi: bool = False,
    has_power: bool = False,
    has_ife: bool = False,
    legroom_override: Optional[int] = None
) -> float:
    """Get comfort score for an aircraft."""
    score, _ = AircraftComfortService.calculate_comfort_score(
        aircraft_model, cabin_class, has_wifi, has_power, has_ife, legroom_override
    )
    return score


def get_comfort_details(
    aircraft_model: Optional[str],
    cabin_class: str = "economy"
) -> Optional[AircraftComfortData]:
    """Get detailed comfort data for an aircraft."""
    return AircraftComfortService.get_comfort_data(aircraft_model)
