"""
AirEase Backend - Booking Redirect Service
Handles flight booking redirects via SerpAPI
"""

import httpx
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode

from app.config import settings


# Common airline name mappings for better matching
# Maps short names/codes to possible full names
AIRLINE_NAME_MAPPINGS = {
    "ana": ["all nippon", "all nippon airways", "ana"],
    "jal": ["japan airlines", "jal"],
    "delta": ["delta", "delta air lines"],
    "united": ["united", "united airlines"],
    "american": ["american", "american airlines"],
    "southwest": ["southwest", "southwest airlines"],
    "british airways": ["british airways", "ba"],
    "lufthansa": ["lufthansa", "lh"],
    "air france": ["air france", "af"],
    "klm": ["klm", "klm royal dutch"],
    "cathay": ["cathay", "cathay pacific"],
    "singapore": ["singapore", "singapore airlines"],
    "emirates": ["emirates"],
    "qatar": ["qatar", "qatar airways"],
    "etihad": ["etihad", "etihad airways"],
}

# Airport code to country code mapping for geolocation
# This helps SerpAPI return the correct booking options for the user's region
AIRPORT_COUNTRY_CODES = {
    # Hong Kong
    "HKG": "hk",
    # Japan
    "NRT": "jp", "HND": "jp", "KIX": "jp", "ITM": "jp", "CTS": "jp", "FUK": "jp", "NGO": "jp", "OKA": "jp",
    # China
    "PEK": "cn", "PVG": "cn", "SHA": "cn", "CAN": "cn", "SZX": "cn", "CTU": "cn", "XIY": "cn", "HGH": "cn",
    # Taiwan
    "TPE": "tw", "KHH": "tw", "TSA": "tw",
    # Singapore
    "SIN": "sg",
    # South Korea
    "ICN": "kr", "GMP": "kr", "PUS": "kr",
    # Thailand
    "BKK": "th", "DMK": "th", "HKT": "th", "CNX": "th",
    # USA
    "JFK": "us", "LAX": "us", "SFO": "us", "ORD": "us", "MIA": "us", "ATL": "us", "DFW": "us", "SEA": "us", "BOS": "us", "DEN": "us", "IAH": "us", "EWR": "us", "LGA": "us", "PHX": "us", "SAN": "us", "IAD": "us", "DCA": "us",
    # UK
    "LHR": "uk", "LGW": "uk", "STN": "uk", "MAN": "uk", "EDI": "uk",
    # France
    "CDG": "fr", "ORY": "fr", "NCE": "fr", "LYS": "fr",
    # Germany
    "FRA": "de", "MUC": "de", "TXL": "de", "BER": "de", "DUS": "de", "HAM": "de",
    # Australia
    "SYD": "au", "MEL": "au", "BNE": "au", "PER": "au",
    # UAE
    "DXB": "ae", "AUH": "ae",
    # India
    "DEL": "in", "BOM": "in", "BLR": "in", "MAA": "in", "CCU": "in", "HYD": "in",
    # Canada
    "YYZ": "ca", "YVR": "ca", "YUL": "ca", "YYC": "ca",
}


def _get_country_code_for_airport(airport_code: str) -> str:
    """Get the country code for an airport, defaults to 'us'."""
    return AIRPORT_COUNTRY_CODES.get(airport_code.upper(), "us") if airport_code else "us"


def _normalize_airline_name(name: str) -> list:
    """
    Get possible name variations for an airline.
    Returns a list of lowercase name variations to match against.
    """
    name_lower = name.lower().strip()
    
    # Check if we have predefined mappings
    for key, variations in AIRLINE_NAME_MAPPINGS.items():
        if name_lower in variations or key in name_lower:
            return variations + [name_lower]
    
    # Return the original name if no mapping found
    return [name_lower]


class BookingRedirectService:
    """
    Service for handling flight booking redirects.
    
    Uses SerpAPI to fetch booking options and generates
    redirect pages for airline booking sites.
    """
    
    BASE_URL = "https://serpapi.com/search"
    
    def __init__(self):
        self.api_key = settings.serpapi_key
    
    async def get_booking_options(
        self,
        booking_token: str,
        departure_id: Optional[str] = None,
        arrival_id: Optional[str] = None,
        outbound_date: Optional[str] = None,
        return_date: Optional[str] = None,
        currency: str = "USD"
    ) -> Dict[str, Any]:
        """
        Fetch booking options from SerpAPI using a booking_token.
        
        The booking_token requires the original search context to work properly.
        If departure_id/arrival_id/outbound_date are not provided, they will be
        extracted from the booking_token if possible.
        
        Args:
            booking_token: The booking token from a flight search result
            departure_id: Original departure airport code
            arrival_id: Original arrival airport code
            outbound_date: Original departure date (YYYY-MM-DD)
            return_date: Optional return date for round trips
            currency: Currency code
        
        Returns:
            SerpAPI response containing booking_options
        """
        # Determine geolocation based on departure airport
        gl = _get_country_code_for_airport(departure_id) if departure_id else "us"
        
        # SerpAPI booking options requires route context alongside the token
        params = {
            "engine": "google_flights",
            "booking_token": booking_token,
            "api_key": self.api_key,
            "hl": "en",
            "gl": gl,
            "currency": currency,
        }
        
        # Add required route context params
        if departure_id:
            params["departure_id"] = departure_id
        if arrival_id:
            params["arrival_id"] = arrival_id
        if outbound_date:
            params["outbound_date"] = outbound_date
        if return_date:
            params["return_date"] = return_date
            params["type"] = "1"  # Round trip
        else:
            params["type"] = "2"  # One way
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as e:
                # SerpAPI returned 400/4xx — try without route context params
                print(f"⚠️ Booking: SerpAPI HTTP {e.response.status_code} with full params, retrying token-only...")
                minimal_params = {
                    "engine": "google_flights",
                    "booking_token": booking_token,
                    "api_key": self.api_key,
                    "hl": "en",
                    "gl": gl,
                    "currency": currency,
                }
                try:
                    retry_resp = await client.get(self.BASE_URL, params=minimal_params)
                    retry_resp.raise_for_status()
                    data = retry_resp.json()
                    if data.get("booking_options"):
                        return data
                except httpx.HTTPStatusError:
                    pass
                
                # Both attempts failed — build fallback Google Flights URL
                print(f"⚠️ Booking: All SerpAPI attempts failed, building fallback URL")
                gf_url = self._build_google_flights_url(departure_id, arrival_id, outbound_date, return_date)
                return {
                    "error": f"Booking service returned {e.response.status_code}",
                    "_google_flights_url": gf_url
                }
            
            # If SerpAPI returned an error in the body (HTTP 200 but no results),
            # retry without route context params (may help for return-leg tokens)
            if "error" in data and not data.get("booking_options"):
                print(f"⚠️ Booking: SerpAPI body error — {data.get('error')}, retrying token-only...")
                minimal_params = {
                    "engine": "google_flights",
                    "booking_token": booking_token,
                    "api_key": self.api_key,
                    "hl": "en",
                    "gl": gl,
                    "currency": currency,
                }
                try:
                    retry_resp = await client.get(self.BASE_URL, params=minimal_params)
                    retry_resp.raise_for_status()
                    retry_data = retry_resp.json()
                    if retry_data.get("booking_options"):
                        return retry_data
                except Exception:
                    pass
                
                # Still no luck — store Google Flights URL for fallback
                gf_url = data.get("search_metadata", {}).get("google_flights_url", "")
                if not gf_url:
                    gf_url = self._build_google_flights_url(departure_id, arrival_id, outbound_date, return_date)
                data["_google_flights_url"] = gf_url
            
            return data
    
    def _build_google_flights_url(
        self,
        departure_id: Optional[str] = None,
        arrival_id: Optional[str] = None,
        outbound_date: Optional[str] = None,
        return_date: Optional[str] = None
    ) -> str:
        """Build a direct Google Flights search URL as fallback."""
        base = "https://www.google.com/travel/flights"
        if departure_id and arrival_id and outbound_date:
            # Google Flights URL format: /flights/DEP-ARR/2026-02-28
            path = f"/flights/{departure_id}-{arrival_id}/{outbound_date}"
            if return_date:
                path += f"/{return_date}"
            return base + path
        return base
    
    def find_booking_option(
        self,
        booking_options: list,
        airline_name: Optional[str] = None,
        prefer_expedia: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Find the best matching booking option.
        
        Priority when prefer_expedia=False (same airline):
          1. Official airline website matching the airline_name
          2. Any official airline website (airline=True)
          3. Expedia if available
          4. Fall back to first available option
        
        Priority when prefer_expedia=True (different airlines / aggregator):
          1. Expedia if available
          2. Fall back to first available option
        
        Args:
            booking_options: List of booking options from SerpAPI
            airline_name: Optional airline name to match (e.g., "ANA", "Delta")
            prefer_expedia: If True, skip airline matching and prefer Expedia
        
        Returns:
            The selected booking option, or None if not found
        """
        if not booking_options:
            return None
        
        # Helper: check if option is Expedia
        def _is_expedia(option: Dict[str, Any]) -> bool:
            together = option.get("together", {})
            book_with = together.get("book_with", "").lower()
            return "expedia" in book_with
        
        if prefer_expedia:
            # AGGREGATOR MODE: prefer Expedia, else first option
            for option in booking_options:
                if _is_expedia(option):
                    return option
            # No Expedia found → fall back to first option
            return booking_options[0] if booking_options else None
        
        # AIRLINE MODE: try official airline first, then Expedia, then first
        
        # Get name variations for matching
        search_names = _normalize_airline_name(airline_name) if airline_name else []
        
        def _matches_airline(book_with: str) -> bool:
            """Check if book_with matches any of the search name variations."""
            book_with_lower = book_with.lower()
            return any(name in book_with_lower for name in search_names)
        
        # First priority: Official airline website matching the airline name
        if search_names:
            for option in booking_options:
                together = option.get("together", {})
                book_with = together.get("book_with", "")
                is_official_airline = together.get("airline", False)
                
                # Prefer official airline booking that matches the airline name
                if is_official_airline and _matches_airline(book_with):
                    return option
        
        # Second priority: Any official airline website (airline=True)
        for option in booking_options:
            together = option.get("together", {})
            if together.get("airline", False):
                return option
        
        # Third priority: Expedia
        for option in booking_options:
            if _is_expedia(option):
                return option
        
        # Fall back to first option
        return booking_options[0] if booking_options else None
    
    def extract_booking_request(
        self,
        booking_option: Dict[str, Any],
        prefer_departing: bool = False,
        prefer_returning: bool = False
    ) -> Optional[Tuple[str, str]]:
        """
        Extract booking request URL and POST data from a booking option.
        
        Handles both "together" bookings and "separate_tickets" scenarios.
        
        Args:
            booking_option: A single booking option from SerpAPI
            prefer_departing: If True, prefer departing flight booking
            prefer_returning: If True, prefer returning flight booking
        
        Returns:
            Tuple of (url, post_data) or None if not available
        """
        # Check if separate tickets
        if booking_option.get("separate_tickets", False):
            # For separate tickets, we need to handle departing and returning
            if prefer_returning:
                returning = booking_option.get("returning", {})
                booking_request = returning.get("booking_request")
            else:
                # Default to departing
                departing = booking_option.get("departing", {})
                booking_request = departing.get("booking_request")
        else:
            # Standard "together" booking
            together = booking_option.get("together", {})
            booking_request = together.get("booking_request")
        
        if not booking_request:
            # Check for booking_phone (phone-only booking)
            together = booking_option.get("together", {})
            if together.get("booking_phone"):
                return None  # No redirect available, phone booking only
            return None
        
        url = booking_request.get("url")
        post_data = booking_request.get("post_data", "")
        
        if not url:
            return None
        
        return (url, post_data)
    
    def generate_redirect_html(
        self,
        url: str,
        post_data: str,
        airline_name: str = "Airline",
        price: Optional[float] = None
    ) -> str:
        """
        Generate HTML page with auto-submit form for POST redirect.
        
        The page includes a hidden form with the POST data that
        automatically submits on page load.
        
        Args:
            url: Target URL for the form
            post_data: URL-encoded POST data string
            airline_name: Airline name for display
            price: Optional price for display
        
        Returns:
            HTML string for the redirect page
        """
        # Parse post_data into input fields
        # post_data is typically a single key-value like "u=<encoded_data>"
        input_fields = ""
        
        if post_data:
            # Split by & for multiple params
            pairs = post_data.split("&") if "&" in post_data else [post_data]
            for pair in pairs:
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    # Escape HTML special characters
                    escaped_value = value.replace('"', '&quot;').replace("'", "&#39;")
                    input_fields += f'<input type="hidden" name="{key}" value="{escaped_value}">\n'
        
        price_display = f"${price:.0f}" if price else ""
        
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Redirecting to {airline_name}...</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            max-width: 400px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        .plane-icon {{
            font-size: 48px;
            margin-bottom: 20px;
            animation: fly 2s infinite ease-in-out;
        }}
        @keyframes fly {{
            0%, 100% {{ transform: translateX(-10px) rotate(-5deg); }}
            50% {{ transform: translateX(10px) rotate(5deg); }}
        }}
        .spinner {{
            width: 40px;
            height: 40px;
            border: 4px solid #e0e0e0;
            border-top-color: #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }}
        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}
        h1 {{
            color: #333;
            font-size: 24px;
            margin-bottom: 10px;
        }}
        .airline {{
            color: #667eea;
            font-weight: bold;
        }}
        .price {{
            font-size: 28px;
            color: #667eea;
            font-weight: bold;
            margin: 15px 0;
        }}
        p {{
            color: #666;
            font-size: 14px;
            line-height: 1.6;
        }}
        .manual-link {{
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }}
        .manual-link a {{
            color: #667eea;
            text-decoration: none;
        }}
        .manual-link a:hover {{
            text-decoration: underline;
        }}
        noscript {{
            display: block;
            margin-top: 20px;
        }}
        .noscript-btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 30px;
            font-size: 16px;
            border-radius: 8px;
            cursor: pointer;
        }}
        .noscript-btn:hover {{
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="plane-icon">✈️</div>
        <h1>Redirecting to <span class="airline">{airline_name}</span></h1>
        {f'<div class="price">{price_display}</div>' if price_display else ''}
        <div class="spinner"></div>
        <p>Please wait while we transfer you to the booking page...</p>
        <p style="margin-top: 10px; color: #999; font-size: 12px;">
            You'll be able to complete your booking on the airline's official website.
        </p>
        
        <noscript>
            <p style="color: #e53e3e; margin-bottom: 15px;">
                JavaScript is disabled. Please click the button below to continue.
            </p>
            <form id="bookingForm" action="{url}" method="POST">
                {input_fields}
                <button type="submit" class="noscript-btn">Continue to {airline_name}</button>
            </form>
        </noscript>
        
        <div class="manual-link">
            <p style="font-size: 12px; color: #999;">
                Not redirected? 
                <a href="javascript:document.getElementById('bookingForm').submit();">
                    Click here
                </a>
            </p>
        </div>
    </div>
    
    <!-- Hidden form for POST redirect -->
    <form id="bookingForm" action="{url}" method="POST" style="display: none;">
        {input_fields}
    </form>
    
    <script>
        // Auto-submit the form after a brief delay for UX
        window.onload = function() {{
            setTimeout(function() {{
                document.getElementById('bookingForm').submit();
            }}, 1500);
        }};
    </script>
</body>
</html>
"""
    
    def generate_error_html(
        self,
        error_message: str,
        details: str = ""
    ) -> str:
        """
        Generate HTML error page when booking redirect fails.
        
        Args:
            error_message: Main error message
            details: Optional detailed error info
        
        Returns:
            HTML string for the error page
        """
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Booking Unavailable - AirEase</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            max-width: 450px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        .error-icon {{
            font-size: 48px;
            margin-bottom: 20px;
        }}
        h1 {{
            color: #333;
            font-size: 22px;
            margin-bottom: 15px;
        }}
        .error-message {{
            color: #e53e3e;
            font-size: 16px;
            margin-bottom: 10px;
        }}
        .details {{
            color: #999;
            font-size: 14px;
            margin-bottom: 25px;
            line-height: 1.6;
        }}
        .back-btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 30px;
            font-size: 16px;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }}
        .back-btn:hover {{
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="error-icon">😔</div>
        <h1>Booking Unavailable</h1>
        <p class="error-message">{error_message}</p>
        <p class="details">{details}</p>
        <a href="javascript:history.back();" class="back-btn">← Go Back</a>
    </div>
</body>
</html>
"""
    
    def generate_google_flights_fallback_html(self, google_flights_url: str) -> str:
        """Generate HTML page that redirects user to Google Flights when SerpAPI booking fails."""
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Redirecting to Google Flights - AirEase</title>
    <meta http-equiv="refresh" content="3;url={google_flights_url}">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        .icon {{ font-size: 48px; margin-bottom: 20px; }}
        h1 {{ color: #333; font-size: 22px; margin-bottom: 15px; }}
        .message {{
            color: #666;
            font-size: 16px;
            margin-bottom: 25px;
            line-height: 1.6;
        }}
        .redirect-btn {{
            background: linear-gradient(135deg, #4285f4 0%, #34a853 100%);
            color: white;
            border: none;
            padding: 14px 35px;
            font-size: 16px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-bottom: 15px;
        }}
        .redirect-btn:hover {{ opacity: 0.9; }}
        .auto-note {{ color: #999; font-size: 13px; }}
        .spinner {{
            border: 3px solid #f3f3f3;
            border-top: 3px solid #4285f4;
            border-radius: 50%;
            width: 30px;
            height: 30px;
            animation: spin 1s linear infinite;
            margin: 15px auto;
        }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✈️</div>
        <h1>Redirecting to Google Flights</h1>
        <p class="message">Direct booking isn't available for this flight segment.<br>We're taking you to Google Flights to complete your booking.</p>
        <div class="spinner"></div>
        <a href="{google_flights_url}" class="redirect-btn">Go to Google Flights →</a>
        <p class="auto-note">You'll be redirected automatically in 3 seconds...</p>
    </div>
</body>
</html>
"""

    def generate_phone_booking_html(
        self,
        airline_name: str,
        phone_number: str,
        price: Optional[float] = None,
        fee: Optional[float] = None
    ) -> str:
        """
        Generate HTML page for phone-only bookings.
        """
        price_display = f"${price:.0f}" if price else ""
        fee_note = f"<p class='fee-note'>Note: Phone booking fee may apply (~${fee:.0f})</p>" if fee else ""
        
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Phone Booking - {airline_name}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            max-width: 400px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        .phone-icon {{
            font-size: 48px;
            margin-bottom: 20px;
        }}
        h1 {{
            color: #333;
            font-size: 22px;
            margin-bottom: 10px;
        }}
        .airline {{
            color: #667eea;
            font-weight: bold;
        }}
        .price {{
            font-size: 28px;
            color: #667eea;
            font-weight: bold;
            margin: 15px 0;
        }}
        .phone-number {{
            font-size: 24px;
            font-weight: bold;
            color: #333;
            margin: 20px 0;
            padding: 15px;
            background: #f5f5f5;
            border-radius: 12px;
        }}
        .phone-number a {{
            color: #667eea;
            text-decoration: none;
        }}
        p {{
            color: #666;
            font-size: 14px;
            line-height: 1.6;
        }}
        .fee-note {{
            color: #999;
            font-size: 12px;
            margin-top: 15px;
        }}
        .back-btn {{
            margin-top: 25px;
            background: transparent;
            color: #667eea;
            border: 2px solid #667eea;
            padding: 10px 25px;
            font-size: 14px;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }}
        .back-btn:hover {{
            background: #667eea;
            color: white;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="phone-icon">📞</div>
        <h1>Book with <span class="airline">{airline_name}</span></h1>
        {f'<div class="price">{price_display}</div>' if price_display else ''}
        <p>This flight is only available for phone booking:</p>
        <div class="phone-number">
            <a href="tel:{phone_number}">{phone_number}</a>
        </div>
        <p>Call the number above to complete your booking with the airline directly.</p>
        {fee_note}
        <a href="javascript:history.back();" class="back-btn">← Go Back</a>
    </div>
</body>
</html>
"""


# Singleton instance
booking_redirect_service = BookingRedirectService()
