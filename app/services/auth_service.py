"""
AirEase Backend - Authentication Service
JWT token handling and password hashing
"""

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings


# Password hashing context using sha256_crypt (more compatible than bcrypt)
pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


class AuthService:
    """Service for authentication operations"""

    def __init__(self):
        self.secret_key = settings.jwt_secret
        self.algorithm = settings.jwt_algorithm
        self.access_token_expire_minutes = settings.jwt_expire_minutes

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return pwd_context.verify(plain_password, hashed_password)

    def hash_password(self, password: str) -> str:
        """Hash a password for storage"""
        return pwd_context.hash(password)

    def create_access_token(self, user_id: int, email: str) -> tuple[str, int]:
        """
        Create a JWT access token.
        Returns tuple of (token, expires_in_seconds)
        """
        expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)
        expires_in_seconds = self.access_token_expire_minutes * 60

        to_encode = {
            "user_id": user_id,
            "email": email,
            "exp": expire,
            "iat": datetime.utcnow()
        }

        token = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return token, expires_in_seconds

    def decode_token(self, token: str) -> Optional[dict]:
        """
        Decode and validate a JWT token.
        Returns the payload if valid, None otherwise.
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            return payload
        except JWTError:
            return None

    def get_user_id_from_token(self, token: str) -> Optional[int]:
        """Extract user_id from a valid token"""
        payload = self.decode_token(token)
        if payload:
            return payload.get("user_id")
        return None


# Singleton instance
auth_service = AuthService()
