"""
AirEase Backend - Amadeus Airport & City Search Service
Replaces SerpAPI autocomplete with Amadeus Airport & City Search API.

Endpoint: GET /v1/reference-data/locations
Docs: https://developers.amadeus.com/self-service/category/air/api-doc/airport-and-city-search

Note: Test environment only contains data from US, Spain, UK, Germany, and India.
Production will have global coverage.
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class AmadeusAutocompleteService:
    """
    Amadeus Airport & City Search API Service.
    
    Searches airports and cities by keyword, returns IATA codes,
    city names, country info, geo coordinates, and traveler scores.
    
    Reuses the same OAuth2 client_credentials flow as the seatmap service.
    """

    def __init__(self):
        self.base_url = settings.amadeus_base_url
        self.api_key = settings.amadeus_api_key
        self.api_secret = settings.amadeus_api_secret
        self.access_token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self.client = httpx.AsyncClient(timeout=15.0)

    async def _get_access_token(self) -> str:
        """Get OAuth2 access token via client_credentials grant."""
        if self.access_token and self.token_expires and datetime.now() < self.token_expires:
            return self.access_token

        auth_url = f"{self.base_url}/v1/security/oauth2/token"

        try:
            response = await self.client.post(
                auth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.api_key,
                    "client_secret": self.api_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                logger.error(f"Amadeus auth failed [{response.status_code}]: {response.text}")
                raise Exception(f"Amadeus authentication failed: {response.status_code}")

            data = response.json()
            self.access_token = data["access_token"]
            self.token_expires = datetime.now() + timedelta(
                seconds=data.get("expires_in", 1799) - 60
            )
            logger.info("Amadeus autocomplete OAuth2 token obtained")
            return self.access_token

        except httpx.RequestError as e:
            logger.error(f"Amadeus auth request error: {e}")
            raise Exception(f"Failed to connect to Amadeus API: {e}")

    async def search_locations(
        self,
        keyword: str,
        sub_type: str = "AIRPORT,CITY",
        country_code: Optional[str] = None,
        page_limit: int = 10,
        page_offset: int = 0,
        sort: str = "analytics.travelers.score",
        view: str = "FULL",
    ) -> Dict[str, Any]:
        """
        Search airports and cities by keyword.

        Args:
            keyword: Search text (e.g., "New", "MUC", "London")
                     Must be at least 1 character, represents start of a word.
            sub_type: Comma-separated: "AIRPORT", "CITY", or "AIRPORT,CITY"
            country_code: ISO 3166-1 alpha-2 country code filter (e.g., "US", "DE")
            page_limit: Max results per page (default 10)
            page_offset: Pagination offset
            sort: Sort field (only "analytics.travelers.score" supported)
            view: "LIGHT" or "FULL" — FULL includes geocode, address, timezone, score

        Returns:
            Raw Amadeus response dict with "data" array of Location objects.
        """
        token = await self._get_access_token()

        url = f"{self.base_url}/v1/reference-data/locations"

        params: Dict[str, Any] = {
            "subType": sub_type,
            "keyword": keyword,
            "page[limit]": page_limit,
            "page[offset]": page_offset,
            "sort": sort,
            "view": view,
        }

        if country_code:
            params["countryCode"] = country_code

        headers = {
            "Authorization": f"Bearer {token}",
        }

        try:
            response = await self.client.get(url, params=params, headers=headers)

            if response.status_code == 401:
                # Token expired, retry once
                self.access_token = None
                token = await self._get_access_token()
                headers["Authorization"] = f"Bearer {token}"
                response = await self.client.get(url, params=params, headers=headers)

            if response.status_code != 200:
                logger.error(
                    f"Amadeus location search failed [{response.status_code}]: {response.text}"
                )
                return {"data": [], "error": response.text}

            return response.json()

        except httpx.RequestError as e:
            logger.error(f"Amadeus location search request error: {e}")
            raise Exception(f"Failed to search Amadeus locations: {e}")

    async def get_location_by_id(self, location_id: str) -> Dict[str, Any]:
        """
        Get a specific airport or city by its Amadeus location ID.

        Args:
            location_id: e.g., "CMUC" (city Munich) or "AMUC" (airport Munich)

        Returns:
            Single Location object.
        """
        token = await self._get_access_token()

        url = f"{self.base_url}/v1/reference-data/locations/{location_id}"

        headers = {
            "Authorization": f"Bearer {token}",
        }

        try:
            response = await self.client.get(url, headers=headers)

            if response.status_code == 401:
                self.access_token = None
                token = await self._get_access_token()
                headers["Authorization"] = f"Bearer {token}"
                response = await self.client.get(url, headers=headers)

            if response.status_code != 200:
                logger.error(
                    f"Amadeus location lookup failed [{response.status_code}]: {response.text}"
                )
                return {"data": None, "error": response.text}

            return response.json()

        except httpx.RequestError as e:
            logger.error(f"Amadeus location lookup request error: {e}")
            raise Exception(f"Failed to get Amadeus location: {e}")

    def parse_locations(self, raw_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse Amadeus location search response into a clean list of suggestions.

        Each suggestion contains:
        - iataCode: IATA code (e.g., "JFK", "MUC")
        - name: Short name (e.g., "MUNICH INTERNATIONAL")
        - detailedName: Full name with city/country (e.g., "MUNICH/DE:MUNICH INTERNATIONAL")
        - subType: "AIRPORT" or "CITY"
        - cityName: City name
        - countryName: Country name
        - countryCode: ISO country code
        - geoCode: { latitude, longitude }
        - score: Traveler popularity score
        """
        data = raw_response.get("data", [])
        results = []

        for location in data:
            address = location.get("address", {})
            analytics = location.get("analytics", {})
            travelers = analytics.get("travelers", {})
            geo_code = location.get("geoCode", {})

            parsed = {
                "id": location.get("id", ""),
                "iataCode": location.get("iataCode", ""),
                "name": location.get("name", ""),
                "detailedName": location.get("detailedName", ""),
                "subType": location.get("subType", ""),
                "cityName": address.get("cityName", ""),
                "cityCode": address.get("cityCode", ""),
                "countryName": address.get("countryName", ""),
                "countryCode": address.get("countryCode", ""),
                "regionCode": address.get("regionCode", ""),
                "stateCode": address.get("stateCode", ""),
                "timeZoneOffset": location.get("timeZoneOffset", ""),
                "geoCode": {
                    "latitude": geo_code.get("latitude"),
                    "longitude": geo_code.get("longitude"),
                } if geo_code else None,
                "score": travelers.get("score"),
            }

            results.append(parsed)

        return results


# Singleton instance
amadeus_autocomplete_service = AmadeusAutocompleteService()
