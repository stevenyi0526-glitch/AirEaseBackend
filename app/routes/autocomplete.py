"""
AirEase Backend - Autocomplete API Routes
位置自动补全API

Uses SerpAPI Google Flights Autocomplete for location suggestions.
https://serpapi.com/google-flights-autocomplete-api
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.models import (
    AutocompleteResponse, LocationSuggestion, AirportSuggestion
)
from app.services.serpapi_service import serpapi_autocomplete_service
from app.config import settings

router = APIRouter(prefix="/v1/autocomplete", tags=["Autocomplete"])


@router.get(
    "/locations",
    response_model=AutocompleteResponse,
    summary="获取位置建议",
    description="根据搜索词获取城市和机场建议，用于搜索框自动补全。"
)
async def get_location_suggestions(
    q: str = Query(..., min_length=1, max_length=100, description="搜索词 (如: 'New York', '东京', 'HKG')"),
    gl: str = Query("us", description="国家代码 (如: 'us', 'cn', 'hk')"),
    hl: str = Query("en", description="语言代码 (如: 'en', 'zh-CN', 'zh-TW')"),
    exclude_regions: bool = Query(False, alias="excludeRegions", description="是否排除地区级别的结果（只返回有机场的城市）"),
):
    """
    获取位置建议 - Get Location Suggestions
    
    使用 SerpAPI Google Flights Autocomplete API 获取位置建议。
    
    功能特点:
    - 支持城市名称搜索 (如: "New York", "东京", "香港")
    - 支持机场代码搜索 (如: "JFK", "NRT", "HKG")
    - 返回城市和地区建议
    - 城市建议包含关联机场列表
    - 支持多语言 (英语、中文等)
    
    参数:
    - **q**: 搜索词 (必填)
    - **gl**: 国家代码，用于本地化结果 (默认: "us")
    - **hl**: 语言代码 (默认: "en")
    - **excludeRegions**: 是否排除地区级别结果 (默认: false)
      - false: 返回城市和地区
      - true: 只返回有机场的城市
    
    返回示例:
    ```json
    {
        "query": "Korea",
        "suggestions": [
            {
                "position": 1,
                "name": "Seoul, South Korea",
                "type": "city",
                "description": "Capital of South Korea",
                "id": "/m/0hsqf",
                "airports": [
                    {"name": "Incheon International Airport", "code": "ICN", "city": "Seoul", "distance": "31 mi"},
                    {"name": "Gimpo International Airport", "code": "GMP", "city": "Seoul", "distance": "11 mi"}
                ]
            },
            {
                "position": 2,
                "name": "South Korea",
                "type": "region",
                "description": "Country in East Asia"
            }
        ]
    }
    ```
    """
    # Check if SerpAPI is configured
    if not settings.serpapi_key:
        raise HTTPException(
            status_code=503,
            detail="Autocomplete service is not configured. SERPAPI_KEY is missing."
        )
    
    try:
        # Call SerpAPI Autocomplete
        raw_response = await serpapi_autocomplete_service.get_suggestions(
            query=q,
            gl=gl,
            hl=hl,
            exclude_regions=exclude_regions
        )
        
        # Check for API errors
        if "error" in raw_response:
            raise HTTPException(
                status_code=502,
                detail=f"SerpAPI error: {raw_response['error']}"
            )
        
        # Parse suggestions
        parsed_suggestions = serpapi_autocomplete_service.parse_suggestions(raw_response)
        
        # Convert to Pydantic models
        suggestions = []
        for item in parsed_suggestions:
            airports = None
            if item.get("airports"):
                airports = [
                    AirportSuggestion(
                        name=a["name"],
                        code=a["code"],
                        city=a.get("city"),
                        cityId=a.get("cityId"),
                        distance=a.get("distance")
                    )
                    for a in item["airports"]
                ]
            
            suggestions.append(LocationSuggestion(
                position=item["position"],
                name=item["name"],
                type=item["type"],
                description=item.get("description"),
                id=item.get("id"),
                airports=airports
            ))
        
        return AutocompleteResponse(
            query=q,
            suggestions=suggestions
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch location suggestions: {str(e)}"
        )


@router.get(
    "/airports",
    response_model=AutocompleteResponse,
    summary="获取机场建议",
    description="只返回有机场的城市建议，适用于航班搜索。"
)
async def get_airport_suggestions(
    q: str = Query(..., min_length=1, max_length=100, description="搜索词"),
    gl: str = Query("us", description="国家代码"),
    hl: str = Query("en", description="语言代码"),
):
    """
    获取机场建议 - Get Airport Suggestions
    
    专门用于航班搜索的机场建议接口。
    只返回有机场的城市，不包含地区级别的结果。
    
    这是 /locations 接口的简化版本，等同于设置 excludeRegions=true。
    """
    return await get_location_suggestions(
        q=q,
        gl=gl,
        hl=hl,
        exclude_regions=True
    )
