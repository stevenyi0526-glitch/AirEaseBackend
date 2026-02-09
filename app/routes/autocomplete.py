"""
AirEase Backend - Autocomplete API Routes
位置自动补全API

Uses Amadeus Airport & City Search API for location suggestions.
Falls back to local PostgreSQL airports database when Amadeus returns no results
(e.g., for regions not covered by the Amadeus test environment).
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
import logging
import psycopg2

from app.models import AutocompleteResponse, LocationSuggestion, GeoCode
from app.services.amadeus_autocomplete_service import amadeus_autocomplete_service
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/autocomplete", tags=["Autocomplete"])


def _get_db_connection():
    """Get PostgreSQL connection for local airport fallback."""
    return psycopg2.connect(
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        host=settings.postgres_host,
        port=str(settings.postgres_port),
    )


def _local_airport_search(keyword: str, limit: int = 10) -> List[LocationSuggestion]:
    """
    Search the local airports table as a fallback.
    Returns LocationSuggestion objects matching the Amadeus response format.
    """
    try:
        conn = _get_db_connection()
        cursor = conn.cursor()

        search_term = f"%{keyword.upper()}%"

        cursor.execute(
            """
            SELECT iata_code, name, municipality, iso_country,
                   latitude_deg, longitude_deg
            FROM airports
            WHERE (
                UPPER(iata_code) LIKE %s OR
                UPPER(name) LIKE %s OR
                UPPER(municipality) LIKE %s
            )
            AND type IN ('large_airport', 'medium_airport')
            AND iata_code IS NOT NULL
            AND iata_code != ''
            ORDER BY
                CASE
                    WHEN UPPER(iata_code) = %s THEN 0
                    WHEN UPPER(iata_code) LIKE %s THEN 1
                    WHEN type = 'large_airport' THEN 2
                    ELSE 3
                END
            LIMIT %s
            """,
            (search_term, search_term, search_term, keyword.upper(), search_term, limit),
        )

        results = []
        for row in cursor.fetchall():
            iata_code, name, municipality, country, lat, lng = row
            geo = None
            if lat is not None and lng is not None:
                geo = GeoCode(latitude=float(lat), longitude=float(lng))

            city_name = municipality or ""
            display_name = name or iata_code
            detailed = f"{city_name}/{country}: {display_name}" if city_name else f"{country}: {display_name}"

            results.append(
                LocationSuggestion(
                    id=f"A{iata_code}",
                    iataCode=iata_code,
                    name=display_name.upper(),
                    detailedName=detailed.upper(),
                    subType="AIRPORT",
                    cityName=city_name.upper(),
                    cityCode=iata_code,
                    countryName=country.upper() if country else None,
                    countryCode=country.upper() if country else None,
                    geoCode=geo,
                    score=None,
                )
            )

        cursor.close()
        conn.close()
        return results

    except Exception as e:
        logger.warning(f"Local airport fallback search failed: {e}")
        return []


@router.get(
    "/locations",
    response_model=AutocompleteResponse,
    summary="搜索机场和城市",
    description="根据关键词搜索机场和城市建议。优先使用 Amadeus API，无结果时回退到本地数据库。",
)
async def get_location_suggestions(
    q: str = Query(
        ...,
        min_length=1,
        max_length=100,
        description="搜索关键词 (如: 'New York', 'MUC', 'HKG')",
    ),
    sub_type: str = Query(
        "AIRPORT,CITY",
        alias="subType",
        description="搜索类型: AIRPORT, CITY, 或 AIRPORT,CITY",
    ),
    country_code: Optional[str] = Query(
        None,
        alias="countryCode",
        description="ISO 3166-1 alpha-2 国家代码过滤 (如: 'US', 'DE', 'GB')",
    ),
    page_limit: int = Query(
        10,
        alias="limit",
        ge=1,
        le=20,
        description="最大返回数量 (默认 10)",
    ),
):
    """
    搜索机场和城市 - Search Airports & Cities

    优先使用 Amadeus Airport & City Search API。
    当 Amadeus 无结果时（例如测试环境不包含该地区），自动回退到本地数据库搜索。
    """
    # Check if Amadeus API is configured
    if not settings.amadeus_api_key or not settings.amadeus_api_secret:
        # No Amadeus — go straight to local fallback
        suggestions = _local_airport_search(q, page_limit)
        return AutocompleteResponse(query=q, suggestions=suggestions)

    try:
        # 1. Try Amadeus Airport & City Search
        raw_response = await amadeus_autocomplete_service.search_locations(
            keyword=q,
            sub_type=sub_type,
            country_code=country_code,
            page_limit=page_limit,
        )

        # Parse Amadeus results
        parsed = amadeus_autocomplete_service.parse_locations(raw_response)

        suggestions = []
        for item in parsed:
            geo = None
            if item.get("geoCode") and item["geoCode"].get("latitude") is not None:
                geo = GeoCode(
                    latitude=item["geoCode"]["latitude"],
                    longitude=item["geoCode"]["longitude"],
                )

            suggestions.append(
                LocationSuggestion(
                    id=item.get("id"),
                    iataCode=item["iataCode"],
                    name=item["name"],
                    detailedName=item.get("detailedName"),
                    subType=item.get("subType"),
                    cityName=item.get("cityName"),
                    cityCode=item.get("cityCode"),
                    countryName=item.get("countryName"),
                    countryCode=item.get("countryCode"),
                    regionCode=item.get("regionCode"),
                    stateCode=item.get("stateCode"),
                    timeZoneOffset=item.get("timeZoneOffset"),
                    geoCode=geo,
                    score=item.get("score"),
                )
            )

        # 2. If Amadeus returned results, return them
        if suggestions:
            return AutocompleteResponse(query=q, suggestions=suggestions)

        # 3. Amadeus returned empty — fall back to local DB
        logger.info(f"Amadeus returned no results for '{q}', falling back to local DB")
        suggestions = _local_airport_search(q, page_limit)
        return AutocompleteResponse(query=q, suggestions=suggestions)

    except HTTPException:
        raise
    except Exception as e:
        # If Amadeus call itself fails, try local fallback
        logger.warning(f"Amadeus autocomplete failed for '{q}': {e}, using local fallback")
        suggestions = _local_airport_search(q, page_limit)
        if suggestions:
            return AutocompleteResponse(query=q, suggestions=suggestions)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch location suggestions: {str(e)}",
        )


@router.get(
    "/airports",
    response_model=AutocompleteResponse,
    summary="搜索机场",
    description="只返回机场建议，适用于航班搜索。",
)
async def get_airport_suggestions(
    q: str = Query(
        ...,
        min_length=1,
        max_length=100,
        description="搜索关键词",
    ),
    country_code: Optional[str] = Query(
        None,
        alias="countryCode",
        description="国家代码过滤",
    ),
    page_limit: int = Query(
        10,
        alias="limit",
        ge=1,
        le=20,
        description="最大返回数量",
    ),
):
    """
    搜索机场 - Search Airports Only

    只搜索机场（不含城市），适用于航班搜索输入框。
    等同于 /locations?subType=AIRPORT
    """
    return await get_location_suggestions(
        q=q,
        sub_type="AIRPORT",
        country_code=country_code,
        page_limit=page_limit,
    )
