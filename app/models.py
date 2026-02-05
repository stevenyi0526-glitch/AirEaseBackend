"""
AirEase Backend - Pydantic Models
数据模型定义
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime, date
from enum import Enum


# ============================================================
# Enums
# ============================================================

class CabinClass(str, Enum):
    """舱位类型"""
    ECONOMY = "economy"
    ECONOMY_CN = "经济舱"
    BUSINESS = "business"
    BUSINESS_CN = "公务舱"
    FIRST = "first"
    FIRST_CN = "头等舱"


class PriceTrend(str, Enum):
    """价格趋势"""
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"


class FacilityStatus(str, Enum):
    """设施状态"""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ReportCategory(str, Enum):
    """反馈类别 - Feedback/Report Categories"""
    AIRCRAFT_MISMATCH = "aircraft_mismatch"      # 机型不符
    MISSING_FACILITIES = "missing_facilities"    # 设施缺失
    PRICE_ERROR = "price_error"                  # 价格错误
    FLIGHT_INFO_ERROR = "flight_info_error"      # 航班信息错误
    TIME_INACCURATE = "time_inaccurate"          # 时间不准确
    OTHER = "other"                              # 其他


class ReportStatus(str, Enum):
    """反馈状态 - Report Status"""
    PENDING = "pending"        # 待处理
    REVIEWED = "reviewed"      # 已审核
    RESOLVED = "resolved"      # 已解决
    DISMISSED = "dismissed"    # 已驳回


# ============================================================
# Flight Models
# ============================================================

class Flight(BaseModel):
    """航班基础信息"""
    id: str
    flight_number: str = Field(alias="flightNumber")
    airline: str
    airline_code: str = Field(alias="airlineCode")
    departure_city: str = Field(alias="departureCity")
    departure_city_code: str = Field(alias="departureCityCode")
    departure_airport: str = Field(alias="departureAirport")
    departure_airport_code: str = Field(alias="departureAirportCode")
    departure_time: datetime = Field(alias="departureTime")
    arrival_city: str = Field(alias="arrivalCity")
    arrival_city_code: str = Field(alias="arrivalCityCode")
    arrival_airport: str = Field(alias="arrivalAirport")
    arrival_airport_code: str = Field(alias="arrivalAirportCode")
    arrival_time: datetime = Field(alias="arrivalTime")
    duration_minutes: int = Field(alias="durationMinutes")
    stops: int = 0
    stop_cities: Optional[List[str]] = Field(default=None, alias="stopCities")
    cabin: str
    aircraft_model: Optional[str] = Field(default=None, alias="aircraftModel")
    price: float
    currency: str = "CNY"
    seats_remaining: Optional[int] = Field(default=None, alias="seatsRemaining")
    
    # === NEW FIELDS FROM SERPAPI ===
    # Booking and purchase link token
    booking_token: Optional[str] = Field(default=None, alias="bookingToken")
    
    # Departure token for round trip - used to fetch return flights
    departure_token: Optional[str] = Field(default=None, alias="departureToken")
    
    # Airline branding
    airline_logo: Optional[str] = Field(default=None, alias="airlineLogo")
    
    # Carbon emissions data
    carbon_emissions: Optional[dict] = Field(default=None, alias="carbonEmissions")
    
    # Additional flight details from SerpAPI
    flight_extensions: Optional[List[str]] = Field(default=None, alias="flightExtensions")
    ticket_also_sold_by: Optional[List[str]] = Field(default=None, alias="ticketAlsoSoldBy")
    often_delayed: Optional[bool] = Field(default=None, alias="oftenDelayed")
    is_overnight: Optional[bool] = Field(default=None, alias="isOvernight")
    
    # Layover details
    layover_details: Optional[List[dict]] = Field(default=None, alias="layoverDetails")
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# ============================================================
# Score Models
# ============================================================

class ScoreDimensions(BaseModel):
    """评分维度"""
    reliability: float = Field(ge=0, le=10)  # On-time performance score (from airline OTP data)
    comfort: float = Field(ge=0, le=10)
    service: float = Field(ge=0, le=10)
    value: float = Field(ge=0, le=10)


class CabinClassScores(BaseModel):
    """Scores separated by cabin class"""
    economy: ScoreDimensions
    business: ScoreDimensions
    overall: ScoreDimensions  # Weighted average or selected cabin


class ScoreExplanation(BaseModel):
    """评分解释"""
    dimension: str
    title: str
    detail: str
    is_positive: bool = Field(alias="isPositive")
    cabin_class: Optional[str] = Field(default=None, alias="cabinClass")  # "economy", "business", or None for both
    
    class Config:
        populate_by_name = True


class UserReviewRatings(BaseModel):
    """Nested ratings object for easier frontend access"""
    food: int
    ground_service: int = Field(alias="groundService")
    seat_comfort: int = Field(alias="seatComfort")
    service: int
    overall: Optional[float] = None
    
    class Config:
        populate_by_name = True


class UserReviewSummary(BaseModel):
    """User review for display"""
    title: str
    review: str
    food_rating: int = Field(alias="foodRating")
    ground_service_rating: int = Field(alias="groundServiceRating")
    seat_comfort_rating: int = Field(alias="seatComfortRating")
    service_rating: int = Field(alias="serviceRating")
    recommended: bool
    travel_type: str = Field(alias="travelType")
    route: str
    aircraft: Optional[str] = None
    cabin_type: Optional[str] = Field(default=None, alias="cabinType")
    ratings: Optional[UserReviewRatings] = None
    
    class Config:
        populate_by_name = True


class ServiceHighlights(BaseModel):
    """Service dimension highlights"""
    highlights: List[str] = []
    economy_highlights: Optional[List[str]] = Field(default=None, alias="economyHighlights")
    business_highlights: Optional[List[str]] = Field(default=None, alias="businessHighlights")
    food_rating: Optional[float] = Field(default=None, alias="foodRating")
    ground_service_rating: Optional[float] = Field(default=None, alias="groundServiceRating")
    seat_comfort_rating: Optional[float] = Field(default=None, alias="seatComfortRating")
    service_rating: Optional[float] = Field(default=None, alias="serviceRating")
    recommendation_rate: Optional[float] = Field(default=None, alias="recommendationRate")
    review_count: int = Field(default=0, alias="reviewCount")
    
    class Config:
        populate_by_name = True


class FlightScore(BaseModel):
    """航班评分"""
    overall_score: float = Field(alias="overallScore", ge=0, le=10)
    dimensions: ScoreDimensions
    # NEW: Separate scores by cabin class
    economy_dimensions: Optional[ScoreDimensions] = Field(default=None, alias="economyDimensions")
    business_dimensions: Optional[ScoreDimensions] = Field(default=None, alias="businessDimensions")
    highlights: List[str] = []
    explanations: List[ScoreExplanation] = []
    # NEW: Service highlights with ratings breakdown
    service_highlights: Optional[ServiceHighlights] = Field(default=None, alias="serviceHighlights")
    # NEW: User reviews
    user_reviews: Optional[List[UserReviewSummary]] = Field(default=None, alias="userReviews")
    persona_weights_applied: str = Field(alias="personaWeightsApplied", default="")
    
    class Config:
        populate_by_name = True


# ============================================================
# Facilities Models
# ============================================================

class FlightFacilities(BaseModel):
    """机上设施"""
    has_wifi: Optional[bool] = Field(default=None, alias="hasWifi")
    has_power: Optional[bool] = Field(default=None, alias="hasPower")
    seat_pitch_inches: Optional[int] = Field(default=None, alias="seatPitchInches")
    seat_pitch_category: Optional[str] = Field(default=None, alias="seatPitchCategory")
    has_ife: Optional[bool] = Field(default=None, alias="hasIFE")
    ife_type: Optional[str] = Field(default=None, alias="ifeType")
    meal_included: Optional[bool] = Field(default=None, alias="mealIncluded")
    meal_type: Optional[str] = Field(default=None, alias="mealType")
    
    # === NEW FIELDS FROM SERPAPI ===
    legroom: Optional[str] = Field(default=None, description="Raw legroom string like '31 in'")
    wifi_free: Optional[bool] = Field(default=None, alias="wifiFree")
    has_usb: Optional[bool] = Field(default=None, alias="hasUSB")
    raw_extensions: Optional[List[str]] = Field(default=None, alias="rawExtensions")
    
    class Config:
        populate_by_name = True


# ============================================================
# Price History Models
# ============================================================

class PricePoint(BaseModel):
    """价格点"""
    date: str
    price: float


class PriceHistory(BaseModel):
    """价格历史"""
    flight_id: str = Field(alias="flightId")
    points: List[PricePoint]
    current_price: float = Field(alias="currentPrice")
    trend: PriceTrend
    
    # === NEW FIELDS FROM SERPAPI PRICE INSIGHTS ===
    price_level: Optional[str] = Field(default=None, alias="priceLevel")  # "low", "typical", "high"
    typical_price_range: Optional[List[float]] = Field(default=None, alias="typicalPriceRange")  # [low, high]
    lowest_price: Optional[float] = Field(default=None, alias="lowestPrice")
    
    class Config:
        populate_by_name = True


# ============================================================
# Combined Models
# ============================================================

class FlightWithScore(BaseModel):
    """航班 + 评分 + 设施"""
    flight: Flight
    score: FlightScore
    facilities: FlightFacilities


class FlightDetail(BaseModel):
    """航班详情（含价格历史）"""
    flight: Flight
    score: FlightScore
    facilities: FlightFacilities
    price_history: PriceHistory = Field(alias="priceHistory")
    
    class Config:
        populate_by_name = True


# ============================================================
# API Request/Response Models
# ============================================================

class SearchQuery(BaseModel):
    """搜索请求"""
    from_city: str = Field(alias="from")
    to_city: str = Field(alias="to")
    date: str
    cabin: str = "economy"
    
    class Config:
        populate_by_name = True


class SearchMeta(BaseModel):
    """搜索元数据"""
    total: int
    search_id: str = Field(alias="searchId")
    cached_at: Optional[datetime] = Field(default=None, alias="cachedAt")
    restricted_count: int = Field(default=0, alias="restrictedCount")
    is_authenticated: bool = Field(default=False, alias="isAuthenticated")
    limit: int = Field(default=40, alias="limit")
    offset: int = Field(default=0, alias="offset")
    has_more: bool = Field(default=False, alias="hasMore")

    class Config:
        populate_by_name = True


class PriceInsights(BaseModel):
    """Google Flights价格洞察"""
    lowest_price: Optional[float] = Field(default=None, alias="lowestPrice")
    price_level: Optional[str] = Field(default=None, alias="priceLevel")  # "low", "typical", "high"
    typical_price_range: Optional[List[int]] = Field(default=None, alias="typicalPriceRange")
    price_history: Optional[List[List[int]]] = Field(default=None, alias="priceHistory")  # [[timestamp, price], ...]
    
    class Config:
        populate_by_name = True


class FlightSearchResponse(BaseModel):
    """航班搜索响应"""
    flights: List[FlightWithScore]
    meta: SearchMeta
    price_insights: Optional[PriceInsights] = Field(default=None, alias="priceInsights")
    
    class Config:
        populate_by_name = True


class RoundTripSearchResponse(BaseModel):
    """Round trip search response with separate departure and return flights"""
    departure_flights: List[FlightWithScore] = Field(alias="departureFlights")
    return_flights: List[FlightWithScore] = Field(alias="returnFlights")
    meta: SearchMeta
    departure_price_insights: Optional[PriceInsights] = Field(default=None, alias="departurePriceInsights")
    return_price_insights: Optional[PriceInsights] = Field(default=None, alias="returnPriceInsights")
    
    class Config:
        populate_by_name = True


class AISearchRequest(BaseModel):
    """AI搜索请求"""
    query: str
    persona: Optional[str] = None


class AISearchResponse(BaseModel):
    """AI搜索响应"""
    parsed_query: Optional[SearchQuery] = Field(alias="parsedQuery")
    confidence: float
    original_query: str = Field(alias="originalQuery")
    suggestions: List[str] = []
    
    class Config:
        populate_by_name = True


class ErrorResponse(BaseModel):
    """错误响应"""
    error: str
    detail: Optional[str] = None
    code: int


# ============================================================
# User Authentication Models
# ============================================================

class UserLabel(str, Enum):
    """User persona labels"""
    BUSINESS = "business"
    FAMILY = "family"
    STUDENT = "student"


class UserBase(BaseModel):
    """User base model"""
    email: EmailStr
    username: str = Field(min_length=3, max_length=50)


class UserCreate(UserBase):
    """User registration request"""
    password: str = Field(min_length=6)
    label: UserLabel = UserLabel.BUSINESS


class UserLogin(BaseModel):
    """User login request"""
    email: EmailStr
    password: str


class VerificationRequest(BaseModel):
    """Email verification code submission"""
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)


class ResendVerificationRequest(BaseModel):
    """Request to resend verification code"""
    email: EmailStr


class VerificationResponse(BaseModel):
    """Response for verification initiation"""
    message: str
    email: str
    expires_in_minutes: int = Field(alias="expiresInMinutes")
    
    class Config:
        populate_by_name = True


class UserUpdate(BaseModel):
    """User profile update request"""
    username: Optional[str] = Field(default=None, min_length=3, max_length=50)
    label: Optional[UserLabel] = None


class UserResponse(UserBase):
    """User response (no password)"""
    id: int
    created_at: datetime
    is_active: bool = True
    label: str = "business"
    family_id: str = Field(alias="familyId")

    class Config:
        from_attributes = True
        populate_by_name = True


class Token(BaseModel):
    """JWT token response"""
    access_token: str = Field(alias="accessToken")
    token_type: str = Field(default="bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn")  # seconds
    user: UserResponse

    class Config:
        populate_by_name = True


class TokenData(BaseModel):
    """Decoded token data"""
    user_id: int
    email: str
    exp: datetime


# ============================================================
# Favorites Models
# ============================================================

class FavoriteCreate(BaseModel):
    """Create favorite request"""
    flight_id: str = Field(alias="flightId")
    flight_number: str = Field(alias="flightNumber")
    airline: str
    departure_city: str = Field(alias="departureCity")
    arrival_city: str = Field(alias="arrivalCity")
    departure_time: datetime = Field(alias="departureTime")
    price: int
    score: int
    
    class Config:
        populate_by_name = True


class FavoriteResponse(BaseModel):
    """Favorite response"""
    id: int
    flight_id: str = Field(alias="flightId")
    flight_number: str = Field(alias="flightNumber")
    airline: str
    departure_city: str = Field(alias="departureCity")
    arrival_city: str = Field(alias="arrivalCity")
    departure_time: datetime = Field(alias="departureTime")
    price: int
    score: int
    created_at: datetime = Field(alias="createdAt")
    
    class Config:
        populate_by_name = True
        from_attributes = True


# ============================================================
# Travelers Models
# ============================================================

class TravelerCreate(BaseModel):
    """Create traveler request"""
    first_name: str = Field(alias="firstName")
    middle_name: Optional[str] = Field(default=None, alias="middleName")
    last_name: str = Field(alias="lastName")
    passport_number: Optional[str] = Field(default=None, alias="passportNumber")
    dob: Optional[date] = None
    nationality: Optional[str] = None
    gender: Optional[str] = None
    
    class Config:
        populate_by_name = True


class TravelerUpdate(BaseModel):
    """Update traveler request"""
    first_name: Optional[str] = Field(default=None, alias="firstName")
    middle_name: Optional[str] = Field(default=None, alias="middleName")
    last_name: Optional[str] = Field(default=None, alias="lastName")
    passport_number: Optional[str] = Field(default=None, alias="passportNumber")
    dob: Optional[date] = None
    nationality: Optional[str] = None
    gender: Optional[str] = None
    
    class Config:
        populate_by_name = True


class TravelerResponse(BaseModel):
    """Traveler response"""
    id: int
    family_id: str = Field(alias="familyId")
    first_name: str = Field(alias="firstName")
    middle_name: Optional[str] = Field(default=None, alias="middleName")
    last_name: str = Field(alias="lastName")
    passport_number: Optional[str] = Field(default=None, alias="passportNumber")
    dob: Optional[date] = None
    nationality: Optional[str] = None
    gender: Optional[str] = None
    is_primary: bool = Field(default=False, alias="isPrimary")
    created_at: datetime = Field(alias="createdAt")
    
    class Config:
        populate_by_name = True
        from_attributes = True


# ============================================================
# City Search Models
# ============================================================

class CitySearchResult(BaseModel):
    """City search result from Google Places API"""
    place_id: str = Field(alias="placeId")
    city: str
    country: str
    airport_code: Optional[str] = Field(default=None, alias="airportCode")
    display_name: str = Field(alias="displayName")
    
    class Config:
        populate_by_name = True


# ============================================================
# Search History Models
# ============================================================

class SearchHistoryCreate(BaseModel):
    """Create search history request"""
    departure_city: str = Field(alias="departure_city")
    arrival_city: str = Field(alias="arrival_city")
    departure_date: date = Field(alias="departure_date")
    return_date: Optional[date] = Field(default=None, alias="return_date")
    passengers: int = 1
    cabin_class: str = Field(default="economy", alias="cabin_class")
    
    class Config:
        populate_by_name = True


class SearchHistoryResponse(BaseModel):
    """Search history response"""
    id: int
    departure_city: str
    arrival_city: str
    departure_date: date
    return_date: Optional[date] = None
    passengers: int
    cabin_class: str
    created_at: datetime
    
    class Config:
        populate_by_name = True
        from_attributes = True


# ============================================================
# User Review Models (PLACEHOLDERS - Connect to SQL Database)
# ============================================================
# TODO: Connect these models to your SQL database with flight models and user reviews

class UserReviewCreate(BaseModel):
    """Create user review request - PLACEHOLDER"""
    flight_id: str = Field(alias="flightId")
    rating: int = Field(ge=1, le=5, description="Rating 1-5 stars")
    title: Optional[str] = None
    comment: Optional[str] = None
    travel_date: Optional[date] = Field(default=None, alias="travelDate")
    cabin_class: Optional[str] = Field(default=None, alias="cabinClass")
    
    # Review dimensions (1-5 each)
    seat_comfort: Optional[int] = Field(default=None, ge=1, le=5, alias="seatComfort")
    crew_service: Optional[int] = Field(default=None, ge=1, le=5, alias="crewService")
    entertainment: Optional[int] = Field(default=None, ge=1, le=5)
    food_beverage: Optional[int] = Field(default=None, ge=1, le=5, alias="foodBeverage")
    value_for_money: Optional[int] = Field(default=None, ge=1, le=5, alias="valueForMoney")
    
    class Config:
        populate_by_name = True


class UserReviewResponse(BaseModel):
    """User review response - PLACEHOLDER"""
    id: int
    flight_id: str = Field(alias="flightId")
    user_id: int = Field(alias="userId")
    rating: int
    title: Optional[str] = None
    comment: Optional[str] = None
    travel_date: Optional[date] = Field(default=None, alias="travelDate")
    cabin_class: Optional[str] = Field(default=None, alias="cabinClass")
    verified: bool = False
    helpful: int = 0
    created_at: datetime = Field(alias="createdAt")
    
    # Review dimensions
    seat_comfort: Optional[int] = Field(default=None, alias="seatComfort")
    crew_service: Optional[int] = Field(default=None, alias="crewService")
    entertainment: Optional[int] = None
    food_beverage: Optional[int] = Field(default=None, alias="foodBeverage")
    value_for_money: Optional[int] = Field(default=None, alias="valueForMoney")
    
    class Config:
        populate_by_name = True
        from_attributes = True


class UserExperienceRating(BaseModel):
    """Aggregated user experience rating for a flight - PLACEHOLDER"""
    flight_id: str = Field(alias="flightId")
    average_rating: float = Field(alias="averageRating")
    total_reviews: int = Field(alias="totalReviews")
    rating_distribution: dict = Field(alias="ratingDistribution")  # {1: count, 2: count, ...}
    dimension_averages: dict = Field(alias="dimensionAverages")   # {seatComfort: avg, ...}
    recent_reviews: List[UserReviewResponse] = Field(default=[], alias="recentReviews")
    
    class Config:
        populate_by_name = True


class FlightWithScoreExtended(BaseModel):
    """Extended flight data including user review placeholders"""
    flight: Flight
    score: FlightScore
    facilities: FlightFacilities
    
    # === PLACEHOLDERS FOR USER DATA ===
    # TODO: Connect to SQL database for user reviews
    user_reviews_placeholder: str = Field(
        default="Connect to SQL database for user reviews",
        alias="userReviewsPlaceholder"
    )
    user_rating_placeholder: Optional[float] = Field(
        default=None,
        alias="userRatingPlaceholder",
        description="Average user rating (null until connected to database)"
    )
    user_experience: Optional[UserExperienceRating] = Field(
        default=None,
        alias="userExperience"
    )
    
    class Config:
        populate_by_name = True


# ============================================================
# Feedback & Error Report Models (反馈与纠错管理)
# ============================================================

class ReportCreate(BaseModel):
    """创建反馈报告请求"""
    user_email: str = Field(alias="userEmail")
    category: ReportCategory
    content: str = Field(min_length=10, max_length=2000)
    flight_id: Optional[str] = Field(default=None, alias="flightId")
    flight_info: Optional[dict] = Field(default=None, alias="flightInfo")  # Airline, route, etc.
    
    class Config:
        populate_by_name = True


class ReportResponse(BaseModel):
    """反馈报告响应"""
    id: int
    user_id: Optional[str] = Field(default=None, alias="userId")
    user_email: str = Field(alias="userEmail")
    category: str
    category_label: str = Field(alias="categoryLabel")  # Chinese label
    content: str
    flight_id: Optional[str] = Field(default=None, alias="flightId")
    flight_info: Optional[dict] = Field(default=None, alias="flightInfo")
    status: str
    status_label: str = Field(alias="statusLabel")  # Chinese label
    admin_notes: Optional[str] = Field(default=None, alias="adminNotes")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    
    class Config:
        populate_by_name = True


class ReportCategoryInfo(BaseModel):
    """反馈类别信息"""
    value: str
    label: str
    label_en: str = Field(alias="labelEn")
    description: Optional[str] = None
    
    class Config:
        populate_by_name = True
