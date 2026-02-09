"""
AirEase Backend - Amadeus SeatMap Display API Service
Fetches seat map data on-demand when user views flight details.

Flow:
1. Authenticate with Amadeus OAuth2 (client_credentials)
2. Search Flight Offers to get a valid flight-offer object
3. POST flight-offer to /v1/shopping/seatmaps to get cabin layout
4. Parse response into simplified seatmap data for frontend

API Docs: https://developers.amadeus.com/self-service/category/air/api-doc/seatmap-display
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class AmadeusSeatmapService:
    """
    Service to fetch seat maps from Amadeus SeatMap Display API v1.
    
    Uses the POST method which accepts a flight offer body.
    The flow:
    1. Get OAuth2 token
    2. Search for a flight offer matching the cached flight data
    3. POST that offer to /v1/shopping/seatmaps
    4. Return parsed seat map data
    """
    
    def __init__(self):
        self.base_url = settings.amadeus_base_url
        self.api_key = settings.amadeus_api_key
        self.api_secret = settings.amadeus_api_secret
        self.access_token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def _get_access_token(self) -> str:
        """Get OAuth2 access token via client_credentials grant."""
        # Return cached token if still valid
        if self.access_token and self.token_expires and datetime.now() < self.token_expires:
            return self.access_token
        
        auth_url = f"{self.base_url}/v1/security/oauth2/token"
        
        try:
            response = await self.client.post(
                auth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.api_key,
                    "client_secret": self.api_secret
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code != 200:
                logger.error(f"Amadeus auth failed [{response.status_code}]: {response.text}")
                raise Exception(f"Amadeus authentication failed: {response.status_code}")
            
            data = response.json()
            self.access_token = data["access_token"]
            # Refresh 60 seconds before expiry
            self.token_expires = datetime.now() + timedelta(seconds=data.get("expires_in", 1799) - 60)
            
            logger.info("Amadeus OAuth2 token obtained successfully")
            return self.access_token
            
        except httpx.RequestError as e:
            logger.error(f"Amadeus auth request error: {e}")
            raise Exception(f"Failed to connect to Amadeus API: {e}")
    
    async def _search_flight_offer(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        carrier_code: str,
        flight_number: str,
        cabin: str = "ECONOMY"
    ) -> Optional[Dict[str, Any]]:
        """
        Step 1: Search for a flight offer using Amadeus Flight Offers Search API.
        We need a valid flight-offer object to pass to the SeatMap API.
        
        Args:
            origin: Departure IATA airport code (e.g., "HKG")
            destination: Arrival IATA airport code (e.g., "NRT")
            departure_date: Date in YYYY-MM-DD format
            carrier_code: 2-letter IATA airline code (e.g., "CX")
            flight_number: Flight number without carrier (e.g., "520")
            cabin: Cabin class (ECONOMY, BUSINESS, FIRST, PREMIUM_ECONOMY)
        
        Returns:
            A flight-offer dict from Amadeus, or None if not found
        """
        token = await self._get_access_token()
        
        search_url = f"{self.base_url}/v2/shopping/flight-offers"
        
        # Map cabin to Amadeus format
        cabin_map = {
            "economy": "ECONOMY",
            "business": "BUSINESS",
            "first": "FIRST",
            "premium": "PREMIUM_ECONOMY",
            "premium economy": "PREMIUM_ECONOMY",
        }
        travel_class = cabin_map.get(cabin.lower(), "ECONOMY") if cabin else "ECONOMY"
        
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date,
            "adults": 1,
            "travelClass": travel_class,
            "includedAirlineCodes": carrier_code,
            "max": 10,
        }
        
        try:
            response = await self.client.get(
                search_url,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                }
            )
            
            if response.status_code != 200:
                logger.warning(f"Flight offer search failed [{response.status_code}]: {response.text[:500]}")
                return None
            
            data = response.json()
            offers = data.get("data", [])
            dictionaries = data.get("dictionaries", {})
            
            if not offers:
                logger.info(f"No flight offers found for {carrier_code}{flight_number} on {departure_date}")
                return None
            
            # Try to find the exact matching flight by number
            # The flight number in the segment is just the numeric part
            numeric_flight_num = ''.join(filter(str.isdigit, flight_number))
            
            for offer in offers:
                for itinerary in offer.get("itineraries", []):
                    for segment in itinerary.get("segments", []):
                        seg_carrier = segment.get("carrierCode", "")
                        seg_number = segment.get("number", "")
                        if seg_carrier == carrier_code and seg_number == numeric_flight_num:
                            # Found the matching flight - return full response structure
                            return {
                                "offer": offer,
                                "dictionaries": dictionaries
                            }
            
            # If exact match not found, return the first offer
            # The seatmap will still be for the correct aircraft/route
            logger.info(f"Exact flight {carrier_code}{flight_number} not found, using first offer")
            return {
                "offer": offers[0],
                "dictionaries": dictionaries
            }
            
        except httpx.RequestError as e:
            logger.error(f"Flight offer search request error: {e}")
            return None
    
    async def get_seatmap(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        carrier_code: str,
        flight_number: str,
        cabin: str = "ECONOMY"
    ) -> Optional[Dict[str, Any]]:
        """
        Main method: Get seat map for a specific flight.
        
        Steps:
        1. Search for flight offer via Flight Offers Search
        2. POST the offer to SeatMap Display API
        3. Parse and return simplified seatmap data
        
        Args:
            origin: Departure IATA airport code
            destination: Arrival IATA airport code
            departure_date: Date in YYYY-MM-DD format
            carrier_code: 2-letter IATA airline code
            flight_number: Flight number (with or without carrier prefix)
            cabin: Cabin class string
        
        Returns:
            Parsed seatmap data dict, or None on failure
        """
        if not self.api_key or not self.api_secret or self.api_secret == "PLACEHOLDER_SECRET":
            logger.warning("Amadeus API credentials not configured properly")
            return None
        
        # Step 1: Get a valid flight offer
        offer_data = await self._search_flight_offer(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            carrier_code=carrier_code,
            flight_number=flight_number,
            cabin=cabin
        )
        
        if not offer_data:
            logger.info(f"Could not find flight offer for seatmap: {carrier_code}{flight_number}")
            return None
        
        # Step 2: POST the offer to SeatMap API
        token = await self._get_access_token()
        seatmap_url = f"{self.base_url}/v1/shopping/seatmaps"
        
        # Build request body - the SeatMap API expects the full flight offer
        request_body = {
            "data": [offer_data["offer"]]
        }
        
        try:
            response = await self.client.post(
                seatmap_url,
                json=request_body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-HTTP-Method-Override": "GET"
                }
            )
            
            if response.status_code != 200:
                logger.warning(f"SeatMap API failed [{response.status_code}]: {response.text[:500]}")
                return None
            
            seatmap_data = response.json()
            
            # Step 3: Parse the seatmap response
            return self._parse_seatmap_response(seatmap_data)
            
        except httpx.RequestError as e:
            logger.error(f"SeatMap API request error: {e}")
            return None
    
    def _parse_seatmap_response(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the Amadeus SeatMap response into a simplified format for the frontend.
        
        The raw response contains:
        - data[]: array of SeatMap objects
          - decks[]: array of Deck objects
            - deckConfiguration: width, length, start/end rows, wing positions
            - seats[]: array of Seat objects with coordinates, characteristics, pricing
            - facilities[]: lavatories, galleys, closets, exits
          - aircraftCabinAmenities: power, seat/legSpace, wifi, entertainment, food
          - dictionaries: seat characteristics codes mapping
        
        Returns simplified data for rendering a visual seat map.
        """
        seatmaps = raw_data.get("data", [])
        dictionaries = raw_data.get("dictionaries", {})
        
        if not seatmaps:
            return None
        
        result = {
            "segments": []
        }
        
        # Seat characteristics code mapping (from Amadeus dictionaries or defaults)
        seat_chars = dictionaries.get("seatCharacteristics", {})
        facility_map = dictionaries.get("facility", {})
        
        for seatmap in seatmaps:
            segment_info = {
                "segmentId": seatmap.get("id"),
                "departure": seatmap.get("departure", {}),
                "arrival": seatmap.get("arrival", {}),
                "carrierCode": seatmap.get("carrierCode"),
                "number": seatmap.get("number"),
                "aircraft": seatmap.get("aircraft", {}),
                "classOfService": seatmap.get("classOfService"),
                "amenities": self._parse_amenities(seatmap.get("aircraftCabinAmenities", {})),
                "decks": []
            }
            
            for deck in seatmap.get("decks", []):
                deck_config = deck.get("deckConfiguration", {})
                
                parsed_deck = {
                    "deckType": deck.get("deckType", "MAIN"),
                    "configuration": {
                        "width": deck_config.get("width"),
                        "length": deck_config.get("length"),
                        "startSeatRow": deck_config.get("startSeatRow"),
                        "endSeatRow": deck_config.get("endSeatRow"),
                        "startWingsRow": deck_config.get("startWingsX"),
                        "endWingsRow": deck_config.get("endWingsX"),
                        "exitRowsX": deck_config.get("exitRowsX", []),
                    },
                    "seats": [],
                    "facilities": [],
                }
                
                # Parse seats
                for seat in deck.get("seats", []):
                    char_codes = seat.get("characteristicsCodes", [])
                    
                    # Resolve characteristic codes to descriptions
                    characteristics = []
                    is_exit_row = False
                    has_extra_legroom = False
                    is_window = False
                    is_aisle = False
                    is_middle = False
                    
                    for code in char_codes:
                        desc = seat_chars.get(code, code)
                        characteristics.append({"code": code, "description": desc})
                        
                        code_upper = code.upper()
                        if code_upper in ("E", "EX"):
                            is_exit_row = True
                        if code_upper in ("L", "LEG", "LS"):
                            has_extra_legroom = True
                        if code_upper == "W":
                            is_window = True
                        if code_upper == "A":
                            is_aisle = True
                        if code_upper in ("M", "MA"):
                            is_middle = True
                    
                    # Parse traveler pricing / availability
                    traveler_pricing = seat.get("travelerPricing", [])
                    availability = "UNKNOWN"
                    price = None
                    currency = None
                    
                    if traveler_pricing:
                        first_pricing = traveler_pricing[0]
                        availability = first_pricing.get("seatAvailabilityStatus", "UNKNOWN")
                        price_info = first_pricing.get("price", {})
                        if price_info:
                            price = price_info.get("total")
                            currency = price_info.get("currency")
                    
                    parsed_seat = {
                        "number": seat.get("number"),
                        "cabin": seat.get("cabin"),
                        "coordinates": seat.get("coordinates", {}),
                        "availability": availability,  # AVAILABLE, BLOCKED, OCCUPIED
                        "characteristics": characteristics,
                        "isExitRow": is_exit_row,
                        "hasExtraLegroom": has_extra_legroom,
                        "isWindow": is_window,
                        "isAisle": is_aisle,
                        "isMiddle": is_middle,
                        "price": price,
                        "currency": currency,
                    }
                    
                    parsed_deck["seats"].append(parsed_seat)
                
                # Parse facilities (lavatories, galleys, exits, closets)
                for facility in deck.get("facilities", []):
                    parsed_facility = {
                        "code": facility.get("code"),
                        "type": facility_map.get(facility.get("code"), facility.get("code")),
                        "coordinates": facility.get("coordinates", {}),
                        "column": facility.get("column"),
                        "row": facility.get("row"),
                    }
                    parsed_deck["facilities"].append(parsed_facility)
                
                segment_info["decks"].append(parsed_deck)
            
            result["segments"].append(segment_info)
        
        # Add dictionaries for reference
        result["dictionaries"] = {
            "seatCharacteristics": seat_chars,
            "facilities": facility_map,
        }
        
        return result
    
    def _parse_amenities(self, amenities_raw: Dict[str, Any]) -> Dict[str, Any]:
        """Parse aircraftCabinAmenities into a cleaner format."""
        if not amenities_raw:
            return {}
        
        result = {}
        
        # Power
        power = amenities_raw.get("power", {})
        if power:
            result["power"] = {
                "isChargeable": power.get("isChargeable"),
                "powerType": power.get("powerType"),
                "usbType": power.get("usbType"),
            }
        
        # Seat / Legroom
        seat = amenities_raw.get("seat", {})
        if seat:
            leg_space = seat.get("legSpace")
            # Amadeus uses "spaceUnit" not "legSpaceUnit"
            space_unit = seat.get("spaceUnit", "")
            # Convert to display-friendly unit
            if space_unit == "INCHES":
                unit_display = "in"
            elif space_unit == "CENTIMETERS":
                unit_display = "cm"
            else:
                unit_display = space_unit.lower() if space_unit else "in"
            
            result["seat"] = {
                "legSpace": leg_space,  # in inches or cm
                "legSpaceUnit": unit_display,
                "tilt": seat.get("tilt"),  # FULL_FLAT, ANGLE_FLAT, NORMAL
                "amenityType": seat.get("amenityType"),
                "medianLegSpace": seat.get("medianLegSpace"),
            }
        
        # WiFi
        wifi = amenities_raw.get("wifi", {})
        if wifi:
            result["wifi"] = {
                "isChargeable": wifi.get("isChargeable"),
                "wifiCoverage": wifi.get("wifiCoverage"),  # FULL, PARTIAL
            }
        
        # Entertainment
        entertainment = amenities_raw.get("entertainment", [])
        if entertainment:
            result["entertainment"] = entertainment
        
        # Food
        food = amenities_raw.get("food", {})
        if food:
            result["food"] = food
        
        # Beverage
        beverage = amenities_raw.get("beverage", {})
        if beverage:
            result["beverage"] = beverage
        
        return result
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
amadeus_seatmap_service = AmadeusSeatmapService()
