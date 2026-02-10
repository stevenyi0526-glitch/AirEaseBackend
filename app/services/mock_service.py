"""
AirEase Backend - Mock Data Service
模拟航班数据服务
"""

from datetime import datetime, timedelta
from typing import List, Optional
import random
import uuid

from app.models import (
    Flight, FlightScore, FlightFacilities, FlightWithScore,
    FlightDetail, PriceHistory, PricePoint, PriceTrend,
    ScoreDimensions, ScoreExplanation, ServiceHighlights, UserReviewSummary, UserReviewRatings
)
from app.services.aircraft_comfort_service import AircraftComfortService
from app.services.airline_reviews_service import AirlineReviewsService
from app.services.scoring_service import ScoringService


class MockFlightService:
    """Mock航班数据服务"""
    
    def __init__(self):
        self._flights: List[FlightWithScore] = []
        self._generate_mock_flights()
    
    def _generate_mock_flights(self):
        """生成模拟航班数据"""
        airlines = [
            ("CA", "中国国航"),
            ("MU", "东方航空"),
            ("CZ", "南方航空"),
            ("HU", "海南航空"),
            ("3U", "四川航空"),
            ("ZH", "深圳航空"),
            ("FM", "上海航空"),
            ("MF", "厦门航空"),
        ]
        
        routes = [
            ("北京", "PEK", "首都国际机场", "上海", "SHA", "虹桥国际机场"),
            ("北京", "PEK", "首都国际机场", "上海", "PVG", "浦东国际机场"),
            ("上海", "SHA", "虹桥国际机场", "北京", "PEK", "首都国际机场"),
            ("广州", "CAN", "白云国际机场", "北京", "PEK", "首都国际机场"),
            ("深圳", "SZX", "宝安国际机场", "上海", "SHA", "虹桥国际机场"),
            ("成都", "TFU", "天府国际机场", "北京", "PEK", "首都国际机场"),
            ("杭州", "HGH", "萧山国际机场", "北京", "PEK", "首都国际机场"),
            ("武汉", "WUH", "天河国际机场", "上海", "SHA", "虹桥国际机场"),
        ]
        
        cabins = ["经济舱", "公务舱", "头等舱"]
        aircrafts = [
            "Boeing 787-9", "Boeing 737-800", "Boeing 777-300",
            "Airbus A320", "Airbus A330", "Airbus A350", "Airbus A321"
        ]
        
        flight_id = 1
        base_date = datetime.now() + timedelta(days=3)
        
        for route in routes:
            from_city, from_code, from_airport, to_city, to_code, to_airport = route
            
            for _ in range(random.randint(3, 6)):
                airline_code, airline_name = random.choice(airlines)
                flight_number = f"{airline_code}{random.randint(1000, 9999)}"
                
                hour = random.randint(6, 21)
                minute = random.choice([0, 15, 30, 45])
                departure_time = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                duration = random.randint(120, 200)
                arrival_time = departure_time + timedelta(minutes=duration)
                
                cabin = random.choice(cabins)
                base_price = {
                    "经济舱": random.randint(800, 1500),
                    "公务舱": random.randint(2500, 4500),
                    "头等舱": random.randint(5000, 8000)
                }[cabin]
                
                stops = random.choices([0, 1], weights=[85, 15])[0]
                
                flight = Flight(
                    id=f"flight-{flight_id}",
                    flightNumber=flight_number,
                    airline=airline_name,
                    airlineCode=airline_code,
                    departureCity=from_city,
                    departureCityCode=from_code,
                    departureAirport=from_airport,
                    departureAirportCode=from_code,
                    departureTime=departure_time,
                    arrivalCity=to_city,
                    arrivalCityCode=to_code,
                    arrivalAirport=to_airport,
                    arrivalAirportCode=to_code,
                    arrivalTime=arrival_time,
                    durationMinutes=duration,
                    stops=stops,
                    stopCities=["武汉"] if stops > 0 else None,
                    cabin=cabin,
                    aircraftModel=random.choice(aircrafts),
                    price=float(base_price),
                    currency="CNY",
                    seatsRemaining=random.randint(1, 50)
                )
                
                score = self._generate_score(flight)
                facilities = self._generate_facilities(cabin, flight.aircraft_model)
                
                self._flights.append(FlightWithScore(
                    flight=flight,
                    score=score,
                    facilities=facilities
                ))
                
                flight_id += 1
    
    def _generate_score(self, flight: Flight) -> FlightScore:
        """生成航班评分 - 使用数据库中的飞机舒适度数据和航空公司评价数据"""
        reliability = round(random.uniform(7.5, 9.5), 1)  # On-time performance score
        
        # Get facilities for this cabin
        is_premium = flight.cabin in ["公务舱", "头等舱"]
        has_wifi = random.choice([True, False])
        has_power = True if is_premium else random.choice([True, False])
        has_ife = True if is_premium else random.choice([True, False])
        
        # ============================================================
        # SEPARATE ECONOMY AND BUSINESS CLASS RATINGS
        # ============================================================
        
        # Calculate ECONOMY class comfort score
        comfort_economy, _ = AircraftComfortService.calculate_comfort_score(
            aircraft_model=flight.aircraft_model,
            cabin_class="economy",
            has_wifi=has_wifi,
            has_power=False,
            has_ife=has_ife
        )
        comfort_economy = round(comfort_economy, 1)
        
        # Calculate BUSINESS class comfort score
        comfort_business, _ = AircraftComfortService.calculate_comfort_score(
            aircraft_model=flight.aircraft_model,
            cabin_class="business",
            has_wifi=True,
            has_power=True,
            has_ife=True
        )
        comfort_business = round(comfort_business, 1)
        
        # Calculate SERVICE scores from airline reviews database
        service_economy, service_details_economy = AirlineReviewsService.calculate_service_score(
            airline_name=flight.airline,
            cabin_class="economy"
        )
        
        service_business, service_details_business = AirlineReviewsService.calculate_service_score(
            airline_name=flight.airline,
            cabin_class="business"
        )
        
        # Get user reviews
        user_reviews_raw = AirlineReviewsService.get_user_reviews(
            airline_name=flight.airline,
            cabin_class=flight.cabin,
            limit=10
        )
        
        # Convert to API model with nested ratings object
        user_reviews = [
            UserReviewSummary(
                title=r.title,
                review=r.review[:500] if len(r.review) > 500 else r.review,
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
        
        # Determine which scores to use based on selected cabin class
        if is_premium:
            comfort = comfort_business
            service = service_business
            service_details = service_details_business
        else:
            comfort = comfort_economy
            service = service_economy
            service_details = service_details_economy
        
        value = round(random.uniform(6.5, 9.5), 1)
        
        # Get facilities info for scoring
        facilities = self._generate_facilities(flight.cabin, flight.aircraft_model)
        
        # Default traveler type
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
            stops=flight.stops,
            duration_minutes=flight.duration_minutes,
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
            stops=flight.stops,
            duration_minutes=flight.duration_minutes,
            apply_boost=True
        )
        
        overall_business, _ = ScoringService.calculate_overall_score(
            reliability=reliability,
            comfort=comfort_business,
            service=service_business,
            value=value,
            traveler_type=traveler_type,
            has_wifi=True,
            has_power=True,
            has_ife=True,
            has_meal=True,
            stops=flight.stops,
            duration_minutes=flight.duration_minutes,
            apply_boost=True
        )
        
        # Get persona label
        persona_label = ScoringService.get_persona_label(traveler_type)
        
        highlights = []
        if comfort > 7.5:
            highlights.append("宽敞座椅")
        if value > 7.5:
            highlights.append("高性价比")
        if flight.stops == 0:
            highlights.append("直飞")
        if facilities.has_wifi:
            highlights.append("机上WiFi")
        
        # Generate comfort explanations from aircraft data
        comfort_explanations = AircraftComfortService.get_comfort_explanation(
            aircraft_model=flight.aircraft_model,
            cabin_class=flight.cabin,
            comfort_score=comfort
        )
        
        explanations = [
            ScoreExplanation(
                dimension="reliability",
                title="航司准点率",
                detail=f"{flight.airline}准点率表现良好",
                isPositive=True
            )
        ]
        
        # Add comfort explanations from database
        for exp in comfort_explanations:
            explanations.append(ScoreExplanation(
                dimension="comfort",
                title=exp["title"],
                detail=exp["detail"],
                isPositive=exp["is_positive"]
            ))
        
        # Add service explanations from airline reviews
        service_explanations = AirlineReviewsService.get_service_explanations(
            airline_name=flight.airline,
            cabin_class=flight.cabin,
            service_score=service
        )
        
        for exp in service_explanations:
            explanations.append(ScoreExplanation(
                dimension="service",
                title=exp["title"],
                detail=exp["detail"],
                isPositive=exp["is_positive"]
            ))
        
        explanations.append(
            ScoreExplanation(
                dimension="value",
                title="价格评估",
                detail=f"当前价格{'低于' if value > 7.5 else '接近'}该航线平均水平",
                isPositive=value > 7.5
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
            overallScore=overall,
            dimensions=ScoreDimensions(
                reliability=reliability,
                comfort=comfort,
                service=service,
                value=value,
                amenities=round(score_details["adjusted_scores"]["amenities"], 1),
                efficiency=round(score_details["adjusted_scores"]["efficiency"], 1)
            ),
            economyDimensions=ScoreDimensions(
                reliability=reliability,
                comfort=comfort_economy,
                service=service_economy,
                value=value,
                amenities=round(score_details["adjusted_scores"]["amenities"], 1),
                efficiency=round(score_details["adjusted_scores"]["efficiency"], 1)
            ),
            businessDimensions=ScoreDimensions(
                reliability=reliability,
                comfort=comfort_business,
                service=service_business,
                value=value,
                amenities=round(score_details["adjusted_scores"]["amenities"], 1),
                efficiency=round(score_details["adjusted_scores"]["efficiency"], 1)
            ),
            highlights=highlights[:3],
            explanations=explanations,
            serviceHighlights=service_highlights,
            userReviews=user_reviews if user_reviews else None,
            personaWeightsApplied=persona_label
        )
    
    def _generate_facilities(self, cabin: str, aircraft_model: str = None) -> FlightFacilities:
        """生成机上设施 - 使用数据库中的飞机舒适度数据"""
        is_premium = cabin in ["公务舱", "头等舱"]
        
        # Get comfort data from database
        comfort_data = AircraftComfortService.get_comfort_data(aircraft_model) if aircraft_model else None
        
        if comfort_data:
            if is_premium:
                seat_pitch = comfort_data.seat_pitch_business
                ife_screen = comfort_data.ife_screen_business
            else:
                seat_pitch = comfort_data.seat_pitch_economy
                ife_screen = comfort_data.ife_screen_economy
            
            # Determine seat pitch category based on actual data
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
            # Fallback to random values if no aircraft data
            seat_pitch = random.randint(30, 34) if cabin == "经济舱" else random.randint(38, 78)
            seat_pitch_category = "宽敞" if is_premium else random.choice(["标准", "紧凑", "宽敞"])
            has_ife = random.choice([True, False]) if not is_premium else True
            ife_type = "个人屏幕" if is_premium or random.random() > 0.5 else None
        
        return FlightFacilities(
            hasWifi=random.choice([True, False, None]),
            hasPower=random.choice([True, False]) if not is_premium else True,
            seatPitchInches=seat_pitch,
            seatPitchCategory=seat_pitch_category,
            hasIFE=has_ife,
            ifeType=ife_type,
            mealIncluded=True,
            mealType="公务舱餐食" if is_premium else random.choice(["正餐", "轻食"])
        )
    
    def _generate_price_history(self, flight: Flight) -> PriceHistory:
        """生成价格历史"""
        points = []
        base_date = datetime.now()
        trend = random.choice([PriceTrend.RISING, PriceTrend.FALLING, PriceTrend.STABLE])
        
        for i in range(7, 0, -1):
            date = base_date - timedelta(days=i)
            if trend == PriceTrend.RISING:
                variation = (7 - i) * random.uniform(15, 25)
            elif trend == PriceTrend.FALLING:
                variation = -(7 - i) * random.uniform(15, 25)
            else:
                variation = random.uniform(-30, 30)
            
            price = max(flight.price + variation, flight.price * 0.7)
            points.append(PricePoint(
                date=date.strftime("%Y-%m-%d"),
                price=round(price, 0)
            ))
        
        return PriceHistory(
            flightId=flight.id,
            points=points,
            currentPrice=flight.price,
            trend=trend
        )
    
    # ============================================================
    # Public API
    # ============================================================
    
    def search_flights(
        self,
        from_city: str,
        to_city: str,
        date: str,
        cabin: str = "economy",
        traveler_type: str = "default"
    ) -> List[FlightWithScore]:
        """
        搜索航班
        
        Args:
            traveler_type: Traveler persona for personalized scoring.
                - "student": Prioritizes value and efficiency
                - "business": Prioritizes reliability and service  
                - "family": Prioritizes comfort and service
                - "default": Balanced weights
        """
        cabin_map = {
            "economy": "经济舱",
            "business": "公务舱",
            "first": "头等舱",
            "经济舱": "经济舱",
            "公务舱": "公务舱",
            "头等舱": "头等舱"
        }
        target_cabin = cabin_map.get(cabin, "经济舱")
        
        results = []
        for fws in self._flights:
            flight = fws.flight
            
            # 匹配城市
            from_match = (
                from_city in flight.departure_city or
                from_city == flight.departure_city_code
            )
            to_match = (
                to_city in flight.arrival_city or
                to_city == flight.arrival_city_code
            )
            cabin_match = flight.cabin == target_cabin
            
            if from_match and to_match and cabin_match:
                # Recalculate score with the traveler_type for personalized weighting
                if traveler_type != "default":
                    personalized_score = self._recalculate_score_with_traveler_type(
                        fws.score, fws.facilities, traveler_type, flight
                    )
                    results.append(FlightWithScore(
                        flight=flight,
                        score=personalized_score,
                        facilities=fws.facilities
                    ))
                else:
                    results.append(fws)
        
        return results
    
    def _recalculate_score_with_traveler_type(
        self,
        original_score: FlightScore,
        facilities: FlightFacilities,
        traveler_type: str,
        flight: Flight
    ) -> FlightScore:
        """Recalculate overall score with traveler-specific weights."""
        dims = original_score.dimensions
        
        # Calculate new overall score with traveler-specific weights
        new_overall, score_details = ScoringService.calculate_overall_score(
            reliability=dims.reliability,
            comfort=dims.comfort,
            service=dims.service,
            value=dims.value,
            traveler_type=traveler_type,
            has_wifi=facilities.has_wifi or False,
            has_power=facilities.has_power or False,
            has_ife=facilities.has_ife or False,
            has_meal=facilities.meal_included or False,
            stops=flight.stops,
            duration_minutes=flight.duration_minutes,
            apply_boost=True
        )
        
        persona_label = ScoringService.get_persona_label(traveler_type)
        
        return FlightScore(
            overall_score=new_overall,
            dimensions=original_score.dimensions,
            economy_dimensions=original_score.economy_dimensions,
            business_dimensions=original_score.business_dimensions,
            highlights=original_score.highlights,
            explanations=original_score.explanations,
            service_highlights=original_score.service_highlights,
            user_reviews=original_score.user_reviews,
            persona_weights_applied=persona_label
        )
    
    def get_flight_detail(self, flight_id: str) -> Optional[FlightDetail]:
        """获取航班详情"""
        for fws in self._flights:
            if fws.flight.id == flight_id:
                return FlightDetail(
                    flight=fws.flight,
                    score=fws.score,
                    facilities=fws.facilities,
                    priceHistory=self._generate_price_history(fws.flight)
                )
        return None
    
    def get_price_history(self, flight_id: str) -> Optional[PriceHistory]:
        """获取价格历史"""
        for fws in self._flights:
            if fws.flight.id == flight_id:
                return self._generate_price_history(fws.flight)
        return None


# Singleton instance
mock_flight_service = MockFlightService()
