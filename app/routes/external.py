"""
External Partner API — Ski Finder Integration
=============================================

Public API endpoints for partner sites (e.g. skifinder.ai) to embed AirEase
flight search into their own product. Two integration modes are supported:

1.  **Deep-link / redirect mode** (no server integration required)
    Partner navigates user to
    `https://airease.ai/external/ski?resort=<NAME>` (or `?arrival=<IATA>`)
    The AirEase SPA performs browser geolocation to detect the user's nearest
    airport, then redirects to `/flights?from=...&to=...&date=...`.

2.  **REST mode** (server-to-server)
    Partner sends a `GET /v1/external/ski/search` request with the desired
    arrival airport / resort plus optional departure code or coordinates.
    Returns the same JSON payload as the regular `/v1/flights/search`
    endpoint. Requires `X-API-Key` header if `EXTERNAL_API_KEY` is configured
    on the server.

The mapping of ski resort → arrival airport is curated from the partner-
supplied dataset.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import settings
from app.models import FlightSearchResponse
from app.routes.flights import search_flights as _internal_search_flights
from app.services.serpapi_service import get_airport_code

router = APIRouter(prefix="/v1/external/ski", tags=["External - Ski Finder"])


# ---------------------------------------------------------------------------
# Curated ski-resort → airport mapping.
# Source: partner CSV (skifinder.ai 2026-05-15).
# ---------------------------------------------------------------------------
SKI_RESORTS: list[dict] = [
    {"resort": "Whistler Blackcomb",  "airport_code": "YVR", "airport_name": "Vancouver International Airport"},
    {"resort": "Zermatt",             "airport_code": "ZRH", "airport_name": "Zurich Airport"},
    {"resort": "Val Thorens",         "airport_code": "GVA", "airport_name": "Geneva Airport"},
    {"resort": "Vail",                "airport_code": "DEN", "airport_name": "Denver International Airport"},
    {"resort": "Courchevel",          "airport_code": "GVA", "airport_name": "Geneva Airport"},
    {"resort": "St. Anton",           "airport_code": "ZRH", "airport_name": "Zurich Airport"},
    {"resort": "Verbier",             "airport_code": "GVA", "airport_name": "Geneva Airport"},
    {"resort": "Niseko",              "airport_code": "HND", "airport_name": "Tokyo Haneda Airport"},
    {"resort": "Aspen Snowmass",      "airport_code": "DEN", "airport_name": "Denver International Airport"},
    {"resort": "Breckenridge",        "airport_code": "DEN", "airport_name": "Denver International Airport"},
    {"resort": "Jackson Hole",        "airport_code": "SLC", "airport_name": "Salt Lake City International Airport"},
    {"resort": "Val d'Isère",         "airport_code": "GVA", "airport_name": "Geneva Airport"},
    {"resort": "Chamonix",            "airport_code": "GVA", "airport_name": "Geneva International Airport"},
    {"resort": "Kitzbühel",           "airport_code": "ZRH", "airport_name": "Zurich Airport"},
    {"resort": "Hakuba Valley",       "airport_code": "HND", "airport_name": "Tokyo Haneda Airport"},
    {"resort": "Mont Tremblant",      "airport_code": "YUL", "airport_name": "Montréal–Trudeau International Airport"},
    {"resort": "Park City",           "airport_code": "SLC", "airport_name": "Salt Lake City International Airport"},
    {"resort": "Davos-Klosters",      "airport_code": "ZRH", "airport_name": "Zurich Airport"},
    {"resort": "Portillo",            "airport_code": "SCL", "airport_name": "Santiago International Airport"},
    {"resort": "Cortina d'Ampezzo",   "airport_code": "GVA", "airport_name": "Geneva Airport"},
]

_RESORT_INDEX: dict[str, dict] = {r["resort"].lower(): r for r in SKI_RESORTS}


def _resolve_resort(resort: str) -> Optional[dict]:
    """Case- and whitespace-insensitive resort lookup."""
    if not resort:
        return None
    key = resort.strip().lower()
    if key in _RESORT_INDEX:
        return _RESORT_INDEX[key]
    # fuzzy: try contains
    for k, v in _RESORT_INDEX.items():
        if key in k or k in key:
            return v
    return None


def _enforce_api_key(provided: Optional[str]) -> None:
    """If an EXTERNAL_API_KEY is configured, partners must supply it."""
    expected = getattr(settings, "external_api_key", "") or ""
    if not expected:
        return  # gating disabled until a key is provisioned
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/resorts",
    summary="List supported ski resorts",
    description="Returns the curated mapping of ski resorts to their primary "
                "arrival airport. Partners can cache this list locally.",
)
async def list_resorts():
    return {
        "count": len(SKI_RESORTS),
        "resorts": SKI_RESORTS,
    }


@router.get(
    "/redirect-url",
    summary="Build a deep-link URL into AirEase",
    description="Returns a ready-to-use URL the partner can `window.open()` "
                "or `<a href=...>` to send users into the AirEase booking flow. "
                "AirEase will perform browser geolocation to fill the departure.",
)
async def build_redirect_url(
    resort: Optional[str] = Query(None, description="Ski resort name (e.g. 'Niseko')"),
    arrival: Optional[str] = Query(None, description="IATA airport code (e.g. 'HND'). Takes precedence over `resort`."),
    date: Optional[str] = Query(None, description="Outbound date YYYY-MM-DD. Defaults to today + 30 days."),
    cabin: str = Query("economy", description="economy / business / first"),
    adults: int = Query(1, ge=1, le=9, description="Adult passenger count (1-9)"),
    children: int = Query(0, ge=0, le=8, description="Child passenger count (0-8)"),
):
    arrival_code = (arrival or "").strip().upper()
    if not arrival_code and resort:
        info = _resolve_resort(resort)
        if not info:
            raise HTTPException(status_code=404, detail=f"Unknown resort: {resort}")
        arrival_code = info["airport_code"]
    if not arrival_code:
        raise HTTPException(status_code=400, detail="Provide either `resort` or `arrival`")

    qs_parts = [f"arrival={arrival_code}"]
    if date:
        qs_parts.append(f"date={date}")
    if cabin:
        qs_parts.append(f"cabin={cabin}")
    if adults != 1:
        qs_parts.append(f"adults={adults}")
    if children:
        qs_parts.append(f"children={children}")
    if resort:
        qs_parts.append(f"resort={resort}")

    url = f"https://airease.ai/external/ski?{'&'.join(qs_parts)}"
    return {"url": url, "arrival_code": arrival_code}


@router.get(
    "/search",
    response_model=FlightSearchResponse,
    summary="Search flights to a ski destination (partner REST API)",
    description="Server-to-server endpoint. Pass either `resort` or "
                "`arrival_code`, plus a `departure_code` (if known on the "
                "partner side) — otherwise the partner should use the "
                "deep-link mode so the browser can do geolocation.",
)
async def external_ski_search(
    resort: Optional[str] = Query(None, description="Ski resort name from /resorts list"),
    arrival_code: Optional[str] = Query(None, description="IATA airport code; overrides `resort`"),
    departure_code: Optional[str] = Query(None, description="IATA airport code of the departure airport"),
    date: Optional[str] = Query(None, description="Outbound date YYYY-MM-DD. Defaults to today + 30 days."),
    cabin: str = Query("economy", description="economy / business / first"),
    adults: int = Query(1, ge=1, le=9),
    children: int = Query(0, ge=0, le=8),
    currency: str = Query("USD"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="Partner API key (required if configured)"),
):
    _enforce_api_key(x_api_key)

    # Resolve arrival
    arr = (arrival_code or "").strip().upper()
    if not arr and resort:
        info = _resolve_resort(resort)
        if not info:
            raise HTTPException(status_code=404, detail=f"Unknown resort: {resort}")
        arr = info["airport_code"]
    if not arr:
        raise HTTPException(status_code=400, detail="Provide either `resort` or `arrival_code`")

    if not departure_code:
        raise HTTPException(
            status_code=400,
            detail="REST mode requires `departure_code`. For automatic geo "
                   "detection, use the deep-link mode via /redirect-url.",
        )

    dep = get_airport_code(departure_code.strip().upper())

    if not date:
        date = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")

    # Delegate to the canonical flight search implementation so partners get
    # the exact same scoring/pricing/sorting logic as the main site.
    return await _internal_search_flights(
        from_city=dep,
        to_city=arr,
        date=date,
        cabin=cabin,
        return_date=None,
        adults=adults,
        children=children,
        currency=currency,
        stops=None,
        sort_by="score",
        traveler_type="default",
        limit=50,
        offset=0,
        authorization=None,
    )
