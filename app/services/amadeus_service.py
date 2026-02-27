"""
AirEase Backend - Amadeus Flight API Service
真实航班数据服务（Amadeus API）
"""

import httpx
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple

from app.config import settings
from app.models import (
    Flight, FlightScore, FlightFacilities, FlightWithScore,
    FlightDetail, PriceHistory, ScoreDimensions, ScoreExplanation
)
from app.services.aircraft_comfort_service import AircraftComfortService


class AmadeusService:
    """
    Amadeus Flight API 服务
    
    文档: https://developers.amadeus.com/
    需要配置 AMADEUS_API_KEY 和 AMADEUS_API_SECRET
    """
    
    def __init__(self):
        self.base_url = settings.amadeus_base_url
        self.api_key = settings.amadeus_api_key
        self.api_secret = settings.amadeus_api_secret
        self.access_token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self.client = httpx.AsyncClient(timeout=30.0)
        # Cache for availability data: key = "origin-dest-date-cabin" -> (timestamp, data)
        self._availability_cache: Dict[str, Tuple[datetime, Dict[str, int]]] = {}
        self._cache_ttl = timedelta(minutes=30)
    
    async def _get_access_token(self) -> str:
        """获取OAuth2 Access Token"""
        if self.access_token and self.token_expires and datetime.now() < self.token_expires:
            return self.access_token
        
        auth_url = f"{self.base_url}/v1/security/oauth2/token"
        
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
            raise Exception(f"Amadeus auth failed: {response.text}")
        
        data = response.json()
        self.access_token = data["access_token"]
        self.token_expires = datetime.now() + timedelta(seconds=data["expires_in"] - 60)
        
        return self.access_token
    
    async def search_flights(
        self,
        from_city: str,
        to_city: str,
        date: str,
        cabin: str = "ECONOMY"
    ) -> List[FlightWithScore]:
        """
        搜索航班
        
        使用 Amadeus Flight Offers Search API
        """
        token = await self._get_access_token()
        
        # 城市代码映射
        city_codes = {
            "北京": "PEK", "上海": "SHA", "广州": "CAN",
            "深圳": "SZX", "成都": "CTU", "杭州": "HGH",
            "武汉": "WUH", "西安": "XIY", "南京": "NKG"
        }
        
        origin = city_codes.get(from_city, from_city)
        destination = city_codes.get(to_city, to_city)
        
        cabin_map = {
            "economy": "ECONOMY", "经济舱": "ECONOMY",
            "business": "BUSINESS", "公务舱": "BUSINESS",
            "first": "FIRST", "头等舱": "FIRST"
        }
        travel_class = cabin_map.get(cabin.lower(), "ECONOMY")
        
        search_url = f"{self.base_url}/v2/shopping/flight-offers"
        
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": date,
            "adults": 1,
            "travelClass": travel_class,
            "currencyCode": "CNY",
            "max": 20
        }
        
        response = await self.client.get(
            search_url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }
        )
        
        if response.status_code != 200:
            print(f"Amadeus search error: {response.text}")
            return []
        
        data = response.json()
        return self._transform_amadeus_response(data, from_city, to_city, cabin)
    
    def _transform_amadeus_response(
        self,
        data: Dict[str, Any],
        from_city: str,
        to_city: str,
        cabin: str
    ) -> List[FlightWithScore]:
        """转换Amadeus响应为内部格式"""
        results = []
        
        for i, offer in enumerate(data.get("data", [])):
            try:
                segment = offer["itineraries"][0]["segments"][0]
                price = float(offer["price"]["total"])
                
                departure_dt = datetime.fromisoformat(segment["departure"]["at"].replace("Z", "+00:00"))
                arrival_dt = datetime.fromisoformat(segment["arrival"]["at"].replace("Z", "+00:00"))
                duration_minutes = int((arrival_dt - departure_dt).total_seconds() / 60)
                
                flight = Flight(
                    id=f"amadeus-{offer['id']}",
                    flightNumber=f"{segment['carrierCode']}{segment['number']}",
                    airline=segment.get("carrierCode", "Unknown"),
                    airlineCode=segment["carrierCode"],
                    departureCity=from_city,
                    departureCityCode=segment["departure"]["iataCode"],
                    departureAirport=segment["departure"]["iataCode"],
                    departureAirportCode=segment["departure"]["iataCode"],
                    departureTime=departure_dt,
                    arrivalCity=to_city,
                    arrivalCityCode=segment["arrival"]["iataCode"],
                    arrivalAirport=segment["arrival"]["iataCode"],
                    arrivalAirportCode=segment["arrival"]["iataCode"],
                    arrivalTime=arrival_dt,
                    durationMinutes=duration_minutes,
                    stops=len(offer["itineraries"][0]["segments"]) - 1,
                    cabin=cabin,
                    aircraftModel=segment.get("aircraft", {}).get("code"),
                    price=price,
                    currency="CNY",
                    seatsRemaining=offer.get("numberOfBookableSeats")
                )
                
                score = self._generate_score(flight)
                facilities = self._generate_facilities(cabin, flight.aircraft_model)
                
                results.append(FlightWithScore(
                    flight=flight,
                    score=score,
                    facilities=facilities
                ))
                
            except Exception as e:
                print(f"Error transforming offer: {e}")
                continue
        
        return results
    
    def _generate_score(self, flight: Flight) -> FlightScore:
        """基于航班属性生成评分 - 使用数据库中的飞机舒适度数据"""
        # 简化评分逻辑
        reliability = 8.5  # On-time performance score (default, would use real data)
        
        # Calculate comfort score using aircraft comfort database
        is_premium = flight.cabin in ["公务舱", "头等舱", "business", "first"]
        comfort, comfort_details = AircraftComfortService.calculate_comfort_score(
            aircraft_model=flight.aircraft_model,
            cabin_class=flight.cabin,
            has_wifi=False,  # Amadeus doesn't provide this
            has_power=is_premium,
            has_ife=is_premium
        )
        comfort = round(comfort, 1)
        
        service = 7.5
        value = min(9.0, max(5.0, 10 - (flight.price / 500)))
        
        overall = round((reliability * 0.25 + comfort * 0.3 + service * 0.2 + value * 0.25), 1)
        
        # Generate comfort explanations from aircraft data
        comfort_explanations = AircraftComfortService.get_comfort_explanation(
            aircraft_model=flight.aircraft_model,
            cabin_class=flight.cabin,
            comfort_score=comfort
        )
        
        explanations = []
        for exp in comfort_explanations:
            explanations.append(ScoreExplanation(
                dimension="comfort",
                title=exp["title"],
                detail=exp["detail"],
                isPositive=exp["is_positive"]
            ))
        
        return FlightScore(
            overallScore=overall,
            dimensions=ScoreDimensions(
                reliability=reliability,
                comfort=comfort,
                service=service,
                value=value,
                amenities=5.0 + (2.5 if is_premium else 0),
                efficiency=10.0 if flight.stops == 0 else (8.0 if flight.stops == 1 else 6.0)
            ),
            highlights=["直飞" if flight.stops == 0 else ""],
            explanations=explanations,
            personaWeightsApplied="default"
        )
    
    def _generate_facilities(self, cabin: str, aircraft_model: str = None) -> FlightFacilities:
        """生成设施信息 - 使用数据库中的飞机舒适度数据"""
        is_premium = cabin in ["公务舱", "头等舱", "business", "first"]
        
        # Get comfort data from database
        comfort_data = AircraftComfortService.get_comfort_data(aircraft_model) if aircraft_model else None
        
        if comfort_data:
            if is_premium:
                seat_pitch = comfort_data.seat_pitch_business
                ife_screen = comfort_data.ife_screen_business
            else:
                seat_pitch = comfort_data.seat_pitch_economy
                ife_screen = comfort_data.ife_screen_economy
            
            # Determine seat pitch category
            if is_premium:
                seat_pitch_category = "宽敞" if seat_pitch >= 60 else "标准"
            else:
                if seat_pitch >= 33:
                    seat_pitch_category = "宽敞"
                elif seat_pitch >= 31:
                    seat_pitch_category = "标准"
                else:
                    seat_pitch_category = "紧凑"
            
            has_ife = ife_screen > 0
            ife_type = f"{ife_screen}英寸屏幕" if ife_screen > 0 else None
        else:
            # Fallback
            seat_pitch = 32 if cabin in ["经济舱", "economy"] else 42
            seat_pitch_category = "标准"
            has_ife = is_premium
            ife_type = "个人屏幕" if is_premium else None
        
        return FlightFacilities(
            hasWifi=None,
            hasPower=is_premium,
            seatPitchInches=seat_pitch,
            seatPitchCategory=seat_pitch_category,
            hasIFE=has_ife,
            ifeType=ife_type,
            mealIncluded=True,
            mealType="正餐"
        )
    
    async def get_flight_availability(
        self,
        origin: str,
        destination: str,
        date: str,
        cabin: str = "ECONOMY"
    ) -> Dict[str, int]:
        """
        Fetch seat availability for ALL flights on a route in ONE API call.
        
        Uses Amadeus Flight Availabilities Search API:
        POST /v1/shopping/availability/flight-availabilities
        
        Returns a dict mapping normalized flight keys to seat counts:
          { "CX 888": 9, "BA 27": 4, ... }
        
        Results are cached for 30 minutes per route+date+cabin to conserve quota.
        """
        # Map cabin string to Amadeus cabin code
        cabin_map = {
            "economy": "ECONOMY",
            "premium": "PREMIUM_ECONOMY",
            "premium economy": "PREMIUM_ECONOMY",
            "business": "BUSINESS",
            "first": "FIRST",
        }
        travel_class = cabin_map.get(cabin.lower(), "ECONOMY")
        
        # Check cache
        cache_key = f"{origin}-{destination}-{date}-{travel_class}"
        if cache_key in self._availability_cache:
            cached_time, cached_data = self._availability_cache[cache_key]
            if datetime.now() - cached_time < self._cache_ttl:
                print(f"[Amadeus Availability] Cache hit for {cache_key}")
                return cached_data
            else:
                del self._availability_cache[cache_key]
        
        try:
            token = await self._get_access_token()
            
            url = f"{self.base_url}/v1/shopping/availability/flight-availabilities"
            
            # Build the request body for batch availability
            request_body = {
                "originDestinations": [
                    {
                        "id": "1",
                        "originLocationCode": origin.upper(),
                        "destinationLocationCode": destination.upper(),
                        "departureDateTime": {
                            "date": date  # YYYY-MM-DD
                        }
                    }
                ],
                "travelers": [
                    {
                        "id": "1",
                        "travelerType": "ADULT"
                    }
                ],
                "sources": ["GDS"]
            }
            
            print(f"[Amadeus Availability] Fetching for {origin}->{destination} on {date}, cabin={travel_class}")
            
            response = await self.client.post(
                url,
                json=request_body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-HTTP-Method-Override": "GET",
                    "Accept": "application/vnd.amadeus+json"
                }
            )
            
            if response.status_code != 200:
                print(f"[Amadeus Availability] Error {response.status_code}: {response.text[:500]}")
                return {}
            
            data = response.json()
            
            # Parse the response: extract seat counts per flight segment
            # Map: "CARRIER NUMBER" -> min seats across all segments
            availability_map: Dict[str, int] = {}
            
            for offer in data.get("data", []):
                for segment in offer.get("segments", []):
                    carrier = segment.get("carrierCode", "")
                    number = segment.get("number", "")
                    
                    if not carrier or not number:
                        continue
                    
                    # Normalize flight key to match SerpAPI format: "CX 888"
                    flight_key = f"{carrier} {number}"
                    
                    # Find the max bookable seats for the target cabin class
                    # Each segment has availabilityClasses with class codes and seat counts
                    max_seats = 0
                    for avail_class in segment.get("availabilityClasses", []):
                        class_code = avail_class.get("class", "")
                        num_seats = avail_class.get("numberOfBookableSeats", 0)
                        
                        # Map class codes to cabin categories
                        # Economy: Y, B, H, K, L, M, N, Q, S, T, V, W, X, G, O, E
                        # Premium Economy: W (sometimes), R
                        # Business: J, C, D, I, Z
                        # First: F, A, P
                        is_match = False
                        if travel_class == "ECONOMY":
                            is_match = class_code in "YBHKLMNQSTVWXGOE"
                        elif travel_class == "PREMIUM_ECONOMY":
                            is_match = class_code in "WR"
                        elif travel_class == "BUSINESS":
                            is_match = class_code in "JCDIZ"
                        elif travel_class == "FIRST":
                            is_match = class_code in "FAP"
                        
                        if is_match and num_seats > max_seats:
                            max_seats = num_seats
                    
                    if max_seats > 0:
                        # If flight has multiple segments (connecting), use minimum
                        if flight_key in availability_map:
                            availability_map[flight_key] = min(availability_map[flight_key], max_seats)
                        else:
                            availability_map[flight_key] = max_seats
            
            print(f"[Amadeus Availability] Found availability for {len(availability_map)} flights")
            
            # Cache the results
            self._availability_cache[cache_key] = (datetime.now(), availability_map)
            
            return availability_map
            
        except Exception as e:
            print(f"[Amadeus Availability] Error: {e}")
            return {}

    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


# Singleton instance
amadeus_service = AmadeusService()
