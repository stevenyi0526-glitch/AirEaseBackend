"""
AirEase Backend - Booking Redirect Routes
Handles flight booking redirects to airline websites
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from typing import Optional, List
import httpx
from urllib.parse import urlencode, quote_plus
from datetime import datetime

from app.services.booking_redirect_service import booking_redirect_service
from app.config import settings

router = APIRouter(prefix="/v1/booking", tags=["Booking"])


# ---------------------------------------------------------------------------
# Airline deep-link URL builders
# Each function returns a search URL pre-filled with origin, destination & dates
# ---------------------------------------------------------------------------
def _build_airline_deep_link(
    airline_code: str,
    airline_name: str,
    departure_id: str,
    arrival_id: str,
    outbound_date: str,
    return_date: Optional[str] = None,
) -> Optional[str]:
    """
    Build a direct airline website deep-link that pre-fills the flight search
    with origin/destination/dates so the user lands on results, not the homepage.
    
    Returns None if the airline is not supported.
    """
    code = (airline_code or "").upper()
    name_lower = (airline_name or "").lower()

    # Parse dates into multiple formats airlines commonly use
    try:
        dep_dt = datetime.strptime(outbound_date, "%Y-%m-%d")
        dep_yyyymmdd = dep_dt.strftime("%Y%m%d")  # 20260320
        dep_ddmmyyyy = dep_dt.strftime("%d/%m/%Y")  # 20/03/2026
        dep_mmddyyyy = dep_dt.strftime("%m/%d/%Y")  # 03/20/2026
        dep_ymd = outbound_date  # 2026-03-20
    except ValueError:
        dep_yyyymmdd = outbound_date.replace("-", "")
        dep_ddmmyyyy = outbound_date
        dep_mmddyyyy = outbound_date
        dep_ymd = outbound_date

    ret_yyyymmdd = ""
    ret_ymd = ""
    if return_date:
        try:
            ret_dt = datetime.strptime(return_date, "%Y-%m-%d")
            ret_yyyymmdd = ret_dt.strftime("%Y%m%d")
            ret_ymd = return_date
        except ValueError:
            ret_yyyymmdd = return_date.replace("-", "")
            ret_ymd = return_date

    trip_type_rt = return_date is not None  # round-trip?

    origin = departure_id.upper()
    dest = arrival_id.upper()

    # --- Cathay Pacific (CX) ---
    if code == "CX" or "cathay" in name_lower:
        cabin = "Y"  # Economy
        trip = "ROUNDTRIP_SEARCH" if trip_type_rt else "SINGLECITY_SEARCH"
        url = (
            f"https://www.cathaypacific.com/ibe/#/flightSearch"
            f"?action={trip}"
            f"&portAndCabinCode={dest}_{cabin}"
            f"&locale=en_HK&brand=CX"
            f"&origin={origin}&dest={dest}"
            f"&departDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        return url

    # --- Japan Airlines (JL) ---
    if code == "JL" or "japan airlines" in name_lower or "jal" in name_lower:
        url = (
            f"https://www.jal.co.jp/en/inter/fare/"
            f"?depCity={origin}&arrCity={dest}&depDate={dep_yyyymmdd}"
        )
        if trip_type_rt and ret_yyyymmdd:
            url += f"&retDate={ret_yyyymmdd}&tripType=R"
        else:
            url += "&tripType=O"
        return url

    # --- ANA (NH) ---
    if code == "NH" or "all nippon" in name_lower or "ana" in name_lower:
        trip = "R" if trip_type_rt else "O"
        url = (
            f"https://www.ana.co.jp/en/us/book-plan/fare/"
            f"?itineryType={trip}"
            f"&departureAirportCode={origin}&arrivalAirportCode={dest}"
            f"&departureDate={dep_yyyymmdd}"
        )
        if trip_type_rt and ret_yyyymmdd:
            url += f"&returnDate={ret_yyyymmdd}"
        return url

    # --- Singapore Airlines (SQ) ---
    if code == "SQ" or "singapore airlines" in name_lower:
        cabin = "Y"
        trip = "RT" if trip_type_rt else "OW"
        url = (
            f"https://www.singaporeair.com/en_UK/plan-and-book/booking/"
            f"?tripType={trip}&cabinClass={cabin}"
            f"&origin={origin}&destination={dest}"
            f"&departDate={dep_ddmmyyyy}"
        )
        if trip_type_rt and return_date:
            try:
                ret_dt2 = datetime.strptime(return_date, "%Y-%m-%d")
                url += f"&returnDate={ret_dt2.strftime('%d/%m/%Y')}"
            except ValueError:
                pass
        url += "&adults=1&children=0&infants=0"
        return url

    # --- Emirates (EK) ---
    if code == "EK" or "emirates" in name_lower:
        trip = "R" if trip_type_rt else "O"
        url = (
            f"https://www.emirates.com/flights/search"
            f"?origin={origin}&destination={dest}"
            f"&departDate={dep_ymd}&tripType={trip}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        url += "&pax=1:0:0&cabin=economy"
        return url

    # --- Qatar Airways (QR) ---
    if code == "QR" or "qatar" in name_lower:
        trip = "R" if trip_type_rt else "O"
        url = (
            f"https://booking.qatarairways.com/nsp/views/showBooking.action"
            f"?tripType={trip}"
            f"&from={origin}&to={dest}"
            f"&departing={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returning={ret_ymd}"
        url += "&adults=1&children=0&infants=0&promoCode="
        return url

    # --- Korean Air (KE) ---
    if code == "KE" or "korean air" in name_lower:
        trip = "RT" if trip_type_rt else "OW"
        url = (
            f"https://www.koreanair.com/booking/best-prices"
            f"?tripType={trip}"
            f"&departureStation={origin}&arrivalStation={dest}"
            f"&departureDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        return url

    # --- Thai Airways (TG) ---
    if code == "TG" or "thai airways" in name_lower:
        trip = "R" if trip_type_rt else "O"
        url = (
            f"https://www.thaiairways.com/en_US/booking/flight_search.page"
            f"?tripType={trip}"
            f"&from={origin}&to={dest}"
            f"&departDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        return url

    # --- EVA Air (BR) ---
    if code == "BR" or "eva air" in name_lower:
        trip = "RT" if trip_type_rt else "OW"
        url = (
            f"https://www.evaair.com/en-global/booking/flight-search/"
            f"?tripType={trip}"
            f"&origin={origin}&destination={dest}"
            f"&departureDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        return url

    # --- China Airlines (CI) ---
    if code == "CI" or "china airlines" in name_lower:
        url = (
            f"https://caleb.china-airlines.com/ibe/#/booking/search"
            f"?tripType={'RT' if trip_type_rt else 'OW'}"
            f"&departure={origin}&arrival={dest}"
            f"&departDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        return url

    # --- Delta (DL) ---
    if code == "DL" or "delta" in name_lower:
        trip = "ROUNDTRIP" if trip_type_rt else "ONE_WAY"
        url = (
            f"https://www.delta.com/flight-search/book-a-flight"
            f"?tripType={trip}"
            f"&originCity={origin}&destinationCity={dest}"
            f"&departureDate={dep_mmddyyyy}"
        )
        if trip_type_rt and return_date:
            try:
                ret_dt2 = datetime.strptime(return_date, "%Y-%m-%d")
                url += f"&returnDate={ret_dt2.strftime('%m/%d/%Y')}"
            except ValueError:
                pass
        url += "&paxCount=1&cabinFare=MAIN"
        return url

    # --- United Airlines (UA) ---
    if code == "UA" or "united" in name_lower:
        trip = "roundtrip" if trip_type_rt else "oneway"
        url = (
            f"https://www.united.com/en/us/fsr/choose-flights"
            f"?tt={trip}"
            f"&o={origin}&d={dest}"
            f"&dd={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&rd={ret_ymd}"
        url += "&px=1&taxng=1&newHP=True&clm=7&st=bestmatches"
        return url

    # --- American Airlines (AA) ---
    if code == "AA" or "american airlines" in name_lower:
        url = (
            f"https://www.aa.com/booking/find-flights"
            f"?origin={origin}&destination={dest}"
            f"&departDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}&tripType=roundTrip"
        else:
            url += "&tripType=oneWay"
        url += "&passengers=1"
        return url

    # --- British Airways (BA) ---
    if code == "BA" or "british airways" in name_lower:
        trip = "RT" if trip_type_rt else "OW"
        url = (
            f"https://www.britishairways.com/travel/book/public/en_gb"
            f"?eId=111054&from={origin}&to={dest}"
            f"&departDate={dep_ddmmyyyy}&tripType={trip}"
        )
        if trip_type_rt and return_date:
            try:
                ret_dt2 = datetime.strptime(return_date, "%Y-%m-%d")
                url += f"&returnDate={ret_dt2.strftime('%d/%m/%Y')}"
            except ValueError:
                pass
        url += "&cabinclass=M&adult=1&child=0&infant=0"
        return url

    # --- Lufthansa (LH) ---
    if code == "LH" or "lufthansa" in name_lower:
        url = (
            f"https://www.lufthansa.com/us/en/flight-search"
            f"?tripType={'R' if trip_type_rt else 'O'}"
            f"&origin={origin}&destination={dest}"
            f"&outDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&inDate={ret_ymd}"
        url += "&adults=1&children=0&infants=0&travelClass=economy"
        return url

    # --- Air France (AF) ---
    if code == "AF" or "air france" in name_lower:
        url = (
            f"https://www.airfrance.us/search/offer"
            f"?origin={origin}&destination={dest}"
            f"&outboundDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&inboundDate={ret_ymd}&tripType=ROUND_TRIP"
        else:
            url += "&tripType=ONE_WAY"
        url += "&cabinClass=ECONOMY&pax=1:0:0"
        return url

    # --- KLM (KL) ---
    if code == "KL" or "klm" in name_lower:
        url = (
            f"https://www.klm.us/search/offer"
            f"?origin={origin}&destination={dest}"
            f"&outboundDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&inboundDate={ret_ymd}&tripType=ROUND_TRIP"
        else:
            url += "&tripType=ONE_WAY"
        url += "&cabinClass=ECONOMY&pax=1:0:0"
        return url

    # --- Etihad (EY) ---
    if code == "EY" or "etihad" in name_lower:
        url = (
            f"https://www.etihad.com/en/fly-etihad/booking"
            f"?origin={origin}&destination={dest}"
            f"&departure={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&return={ret_ymd}&tripType=return"
        else:
            url += "&tripType=oneWay"
        url += "&adults=1&children=0&infants=0"
        return url

    # --- Qantas (QF) ---
    if code == "QF" or "qantas" in name_lower:
        url = (
            f"https://www.qantas.com/au/en/book-a-trip/flights.html"
            f"?from={origin}&to={dest}"
            f"&departure={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&return={ret_ymd}"
        url += "&adults=1&children=0&infants=0&className=economy"
        return url

    # --- Air Canada (AC) ---
    if code == "AC" or "air canada" in name_lower:
        url = (
            f"https://www.aircanada.com/booking/#/search"
            f"?tripType={'RT' if trip_type_rt else 'OW'}"
            f"&org0={origin}&dest0={dest}"
            f"&departDate0={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&departDate1={ret_ymd}"
        url += "&ADT=1&YTH=0&CHD=0&INF=0&marketCode=INT"
        return url

    # --- Vietnam Airlines (VN) ---
    if code == "VN" or "vietnam airlines" in name_lower:
        url = (
            f"https://www.vietnamairlines.com/en/booking/search"
            f"?tripType={'roundTrip' if trip_type_rt else 'oneWay'}"
            f"&origin={origin}&destination={dest}"
            f"&departDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        return url

    # --- Turkish Airlines (TK) ---
    if code == "TK" or "turkish" in name_lower:
        url = (
            f"https://www.turkishairlines.com/en-int/"
            f"flights/?origin={origin}&destination={dest}"
            f"&departureDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}&journeyType=RT"
        else:
            url += "&journeyType=OW"
        url += "&adult=1&child=0&infant=0&cabinClass=economy"
        return url

    # --- Asiana Airlines (OZ) ---
    if code == "OZ" or "asiana" in name_lower:
        url = (
            f"https://flyasiana.com/C/US/EN/booking/search"
            f"?tripType={'RT' if trip_type_rt else 'OW'}"
            f"&origin={origin}&destination={dest}"
            f"&departDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        return url

    # --- Scoot (TR) ---
    if code == "TR" or "scoot" in name_lower:
        url = (
            f"https://www.flyscoot.com/en/book-a-flight"
            f"?origin={origin}&destination={dest}"
            f"&departDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}&tripType=roundTrip"
        else:
            url += "&tripType=oneWay"
        return url

    # --- HK Express (UO) ---
    if code == "UO" or "hk express" in name_lower:
        url = (
            f"https://booking.hkexpress.com/en-hk/select/"
            f"?origin={origin}&destination={dest}"
            f"&departureDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        url += "&ADT=1&CHD=0&INF=0"
        return url

    # --- Peach Aviation (MM) ---
    if code == "MM" or "peach" in name_lower:
        url = (
            f"https://www.flypeach.com/en/booking/select"
            f"?origin={origin}&destination={dest}"
            f"&departDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}&tripType=RT"
        else:
            url += "&tripType=OW"
        return url

    # --- Jetstar (JQ / 3K / GK) ---
    if code in ("JQ", "3K", "GK") or "jetstar" in name_lower:
        url = (
            f"https://www.jetstar.com/au/en/booking/search"
            f"?origin={origin}&destination={dest}"
            f"&departDate={dep_ymd}"
        )
        if trip_type_rt and ret_ymd:
            url += f"&returnDate={ret_ymd}"
        url += "&adults=1&children=0&infants=0"
        return url

    # Not supported — return None
    return None


# Reverse lookup: airline name → IATA code  (used when frontend only sends name)
_AIRLINE_NAME_TO_CODE: dict[str, str] = {
    "cathay pacific": "CX", "cathay": "CX",
    "japan airlines": "JL", "jal": "JL",
    "all nippon airways": "NH", "all nippon": "NH", "ana": "NH",
    "singapore airlines": "SQ",
    "emirates": "EK",
    "qatar airways": "QR", "qatar": "QR",
    "korean air": "KE",
    "thai airways": "TG", "thai": "TG",
    "eva air": "BR", "eva": "BR",
    "china airlines": "CI",
    "delta": "DL", "delta air lines": "DL",
    "united airlines": "UA", "united": "UA",
    "american airlines": "AA", "american": "AA",
    "british airways": "BA",
    "lufthansa": "LH",
    "air france": "AF",
    "klm": "KL", "klm royal dutch": "KL",
    "etihad": "EY", "etihad airways": "EY",
    "qantas": "QF",
    "air canada": "AC",
    "vietnam airlines": "VN",
    "turkish airlines": "TK", "turkish": "TK",
    "asiana airlines": "OZ", "asiana": "OZ",
    "scoot": "TR",
    "hk express": "UO",
    "peach": "MM", "peach aviation": "MM",
    "jetstar": "JQ",
}


def _airline_name_to_code(name: str) -> str:
    """Best-effort mapping from airline display name to IATA code."""
    if not name:
        return ""
    n = name.strip().lower()
    # Exact match first
    if n in _AIRLINE_NAME_TO_CODE:
        return _AIRLINE_NAME_TO_CODE[n]
    # Substring match
    for key, code in _AIRLINE_NAME_TO_CODE.items():
        if key in n or n in key:
            return code
    return ""


def _build_fallback_agency_links(
    departure_id: Optional[str],
    arrival_id: Optional[str],
    outbound_date: Optional[str],
    return_date: Optional[str],
) -> List[dict]:
    """
    Build search-URL links for well-known travel agencies so the user always
    has multiple booking options even when SerpAPI only returns the airline official.
    These open the agency's search page pre-filled with the flight details.
    """
    if not departure_id or not arrival_id or not outbound_date:
        return []

    agencies: List[dict] = []

    # --- Google Flights ---
    gf_q = f"flights from {departure_id} to {arrival_id} on {outbound_date}"
    if return_date:
        gf_q += f" return {return_date}"
    agencies.append({
        "name": "Google Flights",
        "url": f"https://www.google.com/travel/flights?q={quote_plus(gf_q)}",
        "price": None,
        "isAirline": False,
        "logoHint": "google",
    })

    # --- Expedia ---
    exp_url = (
        f"https://www.expedia.com/Flights-search"
        f"/{departure_id}-{arrival_id}"
        f"/{outbound_date}"
    )
    if return_date:
        exp_url += f"/{return_date}"
    agencies.append({
        "name": "Expedia",
        "url": exp_url,
        "price": None,
        "isAirline": False,
        "logoHint": "expedia",
    })

    # --- Trip.com ---
    trip_url = (
        f"https://www.trip.com/flights/{departure_id.lower()}-to-{arrival_id.lower()}"
        f"/tickets-{departure_id.lower()}{arrival_id.lower()}"
        f"?dcity={departure_id}&acity={arrival_id}"
        f"&ddate={outbound_date}"
    )
    if return_date:
        trip_url += f"&rdate={return_date}&flighttype=rt"
    else:
        trip_url += "&flighttype=ow"
    agencies.append({
        "name": "Trip.com",
        "url": trip_url,
        "price": None,
        "isAirline": False,
        "logoHint": "trip",
    })

    # --- Kayak ---
    kayak_path = f"{departure_id}-{arrival_id}/{outbound_date}"
    if return_date:
        kayak_path += f"/{return_date}"
    agencies.append({
        "name": "Kayak",
        "url": f"https://www.kayak.com/flights/{kayak_path}",
        "price": None,
        "isAirline": False,
        "logoHint": "kayak",
    })

    # --- Skyscanner ---
    sky_url = (
        f"https://www.skyscanner.com/transport/flights"
        f"/{departure_id.lower()}/{arrival_id.lower()}"
        f"/{outbound_date.replace('-', '')}"
    )
    if return_date:
        sky_url += f"/{return_date.replace('-', '')}"
    agencies.append({
        "name": "Skyscanner",
        "url": sky_url,
        "price": None,
        "isAirline": False,
        "logoHint": "skyscanner",
    })

    return agencies


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
    airline_code: Optional[str] = Query(None, description="IATA airline code (e.g. CX, JL)"),
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

        # Augment with well-known travel agency search links so the user
        # always has multiple booking options (SerpAPI sometimes only returns 1)
        seen_lower = {n.lower() for n in seen_names}
        fallback_agencies = _build_fallback_agency_links(
            departure_id, arrival_id, outbound_date, return_date
        )
        for agency in fallback_agencies:
            if agency["name"].lower() not in seen_lower:
                links.append(agency)
                seen_lower.add(agency["name"].lower())

        # --- Airline Direct Deep-link ---
        # Try to build a direct airline website link pre-filled with flight details
        # so users land on the search results page, not the homepage.
        resolved_code = airline_code or ""
        if not resolved_code and airline_name:
            resolved_code = _airline_name_to_code(airline_name)
        # Also try to detect from the SerpAPI book_with names
        if not resolved_code:
            for link in links:
                if link.get("isAirline"):
                    resolved_code = _airline_name_to_code(link["name"])
                    if resolved_code:
                        break

        if resolved_code and departure_id and arrival_id and outbound_date:
            # Always prefer the airline_name passed from the frontend (user's selected airline)
            # Do NOT override with SerpAPI airline name – SerpAPI may return a different carrier
            deep_link_name = airline_name or resolved_code

            deep_url = _build_airline_deep_link(
                airline_code=resolved_code,
                airline_name=deep_link_name,
                departure_id=departure_id,
                arrival_id=arrival_id,
                outbound_date=outbound_date,
                return_date=return_date,
            )
            if deep_url:
                direct_label = f"{deep_link_name} (Direct)"
                if direct_label.lower() not in seen_lower:
                    links.insert(0, {
                        "name": direct_label,
                        "url": deep_url,
                        "price": None,
                        "isAirline": True,
                        "logoHint": deep_link_name.lower().split()[0],
                    })
                    seen_lower.add(direct_label.lower())
                    print(f"✈️  Added airline direct deep-link: {deep_link_name} → {deep_url[:80]}...")

        print(f"📋 booking-links: returning {len(links)} total links (SerpAPI + agencies + direct)")

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
