"""
AirEase Backend - Booking Redirect Routes
Handles flight booking redirects to airline websites
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from typing import Optional, List
import httpx
from urllib.parse import urlencode

from app.services.booking_redirect_service import booking_redirect_service
from app.config import settings

router = APIRouter(prefix="/v1/booking", tags=["Booking"])


@router.get(
    "/redirect",
    response_class=HTMLResponse,
    summary="Redirect to airline booking page",
    description="""
    Resolves a booking_token into a direct airline booking session.
    
    This endpoint fetches booking options from Google Flights via SerpAPI
    and generates an HTML page that automatically submits a POST request
    to the airline's booking system.
    
    The redirect mimics Google Flights' behavior by:
    1. Finding the best matching booking option
    2. Extracting the POST URL and data
    3. Generating an auto-submit form
    """
)
async def redirect_to_booking(
    booking_token: str = Query(
        ...,
        description="Booking token from flight search results"
    ),
    departure_id: Optional[str] = Query(
        None,
        description="Departure airport code (e.g., 'JFK', 'LAX')"
    ),
    arrival_id: Optional[str] = Query(
        None,
        description="Arrival airport code (e.g., 'SFO', 'ORD')"
    ),
    outbound_date: Optional[str] = Query(
        None,
        description="Outbound flight date in YYYY-MM-DD format"
    ),
    return_date: Optional[str] = Query(
        None,
        description="Return flight date in YYYY-MM-DD format (for round trips)"
    ),
    airline_name: Optional[str] = Query(
        None,
        description="Preferred airline name to match (e.g., 'Delta', 'United'). Falls back to first available if not matched."
    ),
    prefer_departing: bool = Query(
        False,
        description="For round trips with separate tickets, prefer departing flight booking"
    ),
    prefer_returning: bool = Query(
        False,
        description="For round trips with separate tickets, prefer returning flight booking"
    ),
    prefer_expedia: bool = Query(
        False,
        description="If True, prefer Expedia as the booking provider (for mixed-airline bookings). Falls back to first available option if Expedia is not listed."
    )
):
    """
    Redirect user to airline booking page.
    
    This endpoint performs the following steps:
    
    1. **Fetch Data**: Calls SerpAPI Google Flights engine with the booking_token
    2. **Parse Response**: Finds matching booking option by airline_name or defaults to first
    3. **Extract Details**: Gets the booking_request URL and POST data
    4. **Generate HTML**: Returns an auto-submitting form that redirects to the airline
    
    ### Response Types
    
    - **Success**: HTML page with auto-submit form → redirects to airline
    - **Phone Booking**: HTML page with phone number if online booking unavailable
    - **Error**: HTML page with error message if booking unavailable
    
    ### Important Notes
    
    - The redirect uses POST, not GET, to match Google Flights behavior
    - Booking tokens expire, so use them promptly after search
    - Some flights only support phone booking
    """
    # Check if SerpAPI is configured
    if not settings.serpapi_key:
        return HTMLResponse(
            content=booking_redirect_service.generate_error_html(
                error_message="Booking service not configured",
                details="Please contact support or try booking directly on the airline's website."
            ),
            status_code=500
        )
    
    try:
        # Step 1: Fetch booking options from SerpAPI
        serpapi_response = await booking_redirect_service.get_booking_options(
            booking_token=booking_token,
            departure_id=departure_id,
            arrival_id=arrival_id,
            outbound_date=outbound_date,
            return_date=return_date
        )
        
        # Check for API errors
        if "error" in serpapi_response:
            # Check if we have a Google Flights fallback URL
            google_flights_url = serpapi_response.get("_google_flights_url")
            if google_flights_url:
                return HTMLResponse(
                    content=booking_redirect_service.generate_google_flights_fallback_html(
                        google_flights_url=google_flights_url
                    ),
                    status_code=200
                )
            # Return 200 instead of 502 to avoid Cloudflare "Host Error" interception
            return HTMLResponse(
                content=booking_redirect_service.generate_error_html(
                    error_message="Booking options temporarily unavailable",
                    details="This flight's booking data could not be retrieved. Please try again or search for a new flight."
                ),
                status_code=200
            )
        
        # Step 2: Get booking options
        booking_options = serpapi_response.get("booking_options", [])
        
        if not booking_options:
            # Check if we have a Google Flights fallback URL
            google_flights_url = serpapi_response.get("_google_flights_url")
            if google_flights_url:
                return HTMLResponse(
                    content=booking_redirect_service.generate_google_flights_fallback_html(
                        google_flights_url=google_flights_url
                    ),
                    status_code=200
                )

            # Check if this is a Chinese domestic route
            from app.services.booking_redirect_service import _get_country_code_for_airport
            dep_country = _get_country_code_for_airport(departure_id) if departure_id else ""
            arr_country = _get_country_code_for_airport(arrival_id) if arrival_id else ""
            is_chinese_domestic = dep_country == "cn" and arr_country == "cn"
            
            if is_chinese_domestic:
                return HTMLResponse(
                    content=booking_redirect_service.generate_error_html(
                        error_message="Google does not support Chinese domestic bookings",
                        details="Please book directly on the airline's website or through a Chinese travel platform such as Ctrip (携程), Qunar (去哪儿), or Fliggy (飞猪)."
                    ),
                    status_code=200
                )
            
            return HTMLResponse(
                content=booking_redirect_service.generate_error_html(
                    error_message="No booking options available",
                    details="This flight may no longer be available. Please try a new search."
                ),
                status_code=200
            )
        
        # Step 3: Find matching booking option
        selected_option = booking_redirect_service.find_booking_option(
            booking_options=booking_options,
            airline_name=airline_name,
            prefer_expedia=prefer_expedia
        )
        
        if not selected_option:
            return HTMLResponse(
                content=booking_redirect_service.generate_error_html(
                    error_message="No matching booking option found",
                    details=f"Could not find booking option for '{airline_name}'. Please try without specifying an airline."
                ),
                status_code=404
            )
        
        # Step 4: Extract booking request details
        together = selected_option.get("together", {})
        
        # Check for phone-only booking
        booking_phone = together.get("booking_phone")
        if booking_phone and not together.get("booking_request"):
            return HTMLResponse(
                content=booking_redirect_service.generate_phone_booking_html(
                    airline_name=together.get("book_with", "Airline"),
                    phone_number=booking_phone,
                    price=together.get("price"),
                    fee=together.get("estimated_phone_service_fee")
                ),
                status_code=200
            )
        
        # Extract URL and POST data
        booking_details = booking_redirect_service.extract_booking_request(
            booking_option=selected_option,
            prefer_departing=prefer_departing,
            prefer_returning=prefer_returning
        )
        
        if not booking_details:
            return HTMLResponse(
                content=booking_redirect_service.generate_error_html(
                    error_message="Booking redirect not available",
                    details="This booking option does not support online redirect. Please try a different option or book directly."
                ),
                status_code=404
            )
        
        url, post_data = booking_details
        
        # Step 5: Generate redirect HTML
        redirect_html = booking_redirect_service.generate_redirect_html(
            url=url,
            post_data=post_data,
            airline_name=together.get("book_with", "Airline"),
            price=together.get("price")
        )
        
        return HTMLResponse(content=redirect_html, status_code=200)
    
    except httpx.HTTPStatusError as e:
        print(f"❌ Booking API error: {e.response.status_code} - {e}")
        return HTMLResponse(
            content=booking_redirect_service.generate_error_html(
                error_message="Booking service temporarily unavailable",
                details="The booking data for this flight could not be retrieved. The booking token may have expired — please search again."
            ),
            status_code=200
        )
    except Exception as e:
        print(f"❌ Booking redirect error: {e}")
        return HTMLResponse(
            content=booking_redirect_service.generate_error_html(
                error_message="An error occurred",
                details=str(e)
            ),
            status_code=200
        )


@router.get(
    "/booking-options",
    summary="Get booking options for a flight",
    description="Fetch all available booking options for a flight without redirecting"
)
async def get_booking_options(
    booking_token: str = Query(
        ...,
        description="Booking token from flight search results"
    ),
    departure_id: Optional[str] = Query(
        None,
        description="Departure airport IATA code (e.g., HKG)"
    ),
    arrival_id: Optional[str] = Query(
        None,
        description="Arrival airport IATA code (e.g., NRT)"
    ),
    outbound_date: Optional[str] = Query(
        None,
        description="Outbound date in YYYY-MM-DD format"
    ),
    return_date: Optional[str] = Query(
        None,
        description="Return date for round trips (YYYY-MM-DD)"
    )
):
    """
    Get all booking options for a flight.
    
    Returns the raw booking options from SerpAPI, useful for:
    - Displaying multiple booking options to the user
    - Showing price comparisons from different sellers
    - Letting users choose their preferred booking source
    
    ### Response Fields
    
    - **booking_options**: List of booking options with prices, sellers, and baggage info
    - **selected_flights**: Details of the selected flights
    - **baggage_prices**: Baggage pricing information
    """
    if not settings.serpapi_key:
        raise HTTPException(
            status_code=500,
            detail="Booking service not configured"
        )
    
    try:
        response = await booking_redirect_service.get_booking_options(
            booking_token=booking_token,
            departure_id=departure_id,
            arrival_id=arrival_id,
            outbound_date=outbound_date,
            return_date=return_date
        )
        
        if "error" in response:
            raise HTTPException(
                status_code=422,
                detail=response.get("error", "Failed to fetch booking options")
            )
        
        return {
            "booking_options": response.get("booking_options", []),
            "selected_flights": response.get("selected_flights", []),
            "baggage_prices": response.get("baggage_prices", {}),
            "price_insights": response.get("price_insights")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch booking options: {str(e)}"
        )


@router.get(
    "/booking-links",
    summary="Get all booking platform links for a flight",
    description="Returns structured booking links for all available platforms, for use in the frontend hover menu."
)
async def get_booking_links(
    request: Request,
    booking_token: str = Query(
        ...,
        description="Booking token from flight search results"
    ),
    departure_id: Optional[str] = Query(None, description="Departure airport IATA code"),
    arrival_id: Optional[str] = Query(None, description="Arrival airport IATA code"),
    outbound_date: Optional[str] = Query(None, description="Outbound date YYYY-MM-DD"),
    return_date: Optional[str] = Query(None, description="Return date YYYY-MM-DD"),
    airline_name: Optional[str] = Query(None, description="Airline name for labelling"),
):
    """
    Returns a list of booking platforms with redirect URLs.

    Each item has:
    - **name**: Platform display name (e.g., "Expedia", "Trip.com", "Japan Airlines")
    - **url**: Redirect URL through our /v1/booking/redirect endpoint
    - **price**: Price on that platform (if available)
    - **isAirline**: Whether this is the airline's official site
    - **logoHint**: Lowercase brand name for icon matching
    """
    if not settings.serpapi_key:
        raise HTTPException(status_code=500, detail="Booking service not configured")

    try:
        serpapi_response = await booking_redirect_service.get_booking_options(
            booking_token=booking_token,
            departure_id=departure_id,
            arrival_id=arrival_id,
            outbound_date=outbound_date,
            return_date=return_date,
        )

        booking_options = serpapi_response.get("booking_options", [])
        print(f"📋 booking-links: SerpAPI returned {len(booking_options)} booking_options")
        for i, opt in enumerate(booking_options):
            t = opt.get("together", {})
            print(f"   [{i}] book_with={t.get('book_with','?')}, airline={t.get('airline',False)}, price={t.get('price')}")
        if not booking_options:
            return {"links": []}

        # Build the base redirect URL using the request's origin
        # This ensures it works behind proxies / ngrok / production
        base_url = str(request.base_url).rstrip("/")

        links = []
        seen_names = set()
        for idx, option in enumerate(booking_options):
            together = option.get("together", {})
            book_with = together.get("book_with", "").strip()
            is_airline = together.get("airline", False)

            # Some options use separate_tickets with departing/returning instead of together
            if not book_with and option.get("separate_tickets"):
                departing = option.get("departing", {})
                book_with = departing.get("book_with", "").strip()
                is_airline = departing.get("airline", False)

            if not book_with or book_with in seen_names:
                continue
            seen_names.add(book_with)
            price = together.get("price")

            # Build a redirect URL that selects this specific option by index
            redirect_params = {
                "booking_token": booking_token,
                "option_index": str(idx),
            }
            if departure_id:
                redirect_params["departure_id"] = departure_id
            if arrival_id:
                redirect_params["arrival_id"] = arrival_id
            if outbound_date:
                redirect_params["outbound_date"] = outbound_date
            if return_date:
                redirect_params["return_date"] = return_date

            redirect_url = f"{base_url}/v1/booking/redirect-by-index?{urlencode(redirect_params)}"

            links.append({
                "name": book_with,
                "url": redirect_url,
                "price": price,
                "isAirline": is_airline,
                "logoHint": book_with.lower().split()[0],  # first word lowercase
            })

        return {"links": links}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch booking links: {str(e)}")


@router.get(
    "/redirect-by-index",
    response_class=HTMLResponse,
    summary="Redirect to a specific booking option by index",
)
async def redirect_by_index(
    booking_token: str = Query(..., description="Booking token"),
    option_index: int = Query(..., description="Index of the booking option to use"),
    departure_id: Optional[str] = Query(None),
    arrival_id: Optional[str] = Query(None),
    outbound_date: Optional[str] = Query(None),
    return_date: Optional[str] = Query(None),
):
    """Redirect to a specific booking platform by its index in booking_options."""
    if not settings.serpapi_key:
        return HTMLResponse(
            content=booking_redirect_service.generate_error_html(
                "Booking service not configured", ""
            ),
            status_code=500,
        )

    try:
        serpapi_response = await booking_redirect_service.get_booking_options(
            booking_token=booking_token,
            departure_id=departure_id,
            arrival_id=arrival_id,
            outbound_date=outbound_date,
            return_date=return_date,
        )

        booking_options = serpapi_response.get("booking_options", [])

        if not booking_options:
            google_flights_url = serpapi_response.get("_google_flights_url")
            if google_flights_url:
                return HTMLResponse(
                    content=booking_redirect_service.generate_google_flights_fallback_html(google_flights_url),
                    status_code=200,
                )
            return HTMLResponse(
                content=booking_redirect_service.generate_error_html(
                    "No booking options available",
                    "This flight may no longer be available.",
                ),
                status_code=200,
            )

        # Clamp index
        idx = min(option_index, len(booking_options) - 1)
        selected_option = booking_options[idx]

        together = selected_option.get("together", {})

        # Phone-only?
        booking_phone = together.get("booking_phone")
        if booking_phone and not together.get("booking_request"):
            return HTMLResponse(
                content=booking_redirect_service.generate_phone_booking_html(
                    airline_name=together.get("book_with", "Airline"),
                    phone_number=booking_phone,
                    price=together.get("price"),
                    fee=together.get("estimated_phone_service_fee"),
                ),
                status_code=200,
            )

        booking_details = booking_redirect_service.extract_booking_request(
            booking_option=selected_option,
        )

        if not booking_details:
            return HTMLResponse(
                content=booking_redirect_service.generate_error_html(
                    "Booking redirect not available",
                    "This option does not support online redirect.",
                ),
                status_code=200,
            )

        url, post_data = booking_details
        return HTMLResponse(
            content=booking_redirect_service.generate_redirect_html(
                url=url,
                post_data=post_data,
                airline_name=together.get("book_with", "Airline"),
                price=together.get("price"),
            ),
            status_code=200,
        )

    except Exception as e:
        print(f"❌ redirect-by-index error: {e}")
        return HTMLResponse(
            content=booking_redirect_service.generate_error_html("An error occurred", str(e)),
            status_code=200,
        )
