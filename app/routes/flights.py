"""
AirEase Backend - Flight API Routes
航班相关API路由

Supports both SerpAPI (real Google Flights data) and mock data fallback.
"""

from fastapi import APIRouter, HTTPException, Query, Header
from typing import Optional, Dict
import uuid

from app.models import (
    FlightSearchResponse, FlightDetail, PriceHistory,
    FlightWithScore, SearchMeta, ErrorResponse, RoundTripSearchResponse
)
from app.services.mock_service import mock_flight_service
from app.services.serpapi_service import serpapi_flight_service, get_airport_code
from app.services.amadeus_service import amadeus_service
from app.services.auth_service import auth_service
from app.config import settings

# Maximum number of results for non-authenticated users
MAX_FREE_RESULTS = 3

# Default page size for flight results - fetch all for accuracy
DEFAULT_PAGE_SIZE = 200

# Set to True to use SerpAPI (real data), False for mock data
USE_SERPAPI = True

router = APIRouter(prefix="/v1/flights", tags=["Flights"])


def map_cabin_to_travel_class(cabin: str) -> int:
    """Map cabin string to SerpAPI travel_class integer."""
    cabin_lower = cabin.lower()
    if cabin_lower in ["business", "公务舱"]:
        return 3
    elif cabin_lower in ["first", "头等舱"]:
        return 4
    elif cabin_lower in ["premium", "premium economy", "高端经济舱"]:
        return 2
    else:
        return 1  # Economy


@router.get(
    "/search",
    response_model=FlightSearchResponse,
    summary="搜索航班",
    description="根据出发地、目的地、日期和舱位搜索航班。未登录用户只能看到前3条结果。"
)
async def search_flights(
    from_city: str = Query(..., alias="from", description="出发城市（如：北京、上海）或机场代码（如：PEK, HKG）"),
    to_city: str = Query(..., alias="to", description="到达城市或机场代码"),
    date: str = Query(..., description="出发日期（YYYY-MM-DD）"),
    cabin: str = Query("economy", description="舱位：economy/business/first 或 经济舱/公务舱/头等舱"),
    return_date: Optional[str] = Query(None, description="返程日期（可选，YYYY-MM-DD）"),
    adults: int = Query(1, ge=1, le=9, description="成人乘客数量"),
    currency: str = Query("USD", description="货币：USD, CNY, EUR, etc."),
    stops: Optional[int] = Query(None, ge=0, le=3, description="经停：0=任意, 1=直飞, 2=1经停或更少, 3=2经停或更少"),
    sort_by: str = Query("score", description="排序方式：score/price/duration/departure/arrival"),
    traveler_type: str = Query("default", description="旅客类型：student/business/family/default - 影响评分权重"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=500, description="每页返回数量，默认200，最大500"),
    offset: int = Query(0, ge=0, description="偏移量，用于分页加载更多"),
    authorization: Optional[str] = Header(None, description="JWT Bearer token")
):
    """
    搜索航班 - Search Flights
    
    Uses SerpAPI Google Flights API for real flight data.
    Falls back to mock data if SerpAPI is unavailable.

    - **from**: 出发城市名称或机场代码 (e.g., "北京", "PEK", "HKG")
    - **to**: 到达城市名称或机场代码 (e.g., "东京", "NRT", "LHR")
    - **date**: 出发日期，格式 YYYY-MM-DD
    - **cabin**: 舱位类型 (economy/business/first)
    - **return_date**: 返程日期（可选）
    - **adults**: 成人乘客数量
    - **currency**: 货币代码
    - **stops**: 经停过滤
    - **traveler_type**: 旅客类型 (student/business/family/default)
      - student: 重视价格和效率
      - business: 重视可靠性和服务
      - family: 重视舒适度和服务
    - **Authorization**: Bearer token（可选，未登录用户只能看到前3条结果）

    返回匹配的航班列表，包含评分、设施信息、价格趋势等
    """
    try:
        # Check authentication status
        is_authenticated = False
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
            payload = auth_service.decode_token(token)
            is_authenticated = payload is not None

        all_flights = []
        price_insights = None
        
        # Try SerpAPI first if enabled and API key is configured
        if USE_SERPAPI and settings.serpapi_key:
            try:
                # Convert city names to airport codes
                departure_code = get_airport_code(from_city)
                arrival_code = get_airport_code(to_city)
                travel_class = map_cabin_to_travel_class(cabin)
                
                # Call SerpAPI with traveler_type to optimize sort strategy
                # - student: fetches cheapest flights first (sort_by=2)
                # - business: fetches top-ranked flights (sort_by=1)
                # - family: fetches top-ranked flights (sort_by=1)
                serpapi_response = await serpapi_flight_service.search_flights(
                    departure_id=departure_code,
                    arrival_id=arrival_code,
                    outbound_date=date,
                    return_date=return_date,
                    travel_class=travel_class,
                    adults=adults,
                    currency=currency,
                    stops=stops,
                    traveler_type=traveler_type,  # Pass traveler_type for optimal sorting
                )
                
                # Check for API errors
                if "error" in serpapi_response:
                    print(f"SerpAPI error: {serpapi_response['error']}")
                    raise Exception(serpapi_response["error"])
                
                # Parse the response with traveler_type for personalized scoring
                all_flights, price_insights = serpapi_flight_service.parse_flight_response(
                    serpapi_response, cabin, traveler_type=traveler_type
                )
                
            except Exception as e:
                print(f"SerpAPI failed, falling back to mock data: {e}")
                # Fall back to mock data with traveler_type for personalized scoring
                all_flights = mock_flight_service.search_flights(
                    from_city=from_city,
                    to_city=to_city,
                    date=date,
                    cabin=cabin,
                    traveler_type=traveler_type
                )
        else:
            # Use mock service with traveler_type for personalized scoring
            all_flights = mock_flight_service.search_flights(
                from_city=from_city,
                to_city=to_city,
                date=date,
                cabin=cabin,
                traveler_type=traveler_type
            )

        total_count = len(all_flights)
        restricted_count = 0

        # Sort flights based on sort_by parameter
        # Special handling: For students, "score" sorting means "best value" = sort by price
        if sort_by == "score":
            if traveler_type == "student":
                # Students: "best score" means "best price" - sort by price ascending
                all_flights.sort(key=lambda x: x.flight.price)
            else:
                # Business/Family/Default: sort by overall weighted score
                all_flights.sort(key=lambda x: x.score.overall_score, reverse=True)
        elif sort_by == "price":
            all_flights.sort(key=lambda x: x.flight.price)
        elif sort_by == "duration":
            all_flights.sort(key=lambda x: x.flight.duration_minutes)
        elif sort_by == "departure":
            all_flights.sort(key=lambda x: x.flight.departure_time)
        elif sort_by == "arrival":
            all_flights.sort(key=lambda x: x.flight.arrival_time)

        # Apply pagination with limit and offset
        # For non-authenticated users, we still apply MAX_FREE_RESULTS limit
        if is_authenticated:
            # Apply offset and limit for pagination
            paginated_flights = all_flights[offset:offset + limit]
            has_more = (offset + limit) < total_count
        else:
            # Non-authenticated: limit to MAX_FREE_RESULTS, no pagination
            paginated_flights = all_flights[:MAX_FREE_RESULTS]
            restricted_count = max(0, total_count - MAX_FREE_RESULTS)
            has_more = False

        return FlightSearchResponse(
            flights=paginated_flights,
            meta=SearchMeta(
                total=total_count,
                searchId=f"search-{uuid.uuid4().hex[:8]}",
                cachedAt=None,
                restrictedCount=restricted_count,
                isAuthenticated=is_authenticated,
                limit=limit,
                offset=offset,
                hasMore=has_more
            ),
            priceInsights=price_insights
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/availability",
    response_model=Dict[str, int],
    summary="获取航班座位余量",
    description=(
        "使用 Amadeus Flight Availabilities API 批量获取某条航线所有航班的剩余座位数。"
        "一次 API 调用获取所有航班数据，结果缓存30分钟。"
        "返回 { flightKey: seatsRemaining } 映射。"
    )
)
async def get_flight_availability(
    origin: str = Query(..., description="出发机场IATA代码 (如 HKG, NRT)"),
    destination: str = Query(..., description="到达机场IATA代码"),
    date: str = Query(..., description="出发日期 (YYYY-MM-DD)"),
    cabin: str = Query("economy", description="舱位：economy/business/first"),
):
    """
    Batch fetch seat availability for ALL flights on a route.
    
    Uses ONE Amadeus API call per route+date.
    Results are cached for 30 minutes.
    
    Returns a mapping of flight keys to remaining seat counts:
    { "CX 888": 9, "BA 27": 4 }
    """
    try:
        availability = await amadeus_service.get_flight_availability(
            origin=origin,
            destination=destination,
            date=date,
            cabin=cabin
        )
        return availability
    except Exception as e:
        print(f"[Availability Endpoint] Error: {e}")
        # Return empty dict on error - graceful degradation
        return {}


@router.get(
    "/search-roundtrip",
    response_model=RoundTripSearchResponse,
    summary="搜索往返航班",
    description="搜索往返航班，分别显示出发和返回航班及其各自价格"
)
async def search_roundtrip_flights(
    from_city: str = Query(..., alias="from", description="出发城市/机场代码"),
    to_city: str = Query(..., alias="to", description="到达城市/机场代码"),
    date: str = Query(..., description="出发日期（YYYY-MM-DD）"),
    return_date: str = Query(..., description="返程日期（YYYY-MM-DD）"),
    cabin: str = Query("economy", description="舱位：economy/business/first"),
    adults: int = Query(1, ge=1, le=9, description="成人乘客数量"),
    currency: str = Query("USD", description="货币"),
    stops: Optional[int] = Query(None, ge=0, le=3, description="经停过滤"),
    traveler_type: str = Query("default", description="旅客类型：student/business/family/default"),
    authorization: Optional[str] = Header(None)
):
    """
    搜索往返航班 - 使用两次独立的单程搜索
    
    Returns separate departure and return flights with individual one-way prices.
    This allows users to see the exact cost of each leg.
    
    Note: Individual one-way prices may be higher than bundled round-trip prices.
    """
    import asyncio
    
    try:
        # Check authentication
        is_authenticated = False
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
            payload = auth_service.decode_token(token)
            is_authenticated = payload is not None
        
        departure_code = get_airport_code(from_city)
        arrival_code = get_airport_code(to_city)
        travel_class = map_cabin_to_travel_class(cabin)
        
        # Execute BOTH searches in PARALLEL for speed:
        # 1. Round-trip search: Gets departure flights + price_insights
        # 2. One-way return search: Gets return flights
        # This is faster than sequential and we get price_insights!
        roundtrip_search = serpapi_flight_service.search_flights(
            departure_id=departure_code,
            arrival_id=arrival_code,
            outbound_date=date,
            return_date=return_date,  # Round-trip to get price_insights!
            travel_class=travel_class,
            adults=adults,
            currency=currency,
            stops=stops,
            traveler_type=traveler_type,
        )
        
        return_search = serpapi_flight_service.search_flights(
            departure_id=arrival_code,  # Reversed for return leg
            arrival_id=departure_code,
            outbound_date=return_date,
            return_date=None,  # One-way for individual return flight pricing
            travel_class=travel_class,
            adults=adults,
            currency=currency,
            stops=stops,
            traveler_type=traveler_type,
        )
        
        # Execute both in parallel - much faster!
        roundtrip_response, return_response = await asyncio.gather(
            roundtrip_search, return_search
        )
        
        # Parse responses
        # Round-trip response has departure flights + price_insights
        departure_flights, price_insights = serpapi_flight_service.parse_flight_response(
            roundtrip_response, cabin, traveler_type=traveler_type
        )
        # One-way return response has return flights (with individual pricing)
        return_flights, return_price_insights = serpapi_flight_service.parse_flight_response(
            return_response, cabin, traveler_type=traveler_type
        )
        
        # Apply authentication limits
        if not is_authenticated:
            departure_flights = departure_flights[:MAX_FREE_RESULTS]
            return_flights = return_flights[:MAX_FREE_RESULTS]
        
        total_count = len(departure_flights) + len(return_flights)
        
        return RoundTripSearchResponse(
            departureFlights=departure_flights,
            returnFlights=return_flights,
            meta=SearchMeta(
                total=total_count,
                searchId=f"roundtrip-{uuid.uuid4().hex[:8]}",
                cachedAt=None,
                restrictedCount=0,
                isAuthenticated=is_authenticated,
                limit=len(departure_flights),
                offset=0,
                hasMore=False
            ),
            # Use price_insights from the round-trip search for departure
            departurePriceInsights=price_insights,
            # Return leg uses price insights from one-way (usually null)
            returnPriceInsights=return_price_insights
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/return-flights",
    response_model=FlightSearchResponse,
    summary="获取返程航班",
    description="使用departure_token获取返程航班选项（用于往返机票）"
)
async def get_return_flights(
    departure_token: str = Query(..., description="从出发航班获取的departure_token"),
    from_city: str = Query(..., alias="from", description="原始出发城市/机场代码"),
    to_city: str = Query(..., alias="to", description="原始到达城市/机场代码"),
    date: str = Query(..., description="出发日期（YYYY-MM-DD）"),
    return_date: str = Query(..., description="返程日期（YYYY-MM-DD）"),
    cabin: str = Query("economy", description="舱位：economy/business/first"),
    adults: int = Query(1, ge=1, le=9, description="成人乘客数量"),
    currency: str = Query("USD", description="货币"),
    traveler_type: str = Query("default", description="用户类型：student/business/family/default"),
    authorization: Optional[str] = Header(None)
):
    """
    获取返程航班选项
    
    使用选定出发航班的departure_token来获取匹配的返程航班。
    每个返程航班显示的价格是往返总价。
    """
    try:
        # Check authentication
        is_authenticated = False
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]
            payload = auth_service.decode_token(token)
            is_authenticated = payload is not None
        
        # Map cabin to travel class
        travel_class = map_cabin_to_travel_class(cabin)
        
        # Convert city names to airport codes
        from_code = get_airport_code(from_city)
        to_code = get_airport_code(to_city)
        
        # Fetch return flights
        return_flights = await serpapi_flight_service.search_return_flights(
            departure_id=from_code,
            arrival_id=to_code,
            outbound_date=date,
            return_date=return_date,
            departure_token=departure_token,
            travel_class=travel_class,
            adults=adults,
            currency=currency,
            traveler_type=traveler_type
        )
        
        total_count = len(return_flights)
        
        # For non-authenticated users, limit results
        if not is_authenticated:
            return_flights = return_flights[:MAX_FREE_RESULTS]
            restricted_count = max(0, total_count - MAX_FREE_RESULTS)
        else:
            restricted_count = 0
        
        return FlightSearchResponse(
            flights=return_flights,
            meta=SearchMeta(
                total=total_count,
                searchId=f"return-{uuid.uuid4().hex[:8]}",
                cachedAt=None,
                restrictedCount=restricted_count,
                isAuthenticated=is_authenticated,
                limit=len(return_flights),
                offset=0,
                hasMore=False
            ),
            priceInsights=None
        )
    
    except Exception as e:
        print(f"❌ return-flights error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/reviews",
    summary="获取航空公司评价",
    description="根据航空公司名称获取用户评价，用于用户选择特定航班时按需加载"
)
async def get_airline_reviews(
    airline: str = Query(..., description="航空公司名称 (e.g., 'Cathay Pacific', 'Japan Airlines')"),
    cabin: str = Query("economy", description="舱位类型：economy/business"),
    limit: int = Query(10, ge=1, le=50, description="返回评价数量")
):
    """
    获取航空公司用户评价 - Get Airline User Reviews
    
    This endpoint is called on-demand when user selects a specific flight.
    Reviews are NOT fetched during initial flight search to improve performance.
    
    - **airline**: Airline name
    - **cabin**: Cabin class (economy/business)
    - **limit**: Maximum number of reviews to return
    
    Returns list of user reviews with ratings
    """
    from app.services.airline_reviews_service import AirlineReviewsService
    
    reviews_raw = AirlineReviewsService.get_user_reviews(
        airline_name=airline,
        cabin_class=cabin,
        limit=limit
    )
    
    reviews = [
        {
            "title": r.title,
            "review": r.review[:500] if len(r.review) > 500 else r.review,
            "foodRating": r.food_rating,
            "groundServiceRating": r.ground_service_rating,
            "seatComfortRating": r.seat_comfort_rating,
            "serviceRating": r.service_rating,
            "recommended": r.recommended,
            "travelType": r.travel_type,
            "route": r.route,
            "aircraft": r.aircraft,
            "cabinType": r.cabin_type,
            "ratings": {
                "food": r.food_rating,
                "groundService": r.ground_service_rating,
                "seatComfort": r.seat_comfort_rating,
                "service": r.service_rating,
                "overall": round((r.food_rating + r.ground_service_rating + r.seat_comfort_rating + r.service_rating) / 4, 1) if r.food_rating else None
            }
        }
        for r in reviews_raw
    ]
    
    return {
        "airline": airline,
        "cabin": cabin,
        "count": len(reviews),
        "reviews": reviews
    }


@router.get(
    "/{flight_id}",
    response_model=FlightDetail,
    summary="获取航班详情",
    description="获取指定航班的完整详情，包括评分、设施和价格历史"
)
async def get_flight_detail(flight_id: str):
    """
    获取航班详情
    
    返回航班的完整信息，包括：
    - 基础航班信息
    - AirEase体验评分（4维度）
    - 机上设施详情
    - 7天价格历史
    """
    # First check SerpAPI cache (for recently searched flights)
    detail = serpapi_flight_service.get_flight_detail(flight_id)
    
    # Fall back to mock service
    if not detail:
        detail = mock_flight_service.get_flight_detail(flight_id)
    
    if not detail:
        raise HTTPException(status_code=404, detail="航班不存在 - Flight may have expired from cache. Please search again.")
    
    return detail


@router.get(
    "/{flight_id}/price-history",
    response_model=PriceHistory,
    summary="获取价格历史",
    description="获取航班的7天价格走势"
)
async def get_price_history(flight_id: str):
    """
    获取航班价格历史
    
    返回最近7天的价格变化和趋势分析
    """
    # First check if flight is in SerpAPI cache
    detail = serpapi_flight_service.get_flight_detail(flight_id)
    if detail:
        return detail.priceHistory
    
    # Fall back to mock service
    history = mock_flight_service.get_price_history(flight_id)
    
    if not history:
        raise HTTPException(status_code=404, detail="航班不存在")
    
    return history