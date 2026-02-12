# SerpAPI Google Flights Integration - Implementation Summary

## Overview
This document summarizes the SerpAPI integration for fetching real flight data from Google Flights.

## SerpAPI Engines Used

| Engine | Purpose | Backend Endpoint |
|--------|---------|------------------|
| `google_flights` | Flight search with booking tokens | `/v1/flights/search` |
| `google_flights_autocomplete` | Location/airport suggestions | `/v1/autocomplete/*` |
| `google_flights` (price_insights) | Price analysis & trends | `/v1/price-insights/*` |

## Files Changed

### Backend
1. **`.env`** - Added `SERPAPI_KEY` environment variable
2. **`app/config.py`** - Added `serpapi_key` setting
3. **`app/services/serpapi_service.py`** - SerpAPI flight, autocomplete, and price insights services
4. **`app/services/__init__.py`** - Added serpapi service exports
5. **`app/routes/flights.py`** - Flight search with SerpAPI and mock fallback
6. **`app/routes/autocomplete.py`** - NEW: Location/airport autocomplete API
7. **`app/routes/price_insights.py`** - NEW: Price insights and date comparison API
8. **`app/routes/booking.py`** - Booking redirect API
9. **`app/models.py`** - All Pydantic models including new autocomplete and price insights

### Frontend
1. **`src/api/types.ts`** - Added new SerpAPI data types
2. **`src/api/flights.ts`** - Added documentation and booking URL helper

---

## New Data Fields from SerpAPI

### Flight Model New Fields
| Field | Type | Description |
|-------|------|-------------|
| `bookingToken` | string | Token for Google Flights booking deep link |
| `airlineLogo` | string | URL to airline logo image |
| `carbonEmissions` | object | Carbon emissions data (thisFlightGrams, typicalForRouteGrams, differencePercent) |
| `flightExtensions` | string[] | Amenities like "Wi-Fi for a fee", "Average legroom (31 in)" |
| `ticketAlsoSoldBy` | string[] | Partner airlines selling this ticket |
| `oftenDelayed` | boolean | True if often delayed by 30+ min |
| `isOvernight` | boolean | Overnight flight indicator |
| `layoverDetails` | object[] | Detailed layover information |

### FlightFacilities New Fields
| Field | Type | Description |
|-------|------|-------------|
| `legroom` | string | Raw legroom string like "31 in" |
| `wifiFree` | boolean | True if WiFi is free |
| `hasUSB` | boolean | USB outlet available |
| `rawExtensions` | string[] | Raw extensions from SerpAPI |

### PriceHistory New Fields
| Field | Type | Description |
|-------|------|-------------|
| `priceLevel` | string | "low", "typical", "high" |
| `typicalPriceRange` | [number, number] | [low, high] typical price range |
| `lowestPrice` | number | Lowest price found |

### New Search Parameters
| Parameter | Type | Description |
|-----------|------|-------------|
| `returnDate` | string | Return date for round-trip |
| `adults` | number | Number of adult passengers (1-9) |
| `currency` | string | Currency code (USD, CNY, EUR) |
| `stops` | number | 0=any, 1=nonstop, 2=1 stop or fewer |

---

## Placeholders for Future Development

### 1. User Reviews (Connect to SQL Database)
The following interfaces are defined but need database connection:

```typescript
// Frontend: src/api/types.ts
interface UserReview {
  id: number;
  flightId: string;
  userId: number;
  rating: number;  // 1-5 stars
  title?: string;
  comment?: string;
  // ... dimension ratings
}

interface UserExperienceRating {
  flightId: string;
  averageRating: number;
  totalReviews: number;
  // ... rating distribution and dimension averages
}
```

```python
# Backend: app/models.py
class UserReviewCreate(BaseModel): ...
class UserReviewResponse(BaseModel): ...
class UserExperienceRating(BaseModel): ...
class FlightWithScoreExtended(BaseModel): ...
```

**TODO:** Create database tables and API routes for:
- `POST /v1/reviews` - Create review
- `GET /v1/flights/{id}/reviews` - Get flight reviews
- `GET /v1/flights/{id}/rating` - Get aggregated rating

### 2. Airline Safety Database
Currently, safety scores are set to a default of 8.0. Consider:
- Creating an airline safety database
- Using external aviation safety APIs
- Integrating with AirlineRatings.com or similar

### 3. Meal Information
SerpAPI doesn't provide meal info per flight. Consider:
- Creating a database of airline meal policies by route/cabin
- Allowing users to report meal quality

---

## API Usage Notes

### SerpAPI Rate Limits
- Free tier: 100 searches/month
- Paid plans available for higher volume

### Fallback Behavior
The system automatically falls back to mock data if:
- SerpAPI key is not configured
- SerpAPI returns an error
- Network issues occur

### Toggle Between Mock and Real Data
In `app/routes/flights.py`:
```python
USE_SERPAPI = True  # Set to False to use mock data only
```

---

## Testing the Integration

### Test SerpAPI Directly
```bash
curl "https://serpapi.com/search?engine=google_flights&departure_id=HKG&arrival_id=NRT&outbound_date=2026-03-15&currency=USD&api_key=YOUR_KEY"
```

### Test via Backend
```bash
# Start backend
cd backend
python run.py

# Test flight search
curl "http://localhost:8000/v1/flights/search?from=HKG&to=NRT&date=2026-03-15"

# Test autocomplete
curl "http://localhost:8000/v1/autocomplete/locations?q=tokyo"
curl "http://localhost:8000/v1/autocomplete/airports?q=new"

# Test price insights
curl "http://localhost:8000/v1/price-insights?from=HKG&to=NRT&outboundDate=2026-03-15"

# Test date comparison
curl "http://localhost:8000/v1/price-insights/compare?from=HKG&to=NRT&dates=2026-03-15,2026-03-16,2026-03-17"
```

---

## NEW: Autocomplete API

Get location suggestions as users type in the search box.

### `GET /v1/autocomplete/locations`

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | ✅ | Search query (e.g., "New York", "东京") |
| `gl` | string | | Country code (default: "us") |
| `hl` | string | | Language code (default: "en") |
| `excludeRegions` | boolean | | Only return cities with airports |

**Example Response:**
```json
{
  "query": "tokyo",
  "suggestions": [
    {
      "position": 1,
      "name": "Tokyo, Japan",
      "type": "city",
      "airports": [
        {"name": "Haneda Airport", "code": "HND", "distance": "11 mi"},
        {"name": "Narita International Airport", "code": "NRT", "distance": "42 mi"}
      ]
    }
  ]
}
```

### `GET /v1/autocomplete/airports`

Same as `/locations` with `excludeRegions=true` - only returns cities with airports.

---

## NEW: Price Insights API

Get price analysis for flight routes.

### `GET /v1/price-insights`

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `from` | string | ✅ | Departure airport IATA code |
| `to` | string | ✅ | Arrival airport IATA code |
| `outboundDate` | string | ✅ | Departure date (YYYY-MM-DD) |
| `returnDate` | string | | Return date (YYYY-MM-DD) |
| `currency` | string | | Currency code (default: "USD") |

**Example Response:**
```json
{
  "route": {"departure": "HKG", "arrival": "NRT", "outboundDate": "2026-03-15"},
  "insights": {
    "lowestPrice": 113,
    "priceLevel": "typical",
    "priceLevelDescription": "Prices are typical for this route",
    "typicalPriceRange": {"low": 110, "high": 190},
    "priceHistory": [{"date": "2026-01-15", "price": 108}, ...]
  },
  "currency": "USD"
}
```

**Price Levels:**
- `low` - Prices are lower than usual, good time to buy
- `typical` - Normal prices for this route
- `high` - Prices are higher than usual

### `GET /v1/price-insights/compare`

Compare prices across multiple dates.

**Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `from` | string | ✅ | Departure airport |
| `to` | string | ✅ | Arrival airport |
| `dates` | string | ✅ | Comma-separated dates (max 5) |

**Example Response:**
```json
{
  "dateComparison": [
    {"date": "2026-03-15", "lowestPrice": 113, "priceLevel": "typical"},
    {"date": "2026-03-16", "lowestPrice": 98, "priceLevel": "low"}
  ],
  "recommendation": {
    "bestDate": "2026-03-16",
    "lowestPrice": 98,
    "savings": 15
  }
}
```

---

## Questions/Information Needed

1. **Database Schema**: What is your preferred database schema for user reviews?
2. **Airline Safety Data**: Do you have a source for airline safety ratings?
3. **Additional Filters**: What other search filters would you like to expose in the UI?
4. **Booking Integration**: Do you want to implement direct booking or just redirect to Google Flights?
5. **Caching Strategy**: Should we cache SerpAPI results? If so, for how long?


---

## Next Steps

1. [x] Test the SerpAPI integration with your API key
2. [x] Implement autocomplete API for search box suggestions
3. [x] Implement price insights API for price analysis
4. [x] Implement booking redirect API
5. [ ] Design and implement user reviews database schema
6. [ ] Create API routes for user reviews
7. [ ] Add airline safety database
8. [ ] Update UI components to display new data (carbon emissions, amenities badges, etc.)
9. [ ] Integrate autocomplete into search input components
10. [ ] Add price insights visualization to frontend

---

## SerpAPI Documentation Links

- [Google Flights API](https://serpapi.com/google-flights-api)
- [Google Flights Autocomplete API](https://serpapi.com/google-flights-autocomplete-api)
- [Google Flights Price Insights](https://serpapi.com/google-flights-price-insights)
- [Google Flights Booking Options](https://serpapi.com/google-flights-booking-options)

