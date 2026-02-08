"""
AirEase Backend - Authentication Routes
User registration, login, and profile endpoints
"""

from fastapi import APIRouter, HTTPException, Depends, status, Header
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db, UserDB
from app.models import (
    UserCreate, UserLogin, UserUpdate, Token, UserResponse,
    VerificationRequest, ResendVerificationRequest, VerificationResponse,
    ForgotPasswordRequest, ResetPasswordRequest, ChangePasswordRequest
)
from app.services.auth_service import auth_service
from app.services.verification_service import verification_service

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
    response_model=VerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate registration with email verification",
    description="Start registration process by sending verification code to email"
)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    Initiate user registration with email verification.

    Step 1 of 2-step registration:
    - **email**: Valid email address (must be unique)
    - **username**: Display name (3-50 characters)
    - **password**: Password (minimum 6 characters)

    Sends a 6-digit verification code to the provided email.
    User must call /verify-email with the code to complete registration.
    """
    # Check if email already exists
    existing_user = db.query(UserDB).filter(UserDB.user_email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Generate verification code
    code = verification_service.generate_code()
    
    # Store pending registration
    user_dict = {
        "email": user_data.email,
        "username": user_data.username,
        "password": user_data.password,
        "label": user_data.label.value
    }
    verification_service.store_pending_registration(
        email=user_data.email,
        code=code,
        user_data=user_dict
    )
    
    # Send verification email
    email_sent = await verification_service.send_verification_email(
        email=user_data.email,
        code=code,
        username=user_data.username
    )
    
    if not email_sent and verification_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email. Please try again."
        )
    
    return VerificationResponse(
        message="Verification code sent to your email",
        email=user_data.email,
        expires_in_minutes=verification_service.CODE_EXPIRY_MINUTES
    )


@router.post(
    "/verify-email",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Complete registration with verification code",
    description="Verify email and complete user registration"
)
async def verify_email(
    verification: VerificationRequest,
    db: Session = Depends(get_db)
):
    """
    Complete registration with email verification code.

    Step 2 of 2-step registration:
    - **email**: Email address used in registration
    - **code**: 6-digit verification code from email

    Returns JWT token on successful verification.
    """
    # Verify the code and get user data
    user_data = verification_service.verify_code(
        email=verification.email,
        submitted_code=verification.code
    )
    
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code"
        )
    
    # Double-check email doesn't exist (race condition protection)
    existing_user = db.query(UserDB).filter(UserDB.user_email == verification.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user account
    hashed_password = auth_service.hash_password(user_data["password"])
    db_user = UserDB(
        user_email=user_data["email"],
        user_name=user_data["username"],
        user_password=hashed_password,
        user_label=user_data["label"],
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
    "/resend-verification",
    response_model=VerificationResponse,
    summary="Resend verification code",
    description="Resend verification code to email for pending registration"
)
async def resend_verification(
    request: ResendVerificationRequest,
    db: Session = Depends(get_db)
):
    """
    Resend verification code for pending registration.

    - **email**: Email address with pending verification

    Generates a new code and sends it to the email.
    """
    # Check if there's a pending registration
    pending = verification_service.get_pending_registration(request.email)
    
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending registration for this email. Please register first."
        )
    
    _, user_data = pending
    
    # Generate new code
    new_code = verification_service.generate_code()
    
    # Update pending registration with new code
    verification_service.store_pending_registration(
        email=request.email,
        code=new_code,
        user_data=user_data
    )
    
    # Send new verification email
    email_sent = await verification_service.send_verification_email(
        email=request.email,
        code=new_code,
        username=user_data.get("username", "User")
    )
    
    if not email_sent and verification_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email. Please try again."
        )
    
    return VerificationResponse(
        message="New verification code sent to your email",
        email=request.email,
        expires_in_minutes=verification_service.CODE_EXPIRY_MINUTES
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


@router.post(
    "/forgot-password",
    response_model=VerificationResponse,
    summary="Forgot password",
    description="Send a password reset verification code to email"
)
async def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Initiate password reset.

    - **email**: Registered email address

    Sends a 6-digit verification code to the email if the account exists.
    Always returns success to prevent email enumeration attacks.
    """
    user = db.query(UserDB).filter(UserDB.user_email == request.email).first()
    
    if user:
        # Generate verification code
        code = verification_service.generate_code()
        
        # Store as pending "password reset" — reuse the pending registration store
        # with a special marker
        verification_service.store_pending_registration(
            email=request.email,
            code=code,
            user_data={"action": "password_reset", "user_id": user.user_id}
        )
        
        # Send reset email
        await verification_service.send_verification_email(
            email=request.email,
            code=code,
            username=user.user_name,
            subject="AirEase - Password Reset Code"
        )
    
    # Always return success to prevent email enumeration
    return VerificationResponse(
        message="If this email is registered, a password reset code has been sent",
        email=request.email,
        expires_in_minutes=verification_service.CODE_EXPIRY_MINUTES
    )


@router.post(
    "/reset-password",
    summary="Reset password with verification code",
    description="Reset password using the code received via email"
)
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """
    Reset password with verification code.

    - **email**: Email address
    - **code**: 6-digit verification code from email
    - **new_password**: New password (minimum 6 characters)
    """
    # Verify the code
    pending_data = verification_service.verify_code(
        email=request.email,
        submitted_code=request.code
    )
    
    if not pending_data or pending_data.get("action") != "password_reset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code"
        )
    
    # Find user
    user = db.query(UserDB).filter(UserDB.user_email == request.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update password
    user.user_password = auth_service.hash_password(request.new_password)
    db.commit()
    
    return {"message": "Password has been reset successfully. Please log in with your new password."}


@router.post(
    "/change-password",
    summary="Change password",
    description="Change password while logged in (requires current password)"
)
async def change_password(
    request: ChangePasswordRequest,
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Change password for the currently logged-in user.

    - **current_password**: Current account password
    - **new_password**: New password (minimum 6 characters)
    """
    # Verify current password
    if not auth_service.verify_password(request.current_password, current_user.user_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect"
        )
    
    # Update password
    current_user.user_password = auth_service.hash_password(request.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}


@router.delete(
    "/me",
    summary="Delete account",
    description="Permanently delete the current user's account"
)
async def delete_account(
    current_user: UserDB = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    Permanently delete the current user's account and all associated data.

    Requires valid JWT token in Authorization header.
    This action cannot be undone.
    """
    try:
        # Delete the user (cascading should handle related records)
        db.delete(current_user)
        db.commit()
        return {"message": "Account deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete account: {str(e)}"
        )
