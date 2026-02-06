"""
AirEase Backend - Database Configuration
SQLAlchemy + PostgreSQL setup
"""

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey, Enum as SQLEnum, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import enum
import os
import uuid

from app.config import settings

# Database URL - PostgreSQL
DATABASE_URL = settings.database_url

# Create engine with PostgreSQL settings
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


# ============================================================
# Enums
# ============================================================

class UserLabel(str, enum.Enum):
    """User persona labels"""
    BUSINESS = "business"
    FAMILY = "family"
    STUDENT = "student"


# ============================================================
# Database Models (SQLAlchemy ORM)
# ============================================================

class UserDB(Base):
    """User database model - matches PostgreSQL users table"""
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    user_name = Column(String(50), unique=True, nullable=False)
    user_email = Column(String(255), unique=True, index=True, nullable=False)
    user_password = Column(String(255), nullable=False)
    user_label = Column(String(20), default="business")  # business, family, student
    family_id = Column(String(36), unique=True, nullable=False)  # UUID for family grouping
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Sort preference counters for AI recommendations
    sort_by_overall_count = Column(Integer, default=0)
    sort_by_price_count = Column(Integer, default=0)
    sort_by_comfort_count = Column(Integer, default=0)
    sort_by_duration_count = Column(Integer, default=0)
    sort_by_departure_count = Column(Integer, default=0)
    sort_by_arrival_count = Column(Integer, default=0)
    
    # Relationships
    favorites = relationship("FavoriteDB", back_populates="user", cascade="all, delete-orphan")
    traveler_infos = relationship("TravelerInfoDB", back_populates="user", cascade="all, delete-orphan")
    search_history = relationship("SearchHistoryDB", back_populates="user", cascade="all, delete-orphan")
    flight_selections = relationship("FlightSelectionDB", back_populates="user", cascade="all, delete-orphan")
    
    # Aliases for compatibility
    @property
    def id(self):
        return self.user_id
    
    @property
    def email(self):
        return self.user_email
    
    @property
    def username(self):
        return self.user_name
    
    @property
    def hashed_password(self):
        return self.user_password
    
    @property
    def label(self):
        return self.user_label
    
    @staticmethod
    def generate_family_id():
        """Generate a unique family ID"""
        return str(uuid.uuid4())


class FavoriteDB(Base):
    """User favorites database model"""
    __tablename__ = "favorites"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    flight_id = Column(String(100), nullable=False)
    flight_number = Column(String(20), nullable=False)
    airline = Column(String(100), nullable=False)
    departure_city = Column(String(10), nullable=False)
    arrival_city = Column(String(10), nullable=False)
    departure_time = Column(DateTime, nullable=False)
    price = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    user = relationship("UserDB", back_populates="favorites")


class TravelerInfoDB(Base):
    """
    Traveler information database model.
    Contains personal info for travelers under a family account.
    All travelers created by a user share the same family_id.
    """
    __tablename__ = "traveller_info"
    
    id = Column(Integer, primary_key=True, index=True)
    family_id = Column(String(36), ForeignKey("users.family_id", ondelete="CASCADE"), nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    middle_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=False)
    passport_number = Column(String(100), nullable=True)
    dob = Column(Date, nullable=True)
    nationality = Column(String(50), nullable=True)
    gender = Column(String(10), nullable=True)
    is_primary = Column(Boolean, default=False)  # True if this is the account owner
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship via family_id to user
    user = relationship("UserDB", back_populates="traveler_infos", foreign_keys=[family_id], primaryjoin="TravelerInfoDB.family_id == UserDB.family_id")


class SearchHistoryDB(Base):
    """
    Search history database model.
    Stores user's flight search queries for quick re-search.
    """
    __tablename__ = "search_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    departure_city = Column(String(10), nullable=False)
    arrival_city = Column(String(10), nullable=False)
    departure_date = Column(Date, nullable=False)
    return_date = Column(Date, nullable=True)
    passengers = Column(Integer, nullable=False, default=1)
    cabin_class = Column(String(20), nullable=False, default="economy")
    departure_time_range = Column(String(10), nullable=True)  # "0-4", "4-8", "8-12", etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    user = relationship("UserDB", back_populates="search_history")


class FlightSelectionDB(Base):
    """
    Flight selection tracking model.
    Records when users click to view flight details - used for AI recommendations.
    """
    __tablename__ = "flight_selections"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    flight_id = Column(String(100), nullable=False)
    departure_city = Column(String(10), nullable=False)
    arrival_city = Column(String(10), nullable=False)
    departure_time = Column(DateTime, nullable=False)
    airline = Column(String(100), nullable=False)
    price = Column(Integer, nullable=False)
    overall_score = Column(Integer, nullable=False)
    cabin_class = Column(String(20), nullable=False, default="economy")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    user = relationship("UserDB", back_populates="flight_selections")


class ReportDB(Base):
    """
    Reports and User Reflections - 反馈与纠错管理
    Stores user feedback and error reports with email notification support
    """
    __tablename__ = "reports_and_user_reflections"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=True, index=True)  # Optional: for logged-in users
    user_email = Column(String(255), nullable=False)          # Required: for notification response
    category = Column(String(50), nullable=False, index=True) # Report category
    content = Column(Text, nullable=False)                    # Detailed description
    flight_id = Column(String(100), nullable=True)            # Optional: related flight ID
    flight_info = Column(Text, nullable=True)                 # Optional: flight details JSON
    status = Column(String(20), default="pending", index=True) # pending, reviewed, resolved, dismissed
    admin_notes = Column(Text, nullable=True)                 # Admin response/notes
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserSortActionDB(Base):
    """
    Tracks user sort actions for preference learning.
    Each time a user clicks a sort option, we record it.
    """
    __tablename__ = "user_sort_actions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    sort_dimension = Column(String(50), nullable=False)  # price, duration, score, departure, arrival
    created_at = Column(DateTime, default=datetime.utcnow)


class UserTimeFilterActionDB(Base):
    """
    Tracks user time filter actions for preference learning.
    Records when users filter by departure time range.
    """
    __tablename__ = "user_time_filter_actions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    time_range = Column(String(20), nullable=False)  # "0-6", "6-12", "12-18", "18-24"
    created_at = Column(DateTime, default=datetime.utcnow)


class UserPreferencesCacheDB(Base):
    """
    Cached/aggregated user preferences for fast recommendation lookups.
    Updated periodically from tracking tables using Pandas aggregation.
    """
    __tablename__ = "user_preferences_cache"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    
    # Aggregated preference data (computed from tracking tables)
    time_range_preferences = Column(Text, nullable=True)  # JSONB: {"6-12": 15, "12-18": 8, ...}
    preferred_sort_dimension = Column(String(50), nullable=True)  # Most frequent sort
    preferred_airlines = Column(Text, nullable=True)  # JSONB: ["CX", "HX", "UO"]
    price_sensitivity = Column(String(20), nullable=True)  # "high", "medium", "low"
    
    # Detailed counts for analysis
    sort_counts = Column(Text, nullable=True)  # JSONB: {"price": 25, "duration": 10, ...}
    time_range_counts = Column(Text, nullable=True)  # JSONB: {"6-12": 15, ...}
    airline_counts = Column(Text, nullable=True)  # JSONB: {"CX": 10, "HX": 5, ...}
    total_sort_actions = Column(Integer, default=0)
    total_selections = Column(Integer, default=0)
    
    # Legacy field (to be removed)
    top_routes = Column(Text, nullable=True)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================
# Database Utilities
# ============================================================

def init_db():
    """Initialize database - create all tables"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """
    Dependency to get database session.
    Yields a session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
