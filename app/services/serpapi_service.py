"""
AirEase Backend - SerpAPI Flight Service
Real flight data from Google Flights via SerpAPI
"""

import httpx
from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid

from app.models import (
    Flight, FlightScore, FlightFacilities, FlightWithScore,
    FlightDetail, PriceHistory, PricePoint, PriceTrend,
    ScoreDimensions, ScoreExplanation, ServiceHighlights, UserReviewSummary, UserReviewRatings
)
from app.config import settings
from app.services.airline_reliability_service import AirlineReliabilityService
from app.services.aircraft_comfort_service import AircraftComfortService
from app.services.airline_reviews_service import AirlineReviewsService
from app.services.scoring_service import ScoringService


class SerpAPIFlightService:
    """
    SerpAPI Google Flights Service
    Fetches real flight data including:
    - Flight listings with booking tokens
    - Amenities (WiFi, power, legroom, IFE)
    - Carbon emissions
    - Price insights and history
    """
    
    BASE_URL = "https://serpapi.com/search"
    
    def __init__(self):
        self.api_key = settings.serpapi_key
    
    async def search_flights(
        self,
        departure_id: str,
        arrival_id: str,
        outbound_date: str,
        return_date: Optional[str] = None,
        travel_class: int = 1,  # 1=Economy, 2=Premium Economy, 3=Business, 4=First
        adults: int = 1,
        currency: str = "USD",
        hl: str = "en",
        gl: str = "us",
        stops: Optional[int] = None,  # 0=Any, 1=Nonstop, 2=1 stop or fewer, 3=2 stops or fewer
        deep_search: bool = True,  # Enable for browser-identical results with more flights
        show_hidden: bool = True,  # Include hidden flight results for more options
    ) -> Dict[str, Any]:
        """
        Search flights using SerpAPI Google Flights engine.
        
        Args:
            departure_id: Departure airport code (e.g., "HKG", "LAX")
            arrival_id: Arrival airport code (e.g., "NRT", "LHR")
            outbound_date: Date in YYYY-MM-DD format
            return_date: Return date for round trip (optional)
            travel_class: 1=Economy, 2=Premium Economy, 3=Business, 4=First
            adults: Number of adult passengers
            currency: Currency code (e.g., "USD", "CNY")
            hl: Language code (e.g., "en", "zh-CN")
            gl: Country code (e.g., "us", "cn")
            stops: Filter by number of stops
            deep_search: Enable for browser-identical results (slower but more complete)
            show_hidden: Include hidden flight results for more options
        
        Returns:
            Dict containing flights, price_insights, and airports info
        """
        params = {
            "engine": "google_flights",
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": outbound_date,
            "currency": currency,
            "hl": hl,
            "gl": gl,
            "adults": adults,
            "travel_class": travel_class,
            "api_key": self.api_key,
        }
        
        # Flight type: 1=Round trip, 2=One way
        if return_date:
            params["type"] = "1"
            params["return_date"] = return_date
        else:
            params["type"] = "2"
        
        if stops is not None:
            params["stops"] = stops
        
        # Enable deep_search for more complete results (browser-identical)
        if deep_search:
            params["deep_search"] = "true"
        
        # Enable show_hidden to include hidden flight results
        if show_hidden:
            params["show_hidden"] = "true"
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            return response.json()
    
    def parse_flight_response(
        self,
        serpapi_response: Dict[str, Any],
        cabin_filter: str = "economy"
    ) -> tuple[List[FlightWithScore], Optional[Dict[str, Any]]]:
        """
        Parse SerpAPI response into FlightWithScore objects.
        
        Returns:
            Tuple of (list of FlightWithScore, price_insights dict)
        """
        flights_list: List[FlightWithScore] = []
        
        # Combine best_flights and other_flights
        best_flights = serpapi_response.get("best_flights", [])
        other_flights = serpapi_response.get("other_flights", [])
        all_flights = best_flights + other_flights
        
        price_insights = serpapi_response.get("price_insights")
        
        for idx, flight_data in enumerate(all_flights):
            try:
                parsed_flight = self._parse_single_flight(flight_data, idx, cabin_filter, price_insights)
                if parsed_flight:
                    flights_list.append(parsed_flight)
            except Exception as e:
                print(f"Error parsing flight {idx}: {e}")
                continue
        
        return flights_list, price_insights
    
    def _parse_single_flight(
        self,
        flight_data: Dict[str, Any],
        index: int,
        cabin_filter: str,
        price_insights: Optional[Dict[str, Any]] = None
    ) -> Optional[FlightWithScore]:
        """Parse a single flight from SerpAPI response."""
        
        segments = flight_data.get("flights", [])
        if not segments:
            return None
        
        # First segment for departure info
        first_segment = segments[0]
        # Last segment for arrival info
        last_segment = segments[-1]
        
        # Parse departure info
        dep_airport = first_segment.get("departure_airport", {})
        arr_airport = last_segment.get("arrival_airport", {})
        
        departure_time = dep_airport.get("time", "")
        arrival_time = arr_airport.get("time", "")
        
        # Parse times to datetime
        try:
            dep_dt = datetime.strptime(departure_time, "%Y-%m-%d %H:%M")
            arr_dt = datetime.strptime(arrival_time, "%Y-%m-%d %H:%M")
        except ValueError:
            dep_dt = datetime.now()
            arr_dt = datetime.now()
        
        # Calculate layovers
        layovers = flight_data.get("layovers", [])
        stops_count = len(layovers)
        stop_cities = [lay.get("name", "Unknown") for lay in layovers]
        
        # Get airline info
        airline = first_segment.get("airline", "Unknown Airline")
        airline_logo = first_segment.get("airline_logo", "")
        flight_number = first_segment.get("flight_number", f"XX{index+1000}")
        airplane = first_segment.get("airplane", "Unknown Aircraft")
        travel_class = first_segment.get("travel_class", "Economy")
        
        # Extract legroom
        legroom = first_segment.get("legroom", "")
        legroom_inches = self._parse_legroom(legroom)
        
        # Parse extensions (amenities)
        extensions = first_segment.get("extensions", [])
        facilities = self._parse_amenities(extensions, legroom_inches)
        
        # Get carbon emissions
        carbon_data = flight_data.get("carbon_emissions", {})
        
        # Build the Flight model
        flight = Flight(
            id=f"serp-{uuid.uuid4().hex[:8]}",
            flight_number=flight_number,
            airline=airline,
            airline_code=self._extract_airline_code(flight_number),
            departure_city=dep_airport.get("name", "").split(" Airport")[0].strip() or dep_airport.get("id", ""),
            departure_city_code=dep_airport.get("id", ""),
            departure_airport=dep_airport.get("name", ""),
            departure_airport_code=dep_airport.get("id", ""),
            departure_time=dep_dt,
            arrival_city=arr_airport.get("name", "").split(" Airport")[0].strip() or arr_airport.get("id", ""),
            arrival_city_code=arr_airport.get("id", ""),
            arrival_airport=arr_airport.get("name", ""),
            arrival_airport_code=arr_airport.get("id", ""),
            arrival_time=arr_dt,
            duration_minutes=flight_data.get("total_duration", 0),
            stops=stops_count,
            stop_cities=stop_cities if stop_cities else None,
            cabin=travel_class,
            aircraft_model=airplane,
            price=float(flight_data.get("price", 0)),
            currency="USD",
            seats_remaining=None,  # Not provided by SerpAPI
            
            # === NEW SERPAPI FIELDS ===
            booking_token=flight_data.get("booking_token"),
            airline_logo=airline_logo,
            carbon_emissions=carbon_data,
            flight_extensions=flight_data.get("extensions", []),
            ticket_also_sold_by=first_segment.get("ticket_also_sold_by", []),
            often_delayed=first_segment.get("often_delayed_by_over_30_min", False),
            is_overnight=first_segment.get("overnight", False),
            layover_details=[
                {
                    "durationMinutes": lay.get("duration", 0),
                    "airportName": lay.get("name", "Unknown"),
                    "airportCode": lay.get("id", ""),
                    "isOvernight": lay.get("overnight", False)
                }
                for lay in layovers
            ] if layovers else None,
        )
        
        # Generate score based on SerpAPI data (including price_insights for value score)
        score = self._generate_score_from_serpapi(
            flight_data, facilities, carbon_data, first_segment, price_insights,
            aircraft_model=airplane, cabin_class=travel_class, airline_name=airline
        )
        
        return FlightWithScore(
            flight=flight,
            score=score,
            facilities=facilities,
        )
    
    def _parse_legroom(self, legroom_str: str) -> Optional[int]:
        """Extract legroom inches from string like '31 in'"""
        if not legroom_str:
            return None
        try:
            # Extract number from string like "31 in"
            parts = legroom_str.split()
            if parts:
                return int(parts[0])
        except (ValueError, IndexError):
            pass
        return None
    
    def _parse_amenities(
        self,
        extensions: List[str],
        legroom_inches: Optional[int]
    ) -> FlightFacilities:
        """Parse amenities from SerpAPI extensions list."""
        
        has_wifi = False
        wifi_free = False
        has_power = False
        has_ife = False
        ife_type = None
        meal_included = None  # SerpAPI doesn't typically provide meal info per flight
        
        # Join extensions for easier searching
        ext_lower = [e.lower() for e in extensions]
        ext_joined = " ".join(ext_lower)
        
        # Check for WiFi
        if "wi-fi" in ext_joined or "wifi" in ext_joined:
            has_wifi = True
            if "free wi-fi" in ext_joined or "free wifi" in ext_joined:
                wifi_free = True
        
        # Check for power
        if "power" in ext_joined or "usb" in ext_joined:
            has_power = True
        
        # Check for in-flight entertainment
        if "video" in ext_joined or "tv" in ext_joined or "entertainment" in ext_joined:
            has_ife = True
            if "on-demand" in ext_joined:
                ife_type = "On-demand video"
            elif "live tv" in ext_joined:
                ife_type = "Live TV"
            elif "stream" in ext_joined:
                ife_type = "Stream to device"
        
        # Determine seat pitch category
        seat_pitch_category = None
        if legroom_inches:
            if legroom_inches >= 34:
                seat_pitch_category = "Above average"
            elif legroom_inches >= 31:
                seat_pitch_category = "Average"
            else:
                seat_pitch_category = "Below average"
        
        return FlightFacilities(
            has_wifi=has_wifi,
            has_power=has_power,
            seat_pitch_inches=legroom_inches,
            seat_pitch_category=seat_pitch_category,
            has_ife=has_ife,
            ife_type=ife_type,
            meal_included=meal_included,
            meal_type=None,
        )
    
    def _extract_airline_code(self, flight_number: str) -> str:
        """Extract airline code from flight number like 'BA 301'"""
        if not flight_number:
            return "XX"
        parts = flight_number.split()
        if parts:
            code = parts[0]
            # Return only letters from the code
            return ''.join(c for c in code if c.isalpha())[:2].upper()
        return "XX"
    
    def _calculate_value_score(
        self, 
        current_price: float, 
        price_insights: Optional[Dict[str, Any]]
    ) -> float:
        """
        Calculate value score based on Google Flights price_insights.
        
        Uses price_level from Google if available, otherwise falls back to
        typical_price_range comparison, or a simple price-based heuristic.
        
        Args:
            current_price: The flight's current price
            price_insights: Price insights dict from SerpAPI (may be None)
        
        Returns:
            Value score from 0-10
        """
        if not price_insights:
            # Fallback: No price insights available, use simple price-based scoring
            if current_price <= 0:
                return 6.0  # Neutral score
            elif current_price < 300:
                return 9.0
            elif current_price < 500:
                return 8.0
            elif current_price < 800:
                return 7.0
            elif current_price < 1200:
                return 6.0
            else:
                return 5.0
        
        # Case 1: Use price_level if available (most reliable - Google's assessment)
        price_level = price_insights.get("price_level")
        if price_level:
            if price_level == "low":
                return 10.0  # Excellent value - below typical prices
            elif price_level == "typical":
                return 7.0   # Normal value - within typical range
            else:  # "high"
                return 4.0   # Poor value - above typical prices
        
        # Case 2: Use typical_price_range if available (manual calculation)
        typical_range = price_insights.get("typical_price_range")
        if typical_range and len(typical_range) == 2:
            low, high = typical_range
            if current_price < low:
                return 10.0  # Excellent - below typical range
            elif current_price <= high:
                # Scale between 6-8 based on position in range
                position = (current_price - low) / (high - low) if high > low else 0.5
                return round(8.0 - position * 2, 1)  # 8.0 at low end, 6.0 at high end
            else:
                # Above typical range - poor value
                overage_pct = (current_price - high) / high if high > 0 else 0
                return max(2.0, 5.0 - overage_pct * 5)  # Scale down based on how much over
        
        # Case 3: No price insights - return neutral score
        return 6.0
    
    def _get_price_insight_detail(
        self, 
        current_price: float, 
        price_insights: Optional[Dict[str, Any]]
    ) -> str:
        """
        Generate a user-friendly description of the price insight.
        
        Args:
            current_price: The flight's current price
            price_insights: Price insights dict from SerpAPI
        
        Returns:
            Human-readable price insight string
        """
        if not price_insights:
            return f"Price: ${current_price:.0f}" if current_price > 0 else "Price varies"
        
        price_level = price_insights.get("price_level")
        typical_range = price_insights.get("typical_price_range")
        
        # Build the detail string
        parts = []
        
        # Current price
        if current_price > 0:
            parts.append(f"${current_price:.0f}")
        
        # Price level assessment
        if price_level == "low":
            parts.append("below typical price 🎉")
        elif price_level == "high":
            parts.append("above typical price")
        elif price_level == "typical":
            parts.append("within typical range")
        
        # Typical range context
        if typical_range and len(typical_range) == 2:
            low, high = typical_range
            parts.append(f"(typical: ${low:.0f}-${high:.0f})")
        
        return " ".join(parts) if parts else f"Price: ${current_price:.0f}"

    def _generate_score_from_serpapi(
        self,
        flight_data: Dict[str, Any],
        facilities: FlightFacilities,
        carbon_data: Dict[str, Any],
        first_segment: Dict[str, Any],
        price_insights: Optional[Dict[str, Any]] = None,
        aircraft_model: str = None,
        cabin_class: str = "Economy",
        airline_name: str = None
    ) -> FlightScore:
        """Generate flight score based on SerpAPI data, aircraft comfort database, and airline reviews."""
        
        # Extract airline info
        flight_number = first_segment.get("flight_number", "")
        airline_code = self._extract_airline_code(flight_number)
        airline = airline_name or first_segment.get("airline", "Unknown")
        
        # Check if flight is often delayed (30+ min)
        often_delayed = first_segment.get("often_delayed_by_over_30_min", False)
        
        # Get reliability score from database (based on airline OTP)
        reliability = AirlineReliabilityService.get_reliability_score(
            airline_code, 
            often_delayed=often_delayed
        )
        airline_otp = AirlineReliabilityService.get_otp(airline_code)
        
        # ============================================================
        # SEPARATE ECONOMY AND BUSINESS CLASS RATINGS
        # ============================================================
        
        # Calculate ECONOMY class comfort score
        comfort_economy, comfort_details_economy = AircraftComfortService.calculate_comfort_score(
            aircraft_model=aircraft_model,
            cabin_class="economy",
            has_wifi=facilities.has_wifi or False,
            has_power=facilities.has_power or False,
            has_ife=facilities.has_ife or False,
            legroom_override=None  # Use database values for economy
        )
        
        # Calculate BUSINESS class comfort score
        comfort_business, comfort_details_business = AircraftComfortService.calculate_comfort_score(
            aircraft_model=aircraft_model,
            cabin_class="business",
            has_wifi=True,  # Business usually has all amenities
            has_power=True,
            has_ife=True,
            legroom_override=None
        )
        
        # Calculate SERVICE scores from airline reviews database
        service_economy, service_details_economy = AirlineReviewsService.calculate_service_score(
            airline_name=airline,
            cabin_class="economy"
        )
        
        service_business, service_details_business = AirlineReviewsService.calculate_service_score(
            airline_name=airline,
            cabin_class="business"
        )
        
        # Get user reviews
        user_reviews_raw = AirlineReviewsService.get_user_reviews(
            airline_name=airline,
            cabin_class=cabin_class,
            limit=10
        )
        
        # Convert to API model with nested ratings object
        user_reviews = [
            UserReviewSummary(
                title=r.title,
                review=r.review[:500] if len(r.review) > 500 else r.review,  # Truncate long reviews
                food_rating=r.food_rating,
                ground_service_rating=r.ground_service_rating,
                seat_comfort_rating=r.seat_comfort_rating,
                service_rating=r.service_rating,
                recommended=r.recommended,
                travel_type=r.travel_type,
                route=r.route,
                aircraft=r.aircraft,
                cabin_type=r.cabin_type,
                ratings=UserReviewRatings(
                    food=r.food_rating,
                    ground_service=r.ground_service_rating,
                    seat_comfort=r.seat_comfort_rating,
                    service=r.service_rating,
                    overall=round((r.food_rating + r.ground_service_rating + r.seat_comfort_rating + r.service_rating) / 4, 1) if r.food_rating else None
                )
            )
            for r in user_reviews_raw
        ]
        
        # Determine which comfort/service to use based on selected cabin class
        is_business = "business" in cabin_class.lower() or "first" in cabin_class.lower()
        
        if is_business:
            comfort = comfort_business
            service = service_business
            service_details = service_details_business
        else:
            comfort = comfort_economy
            service = service_economy
            service_details = service_details_economy
        
        # Use legroom from SerpAPI as override for current cabin
        if facilities.seat_pitch_inches:
            comfort, _ = AircraftComfortService.calculate_comfort_score(
                aircraft_model=aircraft_model,
                cabin_class=cabin_class,
                has_wifi=facilities.has_wifi or False,
                has_power=facilities.has_power or False,
                has_ife=facilities.has_ife or False,
                legroom_override=facilities.seat_pitch_inches
            )
        
        # Value score - use price_insights if available
        price = flight_data.get("price", 0)
        value = self._calculate_value_score(price, price_insights)
        
        # Generate price insight detail for explanation
        price_insight_detail = self._get_price_insight_detail(price, price_insights)
        
        # Get flight metadata for scoring
        layovers = flight_data.get("layovers", [])
        stops = len(layovers)
        duration_minutes = flight_data.get("total_duration")
        
        # Default traveler type (can be passed from API in future)
        traveler_type = "default"
        
        # Calculate overall scores using ScoringService with 6 dimensions
        overall, score_details = ScoringService.calculate_overall_score(
            reliability=reliability,
            comfort=comfort,
            service=service,
            value=value,
            traveler_type=traveler_type,
            has_wifi=facilities.has_wifi or False,
            has_power=facilities.has_power or False,
            has_ife=facilities.has_ife or False,
            has_meal=facilities.meal_included or False,
            stops=stops,
            duration_minutes=duration_minutes,
            apply_boost=True
        )
        
        # Calculate for economy and business separately
        overall_economy, _ = ScoringService.calculate_overall_score(
            reliability=reliability,
            comfort=comfort_economy,
            service=service_economy,
            value=value,
            traveler_type=traveler_type,
            has_wifi=facilities.has_wifi or False,
            has_power=facilities.has_power or False,
            has_ife=facilities.has_ife or False,
            has_meal=facilities.meal_included or False,
            stops=stops,
            duration_minutes=duration_minutes,
            apply_boost=True
        )
        
        overall_business, _ = ScoringService.calculate_overall_score(
            reliability=reliability,
            comfort=comfort_business,
            service=service_business,
            value=value,
            traveler_type=traveler_type,
            has_wifi=True,  # Business usually has all amenities
            has_power=True,
            has_ife=True,
            has_meal=True,
            stops=stops,
            duration_minutes=duration_minutes,
            apply_boost=True
        )
        
        # Get persona label
        persona_label = ScoringService.get_persona_label(traveler_type)
        
        # Build highlights
        highlights = []
        if stops == 0:
            highlights.append("Direct flight")
        
        if comfort >= 8.0:
            highlights.append("Comfortable seating")
        
        if price_insights:
            price_level = price_insights.get("price_level")
            if price_level == "low":
                highlights.append("💰 Low price!")
        
        if airline_otp and airline_otp >= 85:
            highlights.append(f"{airline_otp:.0f}% on-time rate")
        
        if facilities.has_wifi:
            highlights.append("WiFi available")
        if facilities.has_power:
            highlights.append("Power outlets")
        if facilities.has_ife:
            highlights.append("In-flight entertainment")
        
        carbon_diff = carbon_data.get("difference_percent", 0)
        if carbon_diff < -5:
            highlights.append(f"{abs(carbon_diff)}% less emissions")
        
        if often_delayed:
            highlights.append("⚠️ Often delayed 30+ min")
        
        # Build explanations
        explanations = []
        
        # Reliability explanation
        if airline_otp:
            otp_detail = f"On-time performance: {airline_otp:.1f}%"
            if often_delayed:
                otp_detail += " (this flight often delayed 30+ min)"
        else:
            otp_detail = "On-time data not available for this airline"
        
        explanations.append(
            ScoreExplanation(
                dimension="reliability",
                title="Airline Reliability",
                detail=otp_detail,
                is_positive=reliability >= 7.5
            )
        )
        
        # Add comfort explanations from aircraft database
        comfort_explanations = AircraftComfortService.get_comfort_explanation(
            aircraft_model=aircraft_model,
            cabin_class=cabin_class,
            comfort_score=comfort
        )
        
        for exp in comfort_explanations:
            explanations.append(ScoreExplanation(
                dimension="comfort",
                title=exp["title"],
                detail=exp["detail"],
                is_positive=exp["is_positive"],
                cabin_class=cabin_class.lower() if "economy" in cabin_class.lower() else "business"
            ))
        
        # Add service explanations from airline reviews
        service_explanations = AirlineReviewsService.get_service_explanations(
            airline_name=airline,
            cabin_class=cabin_class,
            service_score=service
        )
        
        for exp in service_explanations:
            explanations.append(ScoreExplanation(
                dimension="service",
                title=exp["title"],
                detail=exp["detail"],
                is_positive=exp["is_positive"],
                cabin_class=cabin_class.lower() if "economy" in cabin_class.lower() else "business"
            ))
        
        explanations.append(
            ScoreExplanation(
                dimension="value",
                title="Value for Money",
                detail=price_insight_detail,
                is_positive=value >= 7.0
            )
        )
        
        # Build service highlights with cabin-specific information
        service_highlights = ServiceHighlights(
            highlights=service_details.get("highlights", []),
            economy_highlights=service_details_economy.get("highlights", []),
            business_highlights=service_details_business.get("highlights", []),
            food_rating=service_details.get("food_rating"),
            ground_service_rating=service_details.get("ground_service_rating"),
            seat_comfort_rating=service_details.get("seat_comfort_rating"),
            service_rating=service_details.get("service_rating"),
            recommendation_rate=service_details.get("recommendation_rate"),
            review_count=service_details.get("review_count", 0)
        )
        
        return FlightScore(
            overall_score=overall,
            dimensions=ScoreDimensions(
                reliability=round(reliability, 1),
                comfort=round(comfort, 1),
                service=round(service, 1),
                value=round(value, 1)
            ),
            economy_dimensions=ScoreDimensions(
                reliability=round(reliability, 1),
                comfort=round(comfort_economy, 1),
                service=round(service_economy, 1),
                value=round(value, 1)
            ),
            business_dimensions=ScoreDimensions(
                reliability=round(reliability, 1),
                comfort=round(comfort_business, 1),
                service=round(service_business, 1),
                value=round(value, 1)
            ),
            highlights=highlights[:5],
            explanations=explanations,
            service_highlights=service_highlights,
            user_reviews=user_reviews if user_reviews else None,
            persona_weights_applied=persona_label
        )
    
    def parse_price_insights(
        self,
        price_insights: Optional[Dict[str, Any]],
        flight_id: str
    ) -> Optional[PriceHistory]:
        """Parse price insights from SerpAPI response."""
        if not price_insights:
            return None
        
        current_price = price_insights.get("lowest_price", 0)
        price_level = price_insights.get("price_level", "typical")
        typical_range = price_insights.get("typical_price_range", [])
        history_data = price_insights.get("price_history", [])
        
        # Convert timestamp-based history to date-based
        points = []
        for item in history_data:
            if isinstance(item, list) and len(item) == 2:
                timestamp, price = item
                try:
                    date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
                    points.append(PricePoint(date=date_str, price=float(price)))
                except (ValueError, OSError):
                    continue
        
        # Determine trend
        if price_level == "low":
            trend = PriceTrend.FALLING
        elif price_level == "high":
            trend = PriceTrend.RISING
        else:
            trend = PriceTrend.STABLE
        
        return PriceHistory(
            flightId=flight_id,
            points=points[-30:] if points else [],  # Last 30 days
            currentPrice=float(current_price),
            trend=trend,
            priceLevel=price_level,
            typicalPriceRange=typical_range if typical_range else None,
            lowestPrice=float(current_price),
        )


# Airport code mapping for city names (extend as needed)
CITY_TO_AIRPORT_CODE = {
    # China
    "北京": "PEK",
    "beijing": "PEK",
    "上海": "SHA",
    "shanghai": "SHA",
    "广州": "CAN",
    "guangzhou": "CAN",
    "深圳": "SZX",
    "shenzhen": "SZX",
    "成都": "CTU",
    "chengdu": "CTU",
    "杭州": "HGH",
    "hangzhou": "HGH",
    "香港": "HKG",
    "hong kong": "HKG",
    # International
    "tokyo": "NRT",
    "东京": "NRT",
    "london": "LHR",
    "伦敦": "LHR",
    "paris": "CDG",
    "巴黎": "CDG",
    "new york": "JFK",
    "纽约": "JFK",
    "los angeles": "LAX",
    "洛杉矶": "LAX",
    "singapore": "SIN",
    "新加坡": "SIN",
    "seoul": "ICN",
    "首尔": "ICN",
    "sydney": "SYD",
    "悉尼": "SYD",
}


def get_airport_code(city_name: str) -> str:
    """Convert city name to airport code."""
    city_lower = city_name.lower().strip()
    
    # Check if already an airport code (3 letters)
    if len(city_name) == 3 and city_name.isupper():
        return city_name
    
    # Look up in mapping
    return CITY_TO_AIRPORT_CODE.get(city_lower, city_name.upper()[:3])


# Singleton instance
serpapi_flight_service = SerpAPIFlightService()
