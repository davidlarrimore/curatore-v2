"""
Email verification service for Curatore v2.

Provides token generation, validation, and email verification management.

Key Features:
    - Generate secure verification tokens
    - Validate and use verification tokens
    - Resend verification emails
    - Token expiration management
    - Grace period for email verification enforcement

Usage:
    from app.services.verification_service import verification_service

    # Generate verification token
    token = await verification_service.generate_verification_token(user_id)

    # Verify email with token
    user = await verification_service.verify_email_token(token)

    # Resend verification email
    success = await verification_service.resend_verification_email(user_id)

Dependencies:
    - database session for token storage
    - secrets module for secure token generation
    - email_service for sending emails

Configuration:
    Uses settings from config.py:
    - email_verification_token_expire_hours: Token expiration (default 24 hours)
    - email_verification_grace_period_days: Grace period before enforcement (default 7 days)
"""

import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import EmailVerificationToken, User

logger = logging.getLogger("curatore.verification")


class VerificationService:
    """
    Email verification service for managing verification tokens and user verification.

    This service handles the complete email verification workflow including:
    - Token generation with secure random strings
    - Token validation and expiration checks
    - Marking users as verified
    - Resending verification emails
    - Grace period management

    Attributes:
        token_expire_hours: Token expiration in hours (from settings)
        grace_period_days: Grace period before enforcing verification (from settings)
    """

    def __init__(self):
        """Initialize verification service with configuration."""
        self.token_expire_hours = settings.email_verification_token_expire_hours
        self.grace_period_days = settings.email_verification_grace_period_days

        logger.info(
            f"VerificationService initialized (token expiry: {self.token_expire_hours}h, "
            f"grace period: {self.grace_period_days}d)"
        )

    async def generate_verification_token(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> str:
        """
        Generate a new verification token for a user.

        Creates a secure random token and stores it in the database with
        an expiration timestamp. If the user already has unused tokens,
        they remain valid until expiration.

        Args:
            session: Database session
            user_id: User's UUID

        Returns:
            str: Verification token (32 bytes hex, 64 characters)

        Example:
            >>> token = await verification_service.generate_verification_token(session, user.id)
            >>> print(f"Token: {token}")
            Token: a1b2c3d4e5f6...

        Security:
            - Uses secrets.token_urlsafe for cryptographically secure tokens
            - Tokens are unique and indexed for fast lookup
            - Expiration enforced at validation time
        """
        # Generate secure random token (32 bytes = 64 hex characters)
        token = secrets.token_urlsafe(32)

        # Calculate expiration
        expires_at = datetime.utcnow() + timedelta(hours=self.token_expire_hours)

        # Create token record
        verification_token = EmailVerificationToken(
            user_id=user_id,
            token=token,
            expires_at=expires_at,
        )

        session.add(verification_token)
        await session.commit()

        logger.info(f"Generated verification token for user {user_id} (expires: {expires_at})")
        return token

    async def verify_email_token(
        self, session: AsyncSession, token: str
    ) -> Optional[User]:
        """
        Verify an email verification token and mark user as verified.

        Validates the token, checks expiration, marks the token as used,
        and sets the user's is_verified flag to True.

        Args:
            session: Database session
            token: Verification token string

        Returns:
            Optional[User]: Verified user if token is valid, None otherwise

        Example:
            >>> user = await verification_service.verify_email_token(session, token)
            >>> if user:
            ...     print(f"User {user.email} verified!")
            ... else:
            ...     print("Invalid or expired token")

        Token Validation:
            - Token must exist in database
            - Token must not be expired
            - Token must not have been used already
            - User must exist and be active
        """
        # Look up token
        stmt = select(EmailVerificationToken).where(
            EmailVerificationToken.token == token
        )
        result = await session.execute(stmt)
        verification_token = result.scalar_one_or_none()

        if not verification_token:
            logger.warning("Verification token not found")
            return None

        # Check if already used
        if verification_token.used_at:
            logger.warning(f"Verification token already used at {verification_token.used_at}")
            return None

        # Check expiration
        if datetime.utcnow() > verification_token.expires_at:
            logger.warning(f"Verification token expired at {verification_token.expires_at}")
            return None

        # Look up user
        stmt = select(User).where(User.id == verification_token.user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.error(f"User not found for verification token: {verification_token.user_id}")
            return None

        if not user.is_active:
            logger.warning(f"User {user.id} is not active")
            return None

        # Mark token as used
        verification_token.used_at = datetime.utcnow()

        # Mark user as verified
        user.is_verified = True

        await session.commit()
        await session.refresh(user)

        logger.info(f"Email verified successfully for user {user.id} ({user.email})")
        return user

    async def resend_verification_email(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> bool:
        """
        Resend verification email to a user.

        Generates a new verification token and sends a new verification email.
        Old unused tokens remain valid until they expire.

        Args:
            session: Database session
            user_id: User's UUID

        Returns:
            bool: True if email was sent successfully, False otherwise

        Example:
            >>> success = await verification_service.resend_verification_email(session, user_id)
            >>> if success:
            ...     print("Verification email resent")
        """
        # Look up user
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.error(f"User not found: {user_id}")
            return False

        if user.is_verified:
            logger.info(f"User {user.id} is already verified")
            return True  # Already verified, no need to send

        # Generate new token
        token = await self.generate_verification_token(session, user_id)

        # Send email via Celery task
        from app.tasks import send_verification_email_task

        try:
            send_verification_email_task.delay(
                user_email=user.email,
                user_name=user.full_name or user.username,
                verification_token=token,
            )
            logger.info(f"Verification email queued for {user.email}")
            return True
        except Exception as e:
            logger.error(f"Failed to queue verification email for {user.email}: {e}")
            return False

    async def is_verification_required(self, user: User) -> bool:
        """
        Check if email verification is required for a user.

        Users have a grace period after account creation where they can
        access the system without verification. After the grace period,
        verification is required.

        Args:
            user: User object

        Returns:
            bool: True if verification is required, False if still in grace period

        Example:
            >>> if await verification_service.is_verification_required(user):
            ...     raise HTTPException(403, "Email verification required")

        Grace Period:
            - Verified users: No verification required
            - Within grace period: No verification required
            - After grace period: Verification required
        """
        if user.is_verified:
            return False

        # Check if user is within grace period
        grace_period_end = user.created_at + timedelta(days=self.grace_period_days)
        is_within_grace_period = datetime.utcnow() < grace_period_end

        if is_within_grace_period:
            logger.debug(
                f"User {user.id} within grace period (ends: {grace_period_end})"
            )
            return False

        logger.debug(f"User {user.id} verification required (grace period ended: {grace_period_end})")
        return True

    async def cleanup_expired_tokens(self, session: AsyncSession) -> int:
        """
        Clean up expired verification tokens.

        Removes all expired tokens from the database to keep the table clean.
        This should be run periodically via a Celery task.

        Args:
            session: Database session

        Returns:
            int: Number of tokens deleted

        Example:
            >>> deleted = await verification_service.cleanup_expired_tokens(session)
            >>> print(f"Deleted {deleted} expired tokens")
        """
        stmt = select(EmailVerificationToken).where(
            EmailVerificationToken.expires_at < datetime.utcnow()
        )
        result = await session.execute(stmt)
        expired_tokens = result.scalars().all()

        count = len(expired_tokens)
        for token in expired_tokens:
            await session.delete(token)

        await session.commit()

        logger.info(f"Cleaned up {count} expired verification tokens")
        return count


# Global singleton instance
verification_service = VerificationService()
