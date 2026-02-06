"""
AirEase Backend - Price Insights API Routes
价格洞察API

Uses SerpAPI Google Flights Price Insights for price analysis.
https://serpapi.com/google-flights-price-insights
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.models import (
    PriceInsightsResponse, PriceInsightsData, RouteInfo,
    PriceRange, PriceHistoryPoint
)
from app.services.serpapi_service import serpapi_price_insights_service
from app.config import settings

router = APIRouter(prefix="/v1/price-insights", tags=["Price Insights"])


@router.get(
    "",
    response_model=PriceInsightsResponse,
    summary="获取价格洞察",
    description="获取航线价格分析，包括最低价、价格水平和历史趋势。"
)
async def get_price_insights(
    departure: str = Query(..., alias="from", description="出发机场代码 (如: 'HKG', 'JFK')"),
    arrival: str = Query(..., alias="to", description="到达机场代码 (如: 'NRT', 'LAX')"),
    outbound_date: str = Query(..., alias="outboundDate", description="出发日期 (YYYY-MM-DD)"),
    return_date: Optional[str] = Query(None, alias="returnDate", description="返程日期 (YYYY-MM-DD，可选)"),
    currency: str = Query("USD", description="货币代码 (如: 'USD', 'CNY', 'EUR')"),
    travel_class: int = Query(1, alias="travelClass", ge=1, le=4, description="舱位: 1=经济, 2=高端经济, 3=商务, 4=头等"),
    adults: int = Query(1, ge=1, le=9, description="成人乘客数量"),
    gl: str = Query("us", description="国家代码"),
    hl: str = Query("en", description="语言代码"),
):
    """
    获取价格洞察 - Get Price Insights
    
    使用 SerpAPI Google Flights API 获取航线价格分析。
    
    功能特点:
    - 最低价: 当前搜索结果中的最低价格
    - 价格水平: 相对于历史价格的评估 (low/typical/high)
    - 典型价格区间: 该航线的正常价格范围
    - 历史价格: 过去几周的价格趋势
    
    价格水平说明:
    - **low**: 价格低于正常水平，适合购买
    - **typical**: 价格处于正常水平
    - **high**: 价格高于正常水平，可以考虑等待
    
    参数:
    - **from**: 出发机场IATA代码 (必填)
    - **to**: 到达机场IATA代码 (必填)
    - **outboundDate**: 出发日期 YYYY-MM-DD (必填)
    - **returnDate**: 返程日期 YYYY-MM-DD (可选，往返程时需要)
    - **currency**: 货币代码 (默认: USD)
    - **travelClass**: 舱位等级 1-4 (默认: 1=经济舱)
    - **adults**: 成人数量 (默认: 1)
    
    返回示例:
    ```json
    {
        "route": {
            "departure": "HKG",
            "arrival": "NRT",
            "outboundDate": "2024-03-15",
            "returnDate": "2024-03-22"
        },
        "insights": {
            "lowestPrice": 450,
            "priceLevel": "typical",
            "priceLevelDescription": "Prices are typical for this route",
            "typicalPriceRange": {"low": 400, "high": 600},
            "priceHistory": [
                {"date": "2024-02-15", "price": 520},
                {"date": "2024-02-20", "price": 490},
                {"date": "2024-02-25", "price": 450}
            ]
        },
        "currency": "USD"
    }
    ```
    
    使用场景:
    1. 帮助用户判断当前价格是否合理
    2. 展示价格趋势图表
    3. 推荐最佳购买时机
    """
    # Check if SerpAPI is configured
    if not settings.serpapi_key:
        raise HTTPException(
            status_code=503,
            detail="Price insights service is not configured. SERPAPI_KEY is missing."
        )
    
    try:
        # Call SerpAPI for price insights
        raw_response = await serpapi_price_insights_service.get_price_insights(
            departure_id=departure.upper(),
            arrival_id=arrival.upper(),
            outbound_date=outbound_date,
            return_date=return_date,
            currency=currency,
            hl=hl,
            gl=gl,
            travel_class=travel_class,
            adults=adults
        )
        
        # Extract and parse price insights
        raw_insights = raw_response.get("price_insights", {})
        parsed_insights = serpapi_price_insights_service.parse_price_insights(raw_insights)
        
        # Build response
        route_info = RouteInfo(
            departure=departure.upper(),
            arrival=arrival.upper(),
            outboundDate=outbound_date,
            returnDate=return_date
        )
        
        insights_data = None
        if parsed_insights:
            # Convert price history
            price_history = None
            if parsed_insights.get("priceHistory"):
                price_history = [
                    PriceHistoryPoint(date=p["date"], price=p["price"])
                    for p in parsed_insights["priceHistory"]
                ]
            
            # Convert typical price range
            typical_range = None
            if parsed_insights.get("typicalPriceRange"):
                typical_range = PriceRange(
                    low=parsed_insights["typicalPriceRange"]["low"],
                    high=parsed_insights["typicalPriceRange"]["high"]
                )
            
            insights_data = PriceInsightsData(
                lowestPrice=parsed_insights.get("lowestPrice"),
                priceLevel=parsed_insights.get("priceLevel"),
                priceLevelDescription=parsed_insights.get("priceLevelDescription"),
                typicalPriceRange=typical_range,
                priceHistory=price_history
            )
        
        return PriceInsightsResponse(
            route=route_info,
            insights=insights_data,
            currency=currency
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch price insights: {str(e)}"
        )


@router.get(
    "/compare",
    summary="比较多个日期的价格",
    description="比较不同日期的价格，帮助用户选择最佳出行日期。"
)
async def compare_date_prices(
    departure: str = Query(..., alias="from", description="出发机场代码"),
    arrival: str = Query(..., alias="to", description="到达机场代码"),
    dates: str = Query(..., description="逗号分隔的日期列表 (YYYY-MM-DD,YYYY-MM-DD,...)"),
    currency: str = Query("USD", description="货币代码"),
    travel_class: int = Query(1, alias="travelClass", ge=1, le=4, description="舱位等级"),
):
    """
    比较多个日期的价格 - Compare Prices Across Dates
    
    一次性获取多个日期的价格洞察，便于用户选择最便宜的出行日期。
    
    参数:
    - **from**: 出发机场代码
    - **to**: 到达机场代码
    - **dates**: 逗号分隔的日期列表，最多5个日期
    - **currency**: 货币代码
    - **travelClass**: 舱位等级
    
    返回:
    ```json
    {
        "route": {"departure": "HKG", "arrival": "NRT"},
        "currency": "USD",
        "dateComparison": [
            {"date": "2024-03-15", "lowestPrice": 450, "priceLevel": "typical"},
            {"date": "2024-03-16", "lowestPrice": 420, "priceLevel": "low"},
            {"date": "2024-03-17", "lowestPrice": 550, "priceLevel": "high"}
        ],
        "recommendation": {
            "bestDate": "2024-03-16",
            "lowestPrice": 420,
            "savings": 130
        }
    }
    ```
    """
    # Check if SerpAPI is configured
    if not settings.serpapi_key:
        raise HTTPException(
            status_code=503,
            detail="Price insights service is not configured. SERPAPI_KEY is missing."
        )
    
    # Parse dates
    date_list = [d.strip() for d in dates.split(",")]
    if len(date_list) > 5:
        raise HTTPException(
            status_code=400,
            detail="Maximum 5 dates allowed for comparison"
        )
    
    if len(date_list) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 dates required for comparison"
        )
    
    try:
        date_comparison = []
        
        # Fetch price insights for each date
        for date in date_list:
            try:
                raw_response = await serpapi_price_insights_service.get_price_insights(
                    departure_id=departure.upper(),
                    arrival_id=arrival.upper(),
                    outbound_date=date,
                    currency=currency,
                    travel_class=travel_class
                )
                
                raw_insights = raw_response.get("price_insights", {})
                
                date_comparison.append({
                    "date": date,
                    "lowestPrice": raw_insights.get("lowest_price"),
                    "priceLevel": raw_insights.get("price_level", "unknown"),
                    "typicalPriceRange": raw_insights.get("typical_price_range"),
                })
            except Exception as e:
                # If one date fails, continue with others
                date_comparison.append({
                    "date": date,
                    "lowestPrice": None,
                    "priceLevel": "error",
                    "error": str(e)
                })
        
        # Find the best date (lowest price)
        valid_prices = [d for d in date_comparison if d.get("lowestPrice") is not None]
        recommendation = None
        
        if valid_prices:
            best = min(valid_prices, key=lambda x: x["lowestPrice"])
            highest = max(valid_prices, key=lambda x: x["lowestPrice"])
            
            recommendation = {
                "bestDate": best["date"],
                "lowestPrice": best["lowestPrice"],
                "savings": highest["lowestPrice"] - best["lowestPrice"] if len(valid_prices) > 1 else 0
            }
        
        return {
            "route": {
                "departure": departure.upper(),
                "arrival": arrival.upper()
            },
            "currency": currency,
            "dateComparison": date_comparison,
            "recommendation": recommendation
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to compare date prices: {str(e)}"
        )
