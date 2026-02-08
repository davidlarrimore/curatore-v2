# backend/app/api/v1/routers/auth.py
"""
Authentication endpoints for Curatore v2 API (v1).

Provides user registration, login, token refresh, and user profile endpoints.
Supports both JWT token-based authentication (for frontend) and API keys (for backend/headless).

Endpoints:
    POST /auth/register - Register new user
    POST /auth/login - Login and receive tokens
    POST /auth/refresh - Refresh access token
    POST /auth/extend-session - Extend session (new tokens)
    POST /auth/logout - Logout (client-side token discard)
    GET /auth/me - Get current user profile

Security:
    - Passwords are hashed with bcrypt before storage
    - JWT tokens have configurable expiration
    - Refresh tokens allow obtaining new access tokens
    - All tokens are signed with JWT_SECRET_KEY
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.config import settings
from app.core.database.models import Organization, User
from app.dependencies import get_current_user
from app.core.auth.auth_service import auth_service
from app.core.shared.database_service import database_service
from app.core.auth.verification_service import verification_service
from app.core.auth.password_reset_service import password_reset_service

# Initialize router
router = APIRouter(prefix="/auth", tags=["Authentication"])

# Initialize logger
logger = logging.getLogger("curatore.api.auth")


# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================


class UserRegisterRequest(BaseModel):
    """User registration request."""

    email: EmailStr = Field(..., description="User's email address")
    username: str = Field(..., min_length=3, max_length=100, description="Username (3-100 chars)")
    password: str = Field(..., min_length=8, max_length=100, description="Password (min 8 chars)")
    full_name: Optional[str] = Field(None, max_length=255, description="User's full name")
    organization_id: Optional[str] = Field(
        None,
        description="Organization ID (optional, uses default if not provided)",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "username": "johndoe",
                "password": "SecurePass123!",
                "full_name": "John Doe",
            }
        }


class UserLoginRequest(BaseModel):
    """User login request."""

    email_or_username: str = Field(..., description="Email address or username")
    password: str = Field(..., description="Password")

    class Config:
        json_schema_extra = {
            "example": {
                "email_or_username": "user@example.com",
                "password": "SecurePass123!",
            }
        }


class TokenRefreshRequest(BaseModel):
    """Token refresh request."""

    refresh_token: str = Field(..., description="Refresh token from login response")

    class Config:
        json_schema_extra = {
            "example": {
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
            }
        }


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str = Field(..., description="JWT access token (60 min expiration)")
    refresh_token: str = Field(..., description="JWT refresh token (30 day expiration)")
    token_type: str = Field(default="bearer", description="Token type (always 'bearer')")
    expires_in: int = Field(..., description="Access token expiration in seconds")

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 3600,
            }
        }


class UserProfileResponse(BaseModel):
    """User profile response."""

    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="User's email address")
    username: str = Field(..., description="Username")
    full_name: Optional[str] = Field(None, description="User's full name")
    role: str = Field(..., description="User role (org_admin, member, viewer)")
    is_active: bool = Field(..., description="Whether user account is active")
    is_verified: bool = Field(..., description="Whether email is verified")
    organization_id: str = Field(..., description="Organization UUID")
    created_at: datetime = Field(..., description="Account creation timestamp")
    last_login_at: Optional[datetime] = Field(None, description="Last login timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "email": "user@example.com",
                "username": "johndoe",
                "full_name": "John Doe",
                "role": "member",
                "is_active": True,
                "is_verified": True,
                "organization_id": "987fcdeb-51a2-43f7-8b6a-123456789abc",
                "created_at": "2024-01-01T00:00:00",
                "last_login_at": "2024-01-12T15:30:00",
            }
        }


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str = Field(..., description="Response message")


class VerifyEmailRequest(BaseModel):
    """Email verification request."""

    token: str = Field(..., description="Email verification token from email link")

    class Config:
        json_schema_extra = {
            "example": {
                "token": "a1b2c3d4e5f6g7h8i9j0..."
            }
        }


class ResendVerificationRequest(BaseModel):
    """Resend verification email request."""

    email: EmailStr = Field(..., description="User's email address")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com"
            }
        }


class ForgotPasswordRequest(BaseModel):
    """Forgot password request."""

    email: EmailStr = Field(..., description="User's email address")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com"
            }
        }


class ResetPasswordRequest(BaseModel):
    """Reset password request."""

    token: str = Field(..., description="Password reset token from email link")
    new_password: str = Field(..., min_length=8, max_length=100, description="New password (min 8 chars)")

    class Config:
        json_schema_extra = {
            "example": {
                "token": "a1b2c3d4e5f6g7h8i9j0...",
                "new_password": "NewSecurePass123!"
            }
        }


class ValidateResetTokenResponse(BaseModel):
    """Validate reset token response."""

    valid: bool = Field(..., description="Whether token is valid")
    email: Optional[str] = Field(None, description="User email if token is valid")

    class Config:
        json_schema_extra = {
            "example": {
                "valid": True,
                "email": "user@example.com"
            }
        }


# =========================================================================
# ENDPOINTS
# =========================================================================


@router.post(
    "/register",
    response_model=UserProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Register a new user account. Requires organization_id or uses default organization.",
)
async def register(request: UserRegisterRequest) -> UserProfileResponse:
    """
    Register a new user account.

    Creates a new user with hashed password. User is added to the specified
    organization or the default organization if none is provided.

    Args:
        request: User registration details

    Returns:
        UserProfileResponse: Created user profile

    Raises:
        HTTPException: 400 if email/username already exists
        HTTPException: 404 if organization not found
        HTTPException: 500 if user creation fails
    """
    logger.info(f"User registration attempt: {request.email}")

    async with database_service.get_session() as session:
        # Check if email already exists
        result = await session.execute(select(User).where(User.email == request.email))
        if result.scalar_one_or_none():
            logger.warning(f"Registration failed: email {request.email} already exists")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Check if username already exists
        result = await session.execute(select(User).where(User.username == request.username))
        if result.scalar_one_or_none():
            logger.warning(f"Registration failed: username {request.username} already exists")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )

        # Determine organization
        if request.organization_id:
            org_id = UUID(request.organization_id)
            # Verify organization exists
            result = await session.execute(
                select(Organization).where(Organization.id == org_id)
            )
            org = result.scalar_one_or_none()
            if not org:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization not found",
                )
        else:
            # Use default organization (get first active org)
            result = await session.execute(
                select(Organization).where(Organization.is_active == True).limit(1)
            )
            org = result.scalar_one_or_none()
            if not org:
                logger.error("No active organization found for registration")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No active organization available. Please contact administrator.",
                )
            org_id = org.id

        # Hash password
        password_hash = await auth_service.hash_password(request.password)

        # Create user
        new_user = User(
            email=request.email,
            username=request.username,
            password_hash=password_hash,
            full_name=request.full_name,
            organization_id=org_id,
            role="member",  # Default role
            is_active=True,
            is_verified=False,  # Email verification required
        )

        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

        logger.info(f"User registered successfully: {new_user.email} (id: {new_user.id})")

        # Generate verification token and send email
        try:
            token = await verification_service.generate_verification_token(session, new_user.id)
            from app.core.tasks import send_verification_email_task
            send_verification_email_task.delay(
                user_email=new_user.email,
                user_name=new_user.full_name or new_user.username,
                verification_token=token,
            )
            logger.info(f"Verification email queued for {new_user.email}")
        except Exception as e:
            logger.error(f"Failed to send verification email: {e}")
            # Don't fail registration if email fails

        return UserProfileResponse(
            id=str(new_user.id),
            email=new_user.email,
            username=new_user.username,
            full_name=new_user.full_name,
            role=new_user.role,
            is_active=new_user.is_active,
            is_verified=new_user.is_verified,
            organization_id=str(new_user.organization_id),
            created_at=new_user.created_at,
            last_login_at=new_user.last_login_at,
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login user",
    description="Authenticate user and receive JWT access and refresh tokens.",
)
async def login(request: UserLoginRequest) -> TokenResponse:
    """
    Authenticate user and issue JWT tokens.

    Validates credentials and returns access token (60 min) and refresh token (30 days).

    Args:
        request: Login credentials (email/username and password)

    Returns:
        TokenResponse: JWT tokens

    Raises:
        HTTPException: 401 if credentials are invalid or user is inactive
    """
    logger.info(f"Login attempt: {request.email_or_username}")

    async with database_service.get_session() as session:
        # Find user by email or username
        result = await session.execute(
            select(User).where(
                (User.email == request.email_or_username)
                | (User.username == request.email_or_username)
            )
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.warning(f"Login failed: user not found ({request.email_or_username})")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email/username or password",
            )

        # Verify password
        is_valid = await auth_service.verify_password(request.password, user.password_hash)
        if not is_valid:
            logger.warning(f"Login failed: invalid password for user {user.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email/username or password",
            )

        # Check if user is active
        if not user.is_active:
            logger.warning(f"Login failed: user {user.email} is inactive")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive",
            )

        # Update last login timestamp
        user.last_login_at = datetime.utcnow()
        await session.commit()

        # Generate tokens
        access_token = auth_service.create_access_token(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
            role=user.role,
        )

        refresh_token = auth_service.create_refresh_token(
            user_id=str(user.id),
            organization_id=str(user.organization_id),
        )

        logger.info(f"Login successful: {user.email}")

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,  # Convert to seconds
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Use refresh token to obtain a new access token without re-authenticating.",
)
async def refresh_token(request: TokenRefreshRequest) -> TokenResponse:
    """
    Refresh access token using refresh token.

    Validates refresh token and issues new access token and refresh token.

    Args:
        request: Refresh token

    Returns:
        TokenResponse: New JWT tokens

    Raises:
        HTTPException: 401 if refresh token is invalid or expired
    """
    logger.debug("Token refresh attempt")

    try:
        # Decode and validate refresh token
        payload = auth_service.decode_token(request.refresh_token)

        # Verify token type is "refresh"
        if not auth_service.verify_token_type(payload, "refresh"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Expected refresh token.",
            )

        # Extract user_id and org_id
        user_id = payload.get("sub")
        org_id = payload.get("org_id")

        if not user_id or not org_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        # Fetch user to verify still active
        async with database_service.get_session() as session:
            result = await session.execute(select(User).where(User.id == UUID(user_id)))
            user = result.scalar_one_or_none()

            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or inactive",
                )

            # Generate new tokens
            access_token = auth_service.create_access_token(
                user_id=str(user.id),
                organization_id=str(user.organization_id),
                role=user.role,
            )

            refresh_token = auth_service.create_refresh_token(
                user_id=str(user.id),
                organization_id=str(user.organization_id),
            )

            logger.info(f"Token refreshed for user: {user.email}")

            return TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                expires_in=settings.jwt_access_token_expire_minutes * 60,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )


@router.post(
    "/extend-session",
    response_model=TokenResponse,
    summary="Extend session",
    description="Issue new tokens for an authenticated user to extend session timeout.",
)
async def extend_session(user: User = Depends(get_current_user)) -> TokenResponse:
    """
    Extend session by issuing new access and refresh tokens.

    Args:
        user: Current authenticated user

    Returns:
        TokenResponse: New JWT tokens
    """
    access_token = auth_service.create_access_token(
        user_id=str(user.id),
        organization_id=str(user.organization_id),
        role=user.role,
    )

    refresh_token = auth_service.create_refresh_token(
        user_id=str(user.id),
        organization_id=str(user.organization_id),
    )

    logger.info(f"Session extended for user: {user.email}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout user",
    description="Logout user (client should discard tokens). Server-side token invalidation not implemented.",
)
async def logout(user: User = Depends(get_current_user)) -> MessageResponse:
    """
    Logout user.

    Since JWT tokens are stateless, logout is primarily client-side (discard tokens).
    This endpoint is provided for consistency and future token blacklisting implementation.

    Args:
        user: Current authenticated user

    Returns:
        MessageResponse: Logout confirmation message

    Note:
        Client must discard both access_token and refresh_token after logout.
        Future: Implement token blacklist/revocation for enhanced security.
    """
    logger.info(f"User logout: {user.email}")

    return MessageResponse(
        message="Logout successful. Please discard your tokens."
    )


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get current user profile",
    description="Get profile information for the currently authenticated user.",
)
async def get_current_user_profile(user: User = Depends(get_current_user)) -> UserProfileResponse:
    """
    Get current user profile.

    Returns profile information for the authenticated user making the request.

    Args:
        user: Current authenticated user (from JWT or API key)

    Returns:
        UserProfileResponse: User profile information

    Example:
        GET /api/v1/auth/me
        Authorization: Bearer <access_token>

        Response:
        {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "email": "user@example.com",
            "username": "johndoe",
            "role": "member",
            ...
        }
    """
    logger.debug(f"Profile requested for user: {user.email}")

    return UserProfileResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        is_verified=user.is_verified,
        organization_id=str(user.organization_id),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


# =========================================================================
# EMAIL VERIFICATION ENDPOINTS
# =========================================================================


@router.post(
    "/verify-email",
    response_model=UserProfileResponse,
    summary="Verify email address",
    description="Verify user's email address using token from verification email.",
)
async def verify_email(request: VerifyEmailRequest) -> UserProfileResponse:
    """
    Verify email address with token.

    Validates the verification token and marks the user's email as verified.

    Args:
        request: Verification token from email

    Returns:
        UserProfileResponse: Verified user profile

    Raises:
        HTTPException: 400 if token is invalid, expired, or already used
    """
    logger.info("Email verification attempt")

    async with database_service.get_session() as session:
        user = await verification_service.verify_email_token(session, request.token)

        if not user:
            logger.warning("Email verification failed: invalid or expired token")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification token",
            )

        logger.info(f"Email verified successfully for user {user.email}")

        # Optionally send welcome email
        try:
            from app.core.tasks import send_welcome_email_task
            send_welcome_email_task.delay(
                user_email=user.email,
                user_name=user.full_name or user.username,
            )
            logger.info(f"Welcome email queued for {user.email}")
        except Exception as e:
            logger.error(f"Failed to queue welcome email: {e}")

        return UserProfileResponse(
            id=str(user.id),
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            is_verified=user.is_verified,
            organization_id=str(user.organization_id),
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    summary="Resend verification email",
    description="Resend email verification link to user's email address.",
)
async def resend_verification(request: ResendVerificationRequest) -> MessageResponse:
    """
    Resend verification email.

    Generates a new verification token and sends it to the user's email.

    Args:
        request: User's email address

    Returns:
        MessageResponse: Confirmation message

    Note:
        Always returns success to prevent email enumeration attacks.
    """
    logger.info(f"Verification email resend requested for: {request.email}")

    async with database_service.get_session() as session:
        # Look up user by email
        result = await session.execute(select(User).where(User.email == request.email.lower()))
        user = result.scalar_one_or_none()

        if user and user.is_active and not user.is_verified:
            try:
                await verification_service.resend_verification_email(session, user.id)
                logger.info(f"Verification email resent to {request.email}")
            except Exception as e:
                logger.error(f"Failed to resend verification email: {e}")

    # Always return success to prevent email enumeration
    return MessageResponse(
        message="If that email address exists and is not yet verified, a verification link has been sent."
    )


# =========================================================================
# PASSWORD RESET ENDPOINTS
# =========================================================================


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
    description="Request password reset link via email.",
)
async def forgot_password(request: ForgotPasswordRequest) -> MessageResponse:
    """
    Request password reset.

    Generates a password reset token and sends it to the user's email.

    Args:
        request: User's email address

    Returns:
        MessageResponse: Confirmation message

    Note:
        Always returns success to prevent email enumeration attacks.
        Token expires in 1 hour for security.
    """
    logger.info(f"Password reset requested for: {request.email}")

    async with database_service.get_session() as session:
        await password_reset_service.request_password_reset(session, request.email)

    # Always return success to prevent email enumeration
    return MessageResponse(
        message="If that email address exists, a password reset link has been sent."
    )


@router.get(
    "/validate-reset-token/{token}",
    response_model=ValidateResetTokenResponse,
    summary="Validate password reset token",
    description="Check if password reset token is valid without using it.",
)
async def validate_reset_token(token: str) -> ValidateResetTokenResponse:
    """
    Validate password reset token.

    Checks if the token is valid, not expired, and not already used.

    Args:
        token: Password reset token

    Returns:
        ValidateResetTokenResponse: Token validity and user email

    Example:
        GET /api/v1/auth/validate-reset-token/abc123...

        Response:
        {
            "valid": true,
            "email": "user@example.com"
        }
    """
    logger.debug("Reset token validation attempt")

    async with database_service.get_session() as session:
        user = await password_reset_service.validate_reset_token(session, token)

        if user:
            return ValidateResetTokenResponse(
                valid=True,
                email=user.email,
            )
        else:
            return ValidateResetTokenResponse(
                valid=False,
                email=None,
            )


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password",
    description="Reset password using token from password reset email.",
)
async def reset_password(request: ResetPasswordRequest) -> MessageResponse:
    """
    Reset password with token.

    Validates the reset token and updates the user's password.

    Args:
        request: Reset token and new password

    Returns:
        MessageResponse: Success confirmation

    Raises:
        HTTPException: 400 if token is invalid, expired, or already used
    """
    logger.info("Password reset attempt")

    async with database_service.get_session() as session:
        success = await password_reset_service.reset_password(
            session,
            request.token,
            request.new_password,
        )

        if not success:
            logger.warning("Password reset failed: invalid or expired token")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token",
            )

        logger.info("Password reset successful")

        return MessageResponse(
            message="Password reset successfully. You can now login with your new password."
        )
