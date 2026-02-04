# Services Package

# Lazy imports to avoid circular dependencies
def get_mock_service():
    from app.services.mock_service import mock_flight_service
    return mock_flight_service

def get_gemini_service():
    from app.services.gemini_service import gemini_service
    return gemini_service

def get_amadeus_service():
    from app.services.amadeus_service import amadeus_service
    return amadeus_service

def get_serpapi_service():
    from app.services.serpapi_service import serpapi_flight_service
    return serpapi_flight_service

def get_aircraft_comfort_service():
    from app.services.aircraft_comfort_service import AircraftComfortService
    return AircraftComfortService

def get_airline_reviews_service():
    from app.services.airline_reviews_service import AirlineReviewsService
    return AirlineReviewsService

def get_scoring_service():
    from app.services.scoring_service import ScoringService
    return ScoringService
