"""
AirEase Backend - Airline Reliability Service
Fetches on-time performance (OTP) data from airline_reliability table
"""

from typing import Optional, Dict
from sqlalchemy import text
from app.database import SessionLocal


class AirlineReliabilityService:
    """
    Service to fetch airline reliability (OTP) data from PostgreSQL database.
    Uses the airline_reliability table populated from sql.py
    """
    
    # Cache for airline reliability data (loaded on first access)
    _cache: Dict[str, float] = {}
    _cache_loaded: bool = False
    
    @classmethod
    def _load_cache(cls) -> None:
        """Load all airline reliability data into cache."""
        if cls._cache_loaded:
            return
        
        try:
            db = SessionLocal()
            result = db.execute(text("SELECT code, otp FROM airline_reliability"))
            for row in result:
                # OTP is stored as percentage (0-100), we'll use it as-is
                cls._cache[row.code.upper()] = float(row.otp)
            cls._cache_loaded = True
            print(f"✅ Loaded {len(cls._cache)} airlines into reliability cache")
        except Exception as e:
            print(f"⚠️ Error loading airline reliability cache: {e}")
            cls._cache_loaded = True  # Mark as loaded to avoid repeated errors
        finally:
            db.close()
    
    @classmethod
    def get_otp(cls, airline_code: str) -> Optional[float]:
        """
        Get on-time performance percentage for an airline.
        
        Args:
            airline_code: 2-letter IATA airline code (e.g., "DL", "UA", "CX")
        
        Returns:
            OTP percentage (0-100) or None if not found
        """
        cls._load_cache()
        return cls._cache.get(airline_code.upper())
    
    @classmethod
    def get_reliability_score(
        cls, 
        airline_code: str, 
        often_delayed: bool = False
    ) -> float:
        """
        Get reliability score (0-10) for an airline.
        
        The score is calculated from OTP percentage:
        - OTP 90%+ = 9.0-10.0
        - OTP 80-90% = 7.5-9.0
        - OTP 70-80% = 6.0-7.5
        - OTP below 70% = 4.0-6.0
        
        If the flight is often delayed (30+ min), subtract 1.0 from the score.
        
        Args:
            airline_code: 2-letter IATA airline code
            often_delayed: Whether this specific flight is often delayed 30+ min
        
        Returns:
            Reliability score (0-10)
        """
        otp = cls.get_otp(airline_code)
        
        if otp is None:
            # Default score for unknown airlines
            base_score = 7.0
        else:
            # Convert OTP percentage (0-100) to score (0-10)
            # Using a non-linear scale that emphasizes differences at higher OTPs
            if otp >= 90:
                base_score = 9.0 + (otp - 90) / 10  # 90-100% -> 9.0-10.0
            elif otp >= 80:
                base_score = 7.5 + (otp - 80) * 0.15  # 80-90% -> 7.5-9.0
            elif otp >= 70:
                base_score = 6.0 + (otp - 70) * 0.15  # 70-80% -> 6.0-7.5
            elif otp >= 60:
                base_score = 4.0 + (otp - 60) * 0.2   # 60-70% -> 4.0-6.0
            else:
                base_score = max(2.0, otp / 15)       # Below 60% -> 2.0-4.0
        
        # Apply penalty for often delayed flights (-1.0, minimum score 2.0)
        if often_delayed:
            base_score = max(2.0, base_score - 1.0)
        
        return round(min(10.0, base_score), 1)
    
    @classmethod
    def get_airline_info(cls, airline_code: str) -> Optional[Dict]:
        """
        Get full airline reliability info from database.
        
        Args:
            airline_code: 2-letter IATA airline code
        
        Returns:
            Dict with code, name, otp, region or None if not found
        """
        try:
            db = SessionLocal()
            result = db.execute(
                text("SELECT code, name, otp, region FROM airline_reliability WHERE code = :code"),
                {"code": airline_code.upper()}
            )
            row = result.fetchone()
            if row:
                return {
                    "code": row.code,
                    "name": row.name,
                    "otp": float(row.otp),
                    "region": row.region
                }
            return None
        except Exception as e:
            print(f"Error fetching airline info for {airline_code}: {e}")
            return None
        finally:
            db.close()


# Singleton instance
airline_reliability_service = AirlineReliabilityService()
