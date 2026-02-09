"""
AirEase Backend - Booking Redirect Routes
Handles flight booking redirects to airline websites
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from typing import Optional

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
            return HTMLResponse(
                content=booking_redirect_service.generate_error_html(
                    error_message="Failed to fetch booking options",
                    details=serpapi_response.get("error", "Unknown error")
                ),
                status_code=502
            )
        
        # Step 2: Get booking options
        booking_options = serpapi_response.get("booking_options", [])
        
        if not booking_options:
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
                status_code=404
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
        
    except Exception as e:
        print(f"❌ Booking redirect error: {e}")
        return HTMLResponse(
            content=booking_redirect_service.generate_error_html(
                error_message="An error occurred",
                details=str(e)
            ),
            status_code=500
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
            booking_token=booking_token
        )
        
        if "error" in response:
            raise HTTPException(
                status_code=502,
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
