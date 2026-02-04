"""
AirEase Backend - Authentication Routes
User registration, login, and profile endpoints
"""

from fastapi import APIRouter, HTTPException, Depends, status, Header
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db, UserDB
from app.models import UserCreate, UserLogin, UserUpdate, Token, UserResponse
from app.services.auth_service import auth_service

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])


# ============================================================
# Helper Functions
# ============================================================

def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> Optional[UserDB]:
    """
    Dependency to get current user from Authorization header.
    Returns None if not authenticated (for optional auth).
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.split(" ")[1]
    payload = auth_service.decode_token(token)

    if not payload:
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None

    user = db.query(UserDB).filter(UserDB.user_id == user_id).first()
    return user


def require_auth(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> UserDB:
    """
    Dependency that requires authentication.
    Raises 401 if not authenticated.
    """
    user = get_current_user(authorization, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    return user


# ============================================================
# Authentication Endpoints
# ============================================================

@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account and return JWT token"
)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user.

    - **email**: Valid email address (must be unique)
    - **username**: Display name (3-50 characters)
    - **password**: Password (minimum 6 characters)

    Returns JWT token on successful registration.
    """
    # Check if email already exists
    existing_user = db.query(UserDB).filter(UserDB.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create new user with generated family_id
    hashed_password = auth_service.hash_password(user_data.password)
    db_user = UserDB(
        user_email=user_data.email,
        user_name=user_data.username,
        user_password=hashed_password,
        user_label=user_data.label.value,
        family_id=UserDB.generate_family_id()
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Generate token
    access_token, expires_in = auth_service.create_access_token(
        user_id=db_user.user_id,
        email=db_user.user_email
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user=UserResponse(
            id=db_user.user_id,
            email=db_user.user_email,
            username=db_user.user_name,
            created_at=db_user.created_at,
            is_active=db_user.is_active,
            label=db_user.user_label,
            family_id=db_user.family_id
        )
    )


@router.post(
    "/login",
    response_model=Token,
    summary="Login",
    description="Authenticate user and return JWT token"
)
async def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """
    Login with email and password.

    - **email**: Registered email address
    - **password**: Account password

    Returns JWT token on successful authentication.
    """
    # Find user by email
    user = db.query(UserDB).filter(UserDB.user_email == credentials.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Verify password
    if not auth_service.verify_password(credentials.password, user.user_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    # Generate token
    access_token, expires_in = auth_service.create_access_token(
        user_id=user.user_id,
        email=user.user_email
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user=UserResponse(
            id=user.user_id,
            email=user.user_email,
            username=user.user_name,
            created_at=user.created_at,
            is_active=user.is_active,
            label=user.user_label,
            family_id=user.family_id
        )
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Get the currently authenticated user's profile"
)
async def get_me(current_user: UserDB = Depends(require_auth)):
    """
    Get current user profile.

    Requires valid JWT token in Authorization header.
    """
    return UserResponse(
        id=current_user.user_id,
        email=current_user.user_email,
        username=current_user.user_name,
        created_at=current_user.created_at,
        is_active=current_user.is_active,
        label=current_user.user_label,
        family_id=current_user.family_id
    )


@router.put(
    "/me",
    response_model=UserResponse,
    summary="Update current user",
    description="Update the currently authenticated user's profile"
)
async def update_me(
    update_data: UserUpdate,
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Update current user profile.

    Requires valid JWT token in Authorization header.
    """
    if update_data.username is not None:
        current_user.user_name = update_data.username
    if update_data.label is not None:
        current_user.user_label = update_data.label.value
    
    db.commit()
    db.refresh(current_user)
    
    return UserResponse(
        id=current_user.user_id,
        email=current_user.user_email,
        username=current_user.user_name,
        created_at=current_user.created_at,
        is_active=current_user.is_active,
        label=current_user.user_label,
        family_id=current_user.family_id
    )


@router.post(
    "/logout",
    summary="Logout",
    description="Logout current user (client-side token invalidation)"
)
async def logout():
    """
    Logout endpoint.

    Note: JWT tokens are stateless, so this endpoint just returns success.
    The client should remove the token from local storage.
    """
    return {"message": "Logged out successfully"}
