"""
AirEase Backend - Authentication Service
JWT token handling and password hashing
"""

import hashlib
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt

from app.config import settings


class AuthService:
    """Service for authentication operations"""

    def __init__(self):
        self.secret_key = settings.jwt_secret
        self.algorithm = settings.jwt_algorithm
        self.access_token_expire_minutes = settings.jwt_expire_minutes

    def verify_password(self, password_hash: str, stored_hash: str) -> bool:
        """Direct comparison — both sides are SHA-256 hex digests."""
        return password_hash == stored_hash

    def hash_password(self, password_hash: str) -> str:
        """Store the SHA-256 hex digest directly (hashing done by _decode_password)."""
        return password_hash

    @staticmethod
    def sha256(text: str) -> str:
        """Compute SHA-256 hex digest of plain text."""
        return hashlib.sha256(text.encode()).hexdigest()

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
