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
    
    # Cache for storing flight results by ID (for detail page retrieval)
    # Format: { flight_id: FlightWithScore }
    _flight_cache: Dict[str, FlightWithScore] = {}
    
    def __init__(self):
        self.api_key = settings.serpapi_key
    
    # SerpAPI sort_by options
    SORT_BY_TOP_FLIGHTS = 1  # Google's default ranking
    SORT_BY_PRICE = 2        # Lowest price first
    SORT_BY_DEPARTURE = 3    # Departure time
    SORT_BY_ARRIVAL = 4      # Arrival time
    SORT_BY_DURATION = 5     # Shortest duration first
    SORT_BY_EMISSIONS = 6    # Lowest emissions first
    
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
        sort_by: Optional[int] = None,  # 1=Top, 2=Price, 3=Departure, 4=Arrival, 5=Duration, 6=Emissions
        traveler_type: str = "default",  # Used to determine optimal sort strategy
    ) -> Dict[str, Any]:
        """
        Search flights using SerpAPI Google Flights engine.
        
        The sort_by parameter is automatically optimized based on traveler_type:
        - student: sort_by=2 (Price) - Get cheapest flights first
        - business: sort_by=1 (Top flights) - Google considers reliability
        - family: sort_by=1 (Top flights) - Default ranking
        - default: sort_by=1 (Top flights)
        
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
        # Determine optimal sort_by based on traveler_type if not explicitly set
        if sort_by is None:
            if traveler_type == "student":
                # Students prioritize price - fetch cheapest flights first
                sort_by = self.SORT_BY_PRICE
            elif traveler_type == "business":
                # Business travelers care about schedule/reliability - use Google's top ranking
                sort_by = self.SORT_BY_TOP_FLIGHTS
            elif traveler_type == "family":
                # Families value comfort - use Google's top ranking (considers amenities)
                sort_by = self.SORT_BY_TOP_FLIGHTS
            else:
                # Default: use Google's top flights ranking
                sort_by = self.SORT_BY_TOP_FLIGHTS
        
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
            "sort_by": sort_by,  # Add sort_by to API call
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
        cabin_filter: str = "economy",
        traveler_type: str = "default"
    ) -> tuple[List[FlightWithScore], Optional[Dict[str, Any]]]:
        """
        Parse SerpAPI response into FlightWithScore objects.
        
        Args:
            serpapi_response: Raw response from SerpAPI
            cabin_filter: Cabin class filter (economy/business/first)
            traveler_type: Traveler persona for personalized scoring (student/business/family/default)
        
        Returns:
            Tuple of (list of FlightWithScore, price_insights dict)
        """
        flights_list: List[FlightWithScore] = []
        
        # Combine best_flights and other_flights
        best_flights = serpapi_response.get("best_flights", [])
        other_flights = serpapi_response.get("other_flights", [])
        all_flights = best_flights + other_flights
        
        price_insights = serpapi_response.get("price_insights")
        
        # FIRST PASS: Parse all flights and collect durations
        parsed_flights_data = []
        for idx, flight_data in enumerate(all_flights):
            try:
                parsed_flight = self._parse_single_flight(
                    flight_data, idx, cabin_filter, price_insights, traveler_type
                )
                if parsed_flight:
                    parsed_flights_data.append((parsed_flight, flight_data))
            except Exception as e:
                print(f"Error parsing flight {idx}: {e}")
                continue
        
        # Find the SHORTEST flight duration for this route
        # This will be used as the baseline (10/10) for efficiency scoring
        shortest_duration = None
        if parsed_flights_data:
            durations = [fws.flight.duration_minutes for fws, _ in parsed_flights_data if fws.flight.duration_minutes]
            if durations:
                shortest_duration = min(durations)
        
        # SECOND PASS: Recalculate scores with shortest_duration baseline
        for fws, flight_data in parsed_flights_data:
            # Recalculate the score with shortest_duration for proper efficiency scoring
            recalculated_score = self._generate_score_from_serpapi(
                flight_data=flight_data,
                facilities=fws.facilities,
                carbon_data=fws.flight.carbon_emissions or {},
                first_segment=flight_data.get("flights", [{}])[0],
                price_insights=price_insights,
                aircraft_model=fws.flight.aircraft_model,
                cabin_class=cabin_filter,
                airline_name=fws.flight.airline,
                traveler_type=traveler_type,
                shortest_duration=shortest_duration  # NEW: Pass shortest duration
            )
            # Update the score
            fws.score = recalculated_score
            flights_list.append(fws)
        
        # SMART SORTING based on traveler type:
        # - Students: Sort by PRICE (ascending) - cheapest flights first!
        #   SerpAPI already fetched by price, but we ensure consistent ordering
        # - Business: Sort by OVERALL SCORE - best reliable/service flights first
        # - Family: Sort by OVERALL SCORE - best comfort/service flights first
        # - Default: Sort by OVERALL SCORE
        if flights_list:
            if traveler_type == "student":
                # Students want cheapest flights first - sort by price ascending
                flights_list.sort(key=lambda x: x.flight.price)
            else:
                # Business, Family, Default: sort by weighted overall score descending
                flights_list.sort(key=lambda x: x.score.overall_score, reverse=True)
        
        # Cache all flights for later retrieval by ID (for detail page)
        for fws in flights_list:
            self._flight_cache[fws.flight.id] = fws
        
        return flights_list, price_insights
    
    async def search_return_flights(
        self,
        departure_id: str,
        arrival_id: str,
        outbound_date: str,
        return_date: str,
        departure_token: str,
        travel_class: int = 1,
        adults: int = 1,
        currency: str = "USD",
        traveler_type: str = "default"
    ) -> List[FlightWithScore]:
        """
        Search for return flights using a departure_token.
        This is the second step of a round trip booking.
        
        Args:
            departure_token: Token from the selected outbound flight
            Other params: Same as original search for context
        
        Returns:
            List of return flight options with combined round trip prices
        """
        params = {
            "engine": "google_flights",
            "api_key": self.api_key,
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": outbound_date,
            "return_date": return_date,
            "type": "1",  # Round trip
            "currency": currency,
            "hl": "en",
            "gl": "us",
            "departure_token": departure_token,
        }
        
        if travel_class:
            params["travel_class"] = travel_class
        if adults > 1:
            params["adults"] = adults
        
        async with httpx.AsyncClient() as client:
            response = await client.get(self.BASE_URL, params=params, timeout=30.0)
            data = response.json()
        
        # Determine cabin filter
        cabin_map = {1: "economy", 2: "premium economy", 3: "business", 4: "first"}
        cabin_filter = cabin_map.get(travel_class, "economy")
        
        return_flights = []
        
        # Parse best_flights and other_flights from return response
        for flight_list_key in ["best_flights", "other_flights"]:
            for idx, flight_data in enumerate(data.get(flight_list_key, [])):
                fws = self._parse_single_flight(
                    flight_data, 
                    idx, 
                    cabin_filter,
                    traveler_type=traveler_type
                )
                if fws:
                    # Mark as return flight
                    return_flights.append(fws)
        
        # Cache return flights
        for fws in return_flights:
            self._flight_cache[fws.flight.id] = fws
        
        return return_flights
    
    def get_flight_detail(self, flight_id: str) -> Optional[FlightDetail]:
        """
        Get flight detail from cache.
        The flight must have been searched recently to be in cache.
        """
        fws = self._flight_cache.get(flight_id)
        if not fws:
            return None
        
        # Generate price history for the flight
        price_history = self._generate_price_history(fws.flight)
        
        return FlightDetail(
            flight=fws.flight,
            score=fws.score,
            facilities=fws.facilities,
            priceHistory=price_history
        )
    
    def _generate_price_history(self, flight: Flight) -> PriceHistory:
        """Generate synthetic price history based on current price."""
        from datetime import timedelta
        import random
        
        base_price = flight.price
        today = datetime.now()
        
        # Generate 7 days of price history with small variations
        points = []
        for i in range(7, 0, -1):
            date = today - timedelta(days=i)
            # Random variation of -5% to +8%
            variation = random.uniform(-0.05, 0.08)
            price = base_price * (1 + variation)
            points.append(PricePoint(
                date=date.strftime("%Y-%m-%d"),
                price=round(price)
            ))
        
        # Add today's price
        points.append(PricePoint(
            date=today.strftime("%Y-%m-%d"),
            price=base_price
        ))
        
        # Determine trend based on price movement
        if len(points) >= 2:
            first_price = points[0].price
            last_price = points[-1].price
            change_pct = ((last_price - first_price) / first_price) * 100
            
            if change_pct < -3:
                trend = PriceTrend.FALLING
            elif change_pct > 3:
                trend = PriceTrend.RISING
            else:
                trend = PriceTrend.STABLE
        else:
            trend = PriceTrend.STABLE
        
        return PriceHistory(
            flightId=flight.id,
            points=points,
            currentPrice=base_price,
            trend=trend
        )
    
    def _parse_single_flight(
        self,
        flight_data: Dict[str, Any],
        index: int,
        cabin_filter: str,
        price_insights: Optional[Dict[str, Any]] = None,
        traveler_type: str = "default"
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
            departure_token=flight_data.get("departure_token"),  # For round trip return flights
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
        # Pass traveler_type for personalized scoring weights
        score = self._generate_score_from_serpapi(
            flight_data, facilities, carbon_data, first_segment, price_insights,
            aircraft_model=airplane, cabin_class=travel_class, airline_name=airline,
            traveler_type=traveler_type
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
        """Parse amenities from SerpAPI extensions list.
        
        IMPORTANT: SerpAPI data takes priority over database defaults.
        If an amenity is not mentioned in extensions, we set it to False (not available).
        """
        
        has_wifi = False
        wifi_free = False
        has_power = False
        has_ife = False
        ife_type = None
        meal_included = False  # Default to False unless SerpAPI says otherwise
        meal_type = None
        
        # Join extensions for easier searching
        ext_lower = [e.lower() for e in extensions]
        ext_joined = " ".join(ext_lower)
        
        # Check for WiFi
        if "wi-fi" in ext_joined or "wifi" in ext_joined:
            has_wifi = True
            if "free wi-fi" in ext_joined or "free wifi" in ext_joined:
                wifi_free = True
        
        # Check for power
        if "power" in ext_joined or "usb" in ext_joined or "outlet" in ext_joined:
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
            else:
                ife_type = "In-flight entertainment"
        
        # Check for meals - SerpAPI may include meal info in extensions
        if "meal" in ext_joined or "food" in ext_joined or "dinner" in ext_joined or "lunch" in ext_joined or "breakfast" in ext_joined:
            meal_included = True
            if "hot meal" in ext_joined:
                meal_type = "Hot meal"
            elif "snack" in ext_joined:
                meal_type = "Snacks"
            else:
                meal_type = "Meal included"
        elif "snack" in ext_joined:
            meal_included = True
            meal_type = "Snacks"
        
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
            meal_type=meal_type,
            wifi_free=wifi_free,  # Add wifi_free to track if free
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
        airline_name: str = None,
        traveler_type: str = "default",
        shortest_duration: Optional[int] = None  # NEW: Shortest flight time for this route
    ) -> FlightScore:
        """
        Generate flight score based on SerpAPI data, aircraft comfort database, and airline reviews.
        
        Args:
            traveler_type: Traveler persona for personalized scoring weights.
                - "student": Prioritizes value (35%) and efficiency (15%)
                - "business": Prioritizes reliability (30%) and service (20%)
                - "family": Prioritizes comfort (25%) and service (25%)
                - "default": Balanced weights across all dimensions
            shortest_duration: Shortest flight duration for this route in minutes.
                Used as baseline (10/10) for efficiency scoring.
        """
        
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
        # Use SerpAPI data for amenities - don't assume business class has everything
        comfort_business, comfort_details_business = AircraftComfortService.calculate_comfort_score(
            aircraft_model=aircraft_model,
            cabin_class="business",
            has_wifi=facilities.has_wifi or False,  # Use actual SerpAPI data
            has_power=facilities.has_power or False,  # Use actual SerpAPI data
            has_ife=facilities.has_ife or False,  # Use actual SerpAPI data
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
        
        # User reviews are NOT fetched during initial parsing for performance
        # They will be fetched on-demand when user selects a specific flight
        # This saves ~38ms per flight (2.8-4s total for 74 flights)
        user_reviews = []
        
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
        
        # Use traveler_type from parameter for personalized scoring
        # (no longer hardcoded to "default")
        
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
            shortest_duration=shortest_duration,  # Pass shortest duration for efficiency calculation
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
            shortest_duration=shortest_duration,  # Pass shortest duration for efficiency calculation
            apply_boost=True
        )
        
        overall_business, _ = ScoringService.calculate_overall_score(
            reliability=reliability,
            comfort=comfort_business,
            service=service_business,
            value=value,
            traveler_type=traveler_type,
            has_wifi=facilities.has_wifi or False,  # Use actual SerpAPI data
            has_power=facilities.has_power or False,  # Use actual SerpAPI data
            has_ife=facilities.has_ife or False,  # Use actual SerpAPI data
            has_meal=facilities.meal_included or False,  # Use actual SerpAPI data
            stops=stops,
            duration_minutes=duration_minutes,
            shortest_duration=shortest_duration,  # Pass shortest duration for efficiency calculation
            apply_boost=True
        )
        
        # Get persona label
        persona_label = ScoringService.get_persona_label(traveler_type)
        
        # Build highlights
        # IMPORTANT: If often_delayed is True from SerpAPI, do NOT show on-time highlights
        # SerpAPI "often_delayed" is highly reliable data from Google Flights and takes priority
        highlights = []
        if stops == 0:
            highlights.append("Direct flight")
        
        if comfort >= 8.0:
            highlights.append("Comfortable seating")
        
        if price_insights:
            price_level = price_insights.get("price_level")
            if price_level == "low":
                highlights.append("💰 Low price!")
        
        # ONLY show on-time rate if flight is NOT often delayed
        # SerpAPI often_delayed flag overrides airline OTP data
        if airline_otp and airline_otp >= 85 and not often_delayed:
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
        
        # Add delay warning PROMINENTLY for often delayed flights
        if often_delayed:
            # Insert at beginning to make it visible
            highlights.insert(0, "⚠️ Often delayed 30+ min")
        
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


# ============================================================
# Autocomplete Service
# ============================================================

class SerpAPIAutocompleteService:
    """
    SerpAPI Google Flights Autocomplete Service
    
    Provides location suggestions as users type, returning:
    - Cities with their airports
    - Regions (countries, areas)
    - Airport details with IATA codes
    
    API Docs: https://serpapi.com/google-flights-autocomplete-api
    """
    
    BASE_URL = "https://serpapi.com/search"
    
    def __init__(self):
        self.api_key = settings.serpapi_key
    
    async def get_suggestions(
        self,
        query: str,
        gl: str = "us",
        hl: str = "en",
        exclude_regions: bool = False
    ) -> Dict[str, Any]:
        """
        Get location suggestions for a search query.
        
        Args:
            query: Search text (e.g., "New", "Korea", "北京")
            gl: Country code for localization (e.g., "us", "cn", "hk")
            hl: Language code (e.g., "en", "zh-CN", "zh-TW")
            exclude_regions: If True, exclude region-level locations (countries, areas)
                           Only return cities with airports
        
        Returns:
            Dict containing suggestions with:
            - position: Ranking position
            - name: Location name
            - type: "city" or "region"
            - description: Brief description
            - id: Google Knowledge Graph ID
            - airports: List of airports (for cities)
              - name: Airport name
              - id: IATA code
              - city: City name
              - distance: Distance from city center
        
        Example Response:
        {
            "suggestions": [
                {
                    "position": 1,
                    "name": "Seoul, South Korea",
                    "type": "city",
                    "description": "Capital of South Korea",
                    "id": "/m/0hsqf",
                    "airports": [
                        {"name": "Incheon International Airport", "id": "ICN", ...},
                        {"name": "Gimpo International Airport", "id": "GMP", ...}
                    ]
                }
            ]
        }
        """
        if not self.api_key:
            raise ValueError("SERPAPI_KEY not configured")
        
        params = {
            "engine": "google_flights_autocomplete",
            "q": query,
            "gl": gl,
            "hl": hl,
            "api_key": self.api_key,
        }
        
        if exclude_regions:
            params["exclude_regions"] = "true"
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            return response.json()
    
    def parse_suggestions(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse autocomplete response into a clean list of suggestions.
        
        Returns a list of suggestion objects with normalized structure.
        """
        suggestions = response.get("suggestions", [])
        parsed = []
        
        for suggestion in suggestions:
            parsed_item = {
                "position": suggestion.get("position"),
                "name": suggestion.get("name"),
                "type": suggestion.get("type"),  # "city" or "region"
                "description": suggestion.get("description"),
                "id": suggestion.get("id"),  # Google Knowledge Graph ID
            }
            
            # Add airports if available (cities have airports, regions don't)
            airports = suggestion.get("airports", [])
            if airports:
                parsed_item["airports"] = [
                    {
                        "name": airport.get("name"),
                        "code": airport.get("id"),  # IATA code
                        "city": airport.get("city"),
                        "cityId": airport.get("city_id"),
                        "distance": airport.get("distance"),
                    }
                    for airport in airports
                ]
            
            parsed.append(parsed_item)
        
        return parsed


# ============================================================
# Price Insights Service
# ============================================================

class SerpAPIPriceInsightsService:
    """
    SerpAPI Google Flights Price Insights Service
    
    Provides price analysis for flight routes:
    - Lowest available price
    - Price level (low/typical/high)
    - Typical price range
    - Historical price data
    
    API Docs: https://serpapi.com/google-flights-price-insights
    
    Note: Price insights are returned as part of the regular Google Flights
    search response. This service extracts and provides dedicated access
    to that data.
    """
    
    BASE_URL = "https://serpapi.com/search"
    
    def __init__(self):
        self.api_key = settings.serpapi_key
    
    async def get_price_insights(
        self,
        departure_id: str,
        arrival_id: str,
        outbound_date: str,
        return_date: Optional[str] = None,
        currency: str = "USD",
        hl: str = "en",
        gl: str = "us",
        travel_class: int = 1,
        adults: int = 1
    ) -> Dict[str, Any]:
        """
        Get price insights for a flight route.
        
        Args:
            departure_id: Departure airport IATA code (e.g., "JFK", "HKG")
            arrival_id: Arrival airport IATA code (e.g., "LAX", "NRT")
            outbound_date: Departure date (YYYY-MM-DD)
            return_date: Return date for round trips (YYYY-MM-DD, optional)
            currency: Currency code (e.g., "USD", "EUR", "CNY")
            hl: Language code
            gl: Country code
            travel_class: 1=Economy, 2=Premium Economy, 3=Business, 4=First
            adults: Number of passengers
        
        Returns:
            Price insights data:
            {
                "lowest_price": 450,
                "price_level": "typical",  // "low", "typical", "high"
                "typical_price_range": [400, 600],
                "price_history": [
                    [1691013600, 575],  // [timestamp, price]
                    [1691100000, 590],
                    ...
                ]
            }
        """
        if not self.api_key:
            raise ValueError("SERPAPI_KEY not configured")
        
        params = {
            "engine": "google_flights",
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": outbound_date,
            "currency": currency,
            "hl": hl,
            "gl": gl,
            "travel_class": travel_class,
            "adults": adults,
            "api_key": self.api_key,
        }
        
        # Set trip type
        if return_date:
            params["type"] = "1"  # Round trip
            params["return_date"] = return_date
        else:
            params["type"] = "2"  # One way
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
        
        # Extract price_insights from the response
        price_insights = data.get("price_insights", {})
        
        return {
            "route": {
                "departure": departure_id,
                "arrival": arrival_id,
                "outbound_date": outbound_date,
                "return_date": return_date,
            },
            "price_insights": price_insights,
            "search_metadata": data.get("search_metadata", {}),
        }
    
    def parse_price_insights(self, price_insights: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse raw price insights into a user-friendly format.
        
        Returns:
            {
                "lowestPrice": 450,
                "priceLevel": "typical",
                "priceLevelDescription": "Prices are typical for this route",
                "typicalPriceRange": {"low": 400, "high": 600},
                "priceHistory": [
                    {"date": "2024-08-03", "price": 575},
                    ...
                ]
            }
        """
        if not price_insights:
            return None
        
        # Parse price level description
        price_level = price_insights.get("price_level", "unknown")
        level_descriptions = {
            "low": "Prices are lower than usual for this route",
            "typical": "Prices are typical for this route",
            "high": "Prices are higher than usual for this route",
        }
        
        # Parse typical price range
        typical_range = price_insights.get("typical_price_range", [])
        range_obj = None
        if len(typical_range) >= 2:
            range_obj = {
                "low": typical_range[0],
                "high": typical_range[1],
            }
        
        # Parse price history (convert timestamps to dates)
        raw_history = price_insights.get("price_history", [])
        parsed_history = []
        for entry in raw_history:
            if len(entry) >= 2:
                timestamp, price = entry[0], entry[1]
                try:
                    date_obj = datetime.fromtimestamp(timestamp)
                    parsed_history.append({
                        "date": date_obj.strftime("%Y-%m-%d"),
                        "price": price,
                    })
                except (ValueError, OSError):
                    continue
        
        return {
            "lowestPrice": price_insights.get("lowest_price"),
            "priceLevel": price_level,
            "priceLevelDescription": level_descriptions.get(price_level, "Price level unknown"),
            "typicalPriceRange": range_obj,
            "priceHistory": parsed_history,
        }


# Singleton instances
serpapi_flight_service = SerpAPIFlightService()
serpapi_autocomplete_service = SerpAPIAutocompleteService()
serpapi_price_insights_service = SerpAPIPriceInsightsService()
