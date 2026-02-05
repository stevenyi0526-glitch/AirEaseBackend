"""
AirEase Backend - Booking Redirect Service
Handles flight booking redirects via SerpAPI
"""

import httpx
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode

from app.config import settings


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
        booking_token: str
    ) -> Dict[str, Any]:
        """
        Fetch booking options from SerpAPI using a booking_token.
        
        Args:
            booking_token: The booking token from a flight search result
        
        Returns:
            SerpAPI response containing booking_options
        """
        params = {
            "engine": "google_flights",
            "booking_token": booking_token,
            "api_key": self.api_key,
            "hl": "en",
            "gl": "us",
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            return response.json()
    
    def find_booking_option(
        self,
        booking_options: list,
        airline_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find the best matching booking option.
        
        Priority:
        1. Match by airline_name if provided
        2. Prefer direct airline options (airline=True)
        3. Fall back to first available option
        
        Args:
            booking_options: List of booking options from SerpAPI
            airline_name: Optional airline name to match
        
        Returns:
            The selected booking option, or None if not found
        """
        if not booking_options:
            return None
        
        # Normalize airline name for matching
        search_name = airline_name.lower() if airline_name else None
        
        # First pass: look for exact airline match in "together" option
        if search_name:
            for option in booking_options:
                together = option.get("together", {})
                book_with = together.get("book_with", "").lower()
                
                # Check if the seller name contains the airline name
                if search_name in book_with:
                    return option
        
        # Second pass: prefer direct airline options (airline=True)
        for option in booking_options:
            together = option.get("together", {})
            if together.get("airline", False):
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
    
    def generate_phone_booking_html(
        self,
        airline_name: str,
        phone_number: str,
        price: Optional[float] = None,
        fee: Optional[float] = None
    ) -> str:
        """
        Generate HTML page for phone-only bookings.
        
        Args:
            airline_name: Airline name
            phone_number: Booking phone number
            price: Optional price
            fee: Optional phone service fee
        
        Returns:
            HTML string for the phone booking page
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
