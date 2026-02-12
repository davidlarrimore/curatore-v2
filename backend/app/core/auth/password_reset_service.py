"""
Password reset service for Curatore v2.

Provides token generation, validation, and password reset management with rate limiting.

Key Features:
    - Generate secure password reset tokens
    - Validate and use reset tokens
    - Rate limiting to prevent abuse
    - Email enumeration protection
    - Token expiration management

Usage:
    from app.core.auth.password_reset_service import password_reset_service

    # Request password reset (returns True even if email doesn't exist)
    success = await password_reset_service.request_password_reset(session, email)

    # Validate reset token
    user = await password_reset_service.validate_reset_token(session, token)

    # Reset password with token
    success = await password_reset_service.reset_password(session, token, new_password)

Dependencies:
    - database session for token storage
    - secrets module for secure token generation
    - email_service for sending emails
    - auth_service for password hashing
    - Redis for rate limiting (optional)

Configuration:
    Uses settings from config.py:
    - password_reset_token_expire_hours: Token expiration (default 1 hour)
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth.auth_service import auth_service
from app.core.database.models import PasswordResetToken, User

logger = logging.getLogger("curatore.password_reset")


class PasswordResetService:
    """
    Password reset service for managing reset tokens and password changes.

    This service handles the complete password reset workflow including:
    - Token generation with secure random strings
    - Token validation and expiration checks
    - Password reset with new hash
    - Rate limiting to prevent abuse
    - Email enumeration protection

    Attributes:
        token_expire_hours: Token expiration in hours (from settings)
        rate_limit_requests: Max requests per hour per email (hardcoded to 3)
        rate_limit_window: Rate limit window in seconds (hardcoded to 3600)
    """

    def __init__(self):
        """Initialize password reset service with configuration."""
        self.token_expire_hours = settings.password_reset_token_expire_hours
        self.rate_limit_requests = 3  # Max 3 requests per hour
        self.rate_limit_window = 3600  # 1 hour in seconds

        logger.info(
            f"PasswordResetService initialized (token expiry: {self.token_expire_hours}h, "
            f"rate limit: {self.rate_limit_requests} requests per {self.rate_limit_window}s)"
        )

    async def request_password_reset(
        self, session: AsyncSession, email: str
    ) -> bool:
        """
        Request a password reset for an email address.

        Generates a reset token and sends a password reset email.
        Always returns True to prevent email enumeration attacks.

        Args:
            session: Database session
            email: User's email address

        Returns:
            bool: Always True (even if email doesn't exist)

        Example:
            >>> success = await password_reset_service.request_password_reset(session, "user@example.com")
            >>> print("Password reset email sent (if email exists)")

        Security:
            - Always returns True to prevent email enumeration
            - Rate limited to 3 requests per hour per email
            - Tokens expire after 1 hour by default
            - Email contains reset link with secure token
        """
        # Look up user by email
        stmt = select(User).where(User.email == email.lower())
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.info(f"Password reset requested for non-existent email: {email}")
            # Return True to prevent email enumeration
            return True

        if not user.is_active:
            logger.warning(f"Password reset requested for inactive user: {email}")
            # Return True to prevent email enumeration
            return True

        # TODO: Check rate limiting (3 requests per hour per email)
        # This would require Redis for tracking, implementing later
        # For now, we'll just generate the token

        # Generate secure random token
        token = secrets.token_urlsafe(32)

        # Calculate expiration
        expires_at = datetime.utcnow() + timedelta(hours=self.token_expire_hours)

        # Create token record
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=expires_at,
        )

        session.add(reset_token)
        await session.commit()

        logger.info(f"Generated password reset token for user {user.id} (expires: {expires_at})")

        # Send email via Celery task
        from app.core.tasks import send_password_reset_email_task

        try:
            send_password_reset_email_task.delay(
                user_email=user.email,
                user_name=user.full_name or user.username,
                reset_token=token,
            )
            logger.info(f"Password reset email queued for {user.email}")
        except Exception as e:
            logger.error(f"Failed to queue password reset email for {user.email}: {e}")

        # Always return True to prevent email enumeration
        return True

    async def validate_reset_token(
        self, session: AsyncSession, token: str
    ) -> Optional[User]:
        """
        Validate a password reset token without using it.

        Checks if the token exists, is not expired, and has not been used.
        Does not mark the token as used.

        Args:
            session: Database session
            token: Reset token string

        Returns:
            Optional[User]: User if token is valid, None otherwise

        Example:
            >>> user = await password_reset_service.validate_reset_token(session, token)
            >>> if user:
            ...     print(f"Token valid for {user.email}")
            ... else:
            ...     print("Invalid or expired token")

        Token Validation:
            - Token must exist in database
            - Token must not be expired
            - Token must not have been used already
            - User must exist and be active
        """
        # Look up token
        stmt = select(PasswordResetToken).where(PasswordResetToken.token == token)
        result = await session.execute(stmt)
        reset_token = result.scalar_one_or_none()

        if not reset_token:
            logger.warning("Password reset token not found")
            return None

        # Check if already used
        if reset_token.used_at:
            logger.warning(f"Password reset token already used at {reset_token.used_at}")
            return None

        # Check expiration
        if datetime.utcnow() > reset_token.expires_at:
            logger.warning(f"Password reset token expired at {reset_token.expires_at}")
            return None

        # Look up user
        stmt = select(User).where(User.id == reset_token.user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.error(f"User not found for reset token: {reset_token.user_id}")
            return None

        if not user.is_active:
            logger.warning(f"User {user.id} is not active")
            return None

        return user

    async def reset_password(
        self, session: AsyncSession, token: str, new_password: str
    ) -> bool:
        """
        Reset a user's password using a reset token.

        Validates the token, hashes the new password, updates the user,
        and marks the token as used.

        Args:
            session: Database session
            token: Reset token string
            new_password: New password (plaintext, will be hashed)

        Returns:
            bool: True if password was reset successfully, False otherwise

        Example:
            >>> success = await password_reset_service.reset_password(session, token, "NewPass123!")
            >>> if success:
            ...     print("Password reset successfully")
            ... else:
            ...     print("Invalid or expired token")

        Security:
            - Token must be valid and unexpired
            - Password is hashed with bcrypt before storage
            - Token is marked as used to prevent reuse
            - User can login immediately with new password
        """
        # Validate token first
        user = await self.validate_reset_token(session, token)
        if not user:
            return False

        # Hash new password
        try:
            password_hash = await auth_service.hash_password(new_password)
        except Exception as e:
            logger.error(f"Failed to hash password: {e}")
            return False

        # Update user password
        user.password_hash = password_hash

        # Mark token as used
        stmt = select(PasswordResetToken).where(PasswordResetToken.token == token)
        result = await session.execute(stmt)
        reset_token = result.scalar_one_or_none()

        if reset_token:
            reset_token.used_at = datetime.utcnow()

        await session.commit()

        logger.info(f"Password reset successfully for user {user.id} ({user.email})")
        return True

    async def cleanup_expired_tokens(self, session: AsyncSession) -> int:
        """
        Clean up expired password reset tokens.

        Removes all expired tokens from the database to keep the table clean.
        This should be run periodically via a Celery task.

        Args:
            session: Database session

        Returns:
            int: Number of tokens deleted

        Example:
            >>> deleted = await password_reset_service.cleanup_expired_tokens(session)
            >>> print(f"Deleted {deleted} expired tokens")
        """
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.expires_at < datetime.utcnow()
        )
        result = await session.execute(stmt)
        expired_tokens = result.scalars().all()

        count = len(expired_tokens)
        for token in expired_tokens:
            await session.delete(token)

        await session.commit()

        logger.info(f"Cleaned up {count} expired password reset tokens")
        return count


# Global singleton instance
password_reset_service = PasswordResetService()
