"""
AirEase Backend - Flight API Routes
航班相关API路由

Supports both SerpAPI (real Google Flights data) and mock data fallback.
"""

from fastapi import APIRouter, HTTPException, Query, Header
from typing import Optional
import uuid

from app.models import (
    FlightSearchResponse, FlightDetail, PriceHistory,
    FlightWithScore, SearchMeta, ErrorResponse
)
from app.services.mock_service import mock_flight_service
from app.services.serpapi_service import serpapi_flight_service, get_airport_code
from app.services.auth_service import auth_service
from app.config import settings

# Maximum number of results for non-authenticated users
MAX_FREE_RESULTS = 3

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
                
                # Call SerpAPI
                serpapi_response = await serpapi_flight_service.search_flights(
                    departure_id=departure_code,
                    arrival_id=arrival_code,
                    outbound_date=date,
                    return_date=return_date,
                    travel_class=travel_class,
                    adults=adults,
                    currency=currency,
                    stops=stops,
                )
                
                # Check for API errors
                if "error" in serpapi_response:
                    print(f"SerpAPI error: {serpapi_response['error']}")
                    raise Exception(serpapi_response["error"])
                
                # Parse the response
                all_flights, price_insights = serpapi_flight_service.parse_flight_response(
                    serpapi_response, cabin
                )
                
            except Exception as e:
                print(f"SerpAPI failed, falling back to mock data: {e}")
                # Fall back to mock data
                all_flights = mock_flight_service.search_flights(
                    from_city=from_city,
                    to_city=to_city,
                    date=date,
                    cabin=cabin
                )
        else:
            # Use mock service
            all_flights = mock_flight_service.search_flights(
                from_city=from_city,
                to_city=to_city,
                date=date,
                cabin=cabin
            )

        total_count = len(all_flights)
        restricted_count = 0

        # Sort flights based on sort_by parameter
        if sort_by == "score":
            all_flights.sort(key=lambda x: x.score.overall_score, reverse=True)
        elif sort_by == "price":
            all_flights.sort(key=lambda x: x.flight.price)
        elif sort_by == "duration":
            all_flights.sort(key=lambda x: x.flight.duration_minutes)
        elif sort_by == "departure":
            all_flights.sort(key=lambda x: x.flight.departure_time)
        elif sort_by == "arrival":
            all_flights.sort(key=lambda x: x.flight.arrival_time)

        # Limit results for non-authenticated users
        if is_authenticated:
            visible_flights = all_flights
        else:
            visible_flights = all_flights[:MAX_FREE_RESULTS]
            restricted_count = max(0, total_count - MAX_FREE_RESULTS)

        return FlightSearchResponse(
            flights=visible_flights,
            meta=SearchMeta(
                total=total_count,
                searchId=f"search-{uuid.uuid4().hex[:8]}",
                cachedAt=None,
                restrictedCount=restricted_count,
                isAuthenticated=is_authenticated
            ),
            priceInsights=price_insights
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    detail = mock_flight_service.get_flight_detail(flight_id)
    
    if not detail:
        raise HTTPException(status_code=404, detail="航班不存在")
    
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
    history = mock_flight_service.get_price_history(flight_id)
    
    if not history:
        raise HTTPException(status_code=404, detail="航班不存在")
    
    return history
