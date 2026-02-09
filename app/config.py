"""
AirEase Backend Configuration
环境变量和应用配置
"""

from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True
    
    # API Keys
    gemini_api_key: str = ""
    
    # SerpAPI Key (Google Flights API)
    serpapi_key: str = ""
    
    # Amadeus Flight API
    amadeus_api_key: str = ""
    amadeus_api_secret: str = ""
    amadeus_base_url: str = "https://test.api.amadeus.com"
    
    # Google Places API
    google_places_api_key: str = ""
    
    # PostgreSQL Database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_db: str = "airease"
    
    @property
    def database_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    # Cache
    redis_url: Optional[str] = None
    cache_ttl: int = 300  # 5 minutes
    
    # CORS
    cors_origins: str = "*"

    # JWT Authentication
    jwt_secret: str = "airease-super-secret-key-change-in-production-2024"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 days
    
    # Email Notification Settings (for feedback reports and verification)
    # =================================================================
    # To enable email functionality, you need to configure SMTP settings.
    # 
    # FOR GMAIL:
    # 1. Enable 2-Factor Authentication in your Google Account
    # 2. Go to: https://myaccount.google.com/apppasswords
    # 3. Generate an "App Password" for "Mail"
    # 4. Use that 16-character password as smtp_password (not your Google password!)
    #
    # Example .env configuration for Gmail:
    #   SMTP_HOST=smtp.gmail.com
    #   SMTP_PORT=587
    #   SMTP_USER=your-email@gmail.com
    #   SMTP_PASSWORD=xxxx xxxx xxxx xxxx  (App Password from step 3)
    #   ADMIN_EMAIL=stevenyi0526@gmail.com
    #   FROM_EMAIL=your-email@gmail.com
    #
    # FOR OTHER PROVIDERS:
    # - Outlook: smtp.office365.com, port 587
    # - Yahoo: smtp.mail.yahoo.com, port 587
    # - Custom: Use your email provider's SMTP settings
    # =================================================================
    smtp_host: str = ""           # e.g., "smtp.gmail.com"
    smtp_port: int = 587          # TLS port (use 465 for SSL)
    smtp_user: str = ""           # Your email address
    smtp_password: str = ""       # App password (NOT your regular password!)
    admin_email: str = "steven.yi@airease.ai"  # Email to receive feedback notifications
    from_email: Optional[str] = None  # Sender email (defaults to smtp_user)
    
    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
