# backend/app/services/auth_service.py
"""
Authentication service for Curatore v2.

Provides JWT token management, API key generation/validation, and password hashing
for user authentication and authorization.

Key Features:
    - JWT token generation (access + refresh tokens)
    - JWT token validation and decoding
    - API key generation with bcrypt hashing
    - API key validation
    - Password hashing with bcrypt
    - Token refresh logic

Usage:
    from app.core.auth.auth_service import auth_service

    # Hash password
    hashed = await auth_service.hash_password("password123")

    # Verify password
    is_valid = await auth_service.verify_password("password123", hashed)

    # Create access token
    access_token = auth_service.create_access_token(user_id="user-uuid", org_id="org-uuid")

    # Validate token
    payload = auth_service.decode_token(access_token)

    # Generate API key
    api_key, key_hash = auth_service.generate_api_key()

Dependencies:
    - PyJWT for JWT token handling
    - bcrypt for password/API key hashing
    - passlib for password utilities

Configuration:
    Uses settings from config.py:
    - JWT_SECRET_KEY: Secret key for signing JWT tokens
    - JWT_ALGORITHM: Algorithm for JWT signing (default: HS256)
    - JWT_ACCESS_TOKEN_EXPIRE_MINUTES: Access token TTL
    - JWT_REFRESH_TOKEN_EXPIRE_DAYS: Refresh token TTL
    - BCRYPT_ROUNDS: Work factor for bcrypt hashing
    - API_KEY_PREFIX: Prefix for generated API keys (default: cur_)

Security Notes:
    - Always use bcrypt for password/API key hashing (never store plaintext)
    - JWT tokens should be transmitted over HTTPS only
    - Access tokens have short expiration (60 min default)
    - Refresh tokens have longer expiration (30 days default)
    - API keys are shown only once on creation, then hashed
    - Use constant-time comparison for password/key verification
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import bcrypt
import jwt
from passlib.context import CryptContext

from app.config import settings

# Configure password context with bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """
    Authentication service for managing JWT tokens, API keys, and passwords.

    This service provides cryptographic operations for authentication including:
    - Password hashing and verification
    - JWT token generation and validation
    - API key generation and validation

    The service is implemented as a singleton and should be imported as:
        from app.core.auth.auth_service import auth_service

    Attributes:
        _logger: Logger instance for authentication events
        jwt_secret: Secret key for JWT signing
        jwt_algorithm: Algorithm for JWT signing
        access_token_expire: Timedelta for access token expiration
        refresh_token_expire: Timedelta for refresh token expiration
        bcrypt_rounds: Work factor for bcrypt hashing
        api_key_prefix: Prefix for generated API keys
    """

    def __init__(self):
        """Initialize the authentication service with settings from config."""
        self._logger = logging.getLogger("curatore.auth")

        # JWT configuration
        self.jwt_secret = settings.jwt_secret_key
        self.jwt_algorithm = settings.jwt_algorithm
        self.access_token_expire = timedelta(minutes=settings.jwt_access_token_expire_minutes)
        self.refresh_token_expire = timedelta(days=settings.jwt_refresh_token_expire_days)

        # Bcrypt configuration
        self.bcrypt_rounds = settings.bcrypt_rounds

        # API key configuration
        self.api_key_prefix = settings.api_key_prefix

        self._logger.info(
            f"AuthService initialized (JWT algo: {self.jwt_algorithm}, "
            f"access token TTL: {self.access_token_expire}, "
            f"bcrypt rounds: {self.bcrypt_rounds})"
        )

    # =========================================================================
    # PASSWORD HASHING & VERIFICATION
    # =========================================================================

    async def hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.

        Uses the configured bcrypt work factor from settings. The hash includes
        a randomly generated salt and is safe to store in the database.

        Args:
            password: Plain text password to hash

        Returns:
            str: Bcrypt hash of the password (includes salt)

        Example:
            >>> hashed = await auth_service.hash_password("password123")
            >>> print(hashed)
            '$2b$12$...'

        Security:
            - Never store passwords in plain text
            - Each hash includes a unique random salt
            - Bcrypt is computationally expensive to prevent brute force attacks
        """
        self._logger.debug("Hashing password")
        password_bytes = password.encode("utf-8")
        salt = bcrypt.gensalt(rounds=self.bcrypt_rounds)
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode("utf-8")

    async def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against a bcrypt hash.

        Uses constant-time comparison to prevent timing attacks.

        Args:
            plain_password: Plain text password to verify
            hashed_password: Bcrypt hash to verify against

        Returns:
            bool: True if password matches, False otherwise

        Example:
            >>> hashed = await auth_service.hash_password("password123")
            >>> is_valid = await auth_service.verify_password("password123", hashed)
            >>> print(is_valid)
            True
            >>> is_valid = await auth_service.verify_password("wrong", hashed)
            >>> print(is_valid)
            False

        Security:
            - Uses constant-time comparison to prevent timing attacks
            - Returns False for any errors (invalid hash, etc.)
        """
        self._logger.debug("Verifying password")
        try:
            password_bytes = plain_password.encode("utf-8")
            hashed_bytes = hashed_password.encode("utf-8")
            return bcrypt.checkpw(password_bytes, hashed_bytes)
        except Exception as e:
            self._logger.warning(f"Password verification failed: {e}")
            return False

    # =========================================================================
    # JWT TOKEN GENERATION & VALIDATION
    # =========================================================================

    def create_access_token(
        self,
        user_id: str,
        organization_id: Optional[str],
        role: str = "member",
        additional_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a JWT access token for a user.

        Access tokens have short expiration (default 60 minutes) and are used
        for authenticating API requests.

        Args:
            user_id: User's UUID as string
            organization_id: Organization's UUID as string (None for system admins)
            role: User's role (admin, org_admin, member, viewer)
            additional_claims: Optional additional JWT claims

        Returns:
            str: Encoded JWT access token

        Example:
            >>> token = auth_service.create_access_token(
            ...     user_id="123e4567-e89b-12d3-a456-426614174000",
            ...     organization_id="987fcdeb-51a2-43f7-8b6a-123456789abc",
            ...     role="org_admin"
            ... )
            >>> print(token)
            'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'

        Token Claims:
            - sub: User ID (subject)
            - org_id: Organization ID (null for system admins)
            - role: User role
            - type: "access"
            - exp: Expiration timestamp
            - iat: Issued at timestamp
            - Additional claims if provided

        Note:
            For admin users (role='admin'), organization_id is None.
            These users can access any organization via X-Organization-Id header.
        """
        now = datetime.utcnow()
        expire = now + self.access_token_expire

        # Standard JWT claims
        claims = {
            "sub": user_id,  # Subject (user ID)
            "org_id": organization_id,  # None for admin users
            "role": role,
            "type": "access",
            "exp": expire,  # Expiration time
            "iat": now,  # Issued at
        }

        # Add any additional claims
        if additional_claims:
            claims.update(additional_claims)

        token = jwt.encode(claims, self.jwt_secret, algorithm=self.jwt_algorithm)
        self._logger.debug(f"Created access token for user {user_id} (expires in {self.access_token_expire})")

        return token

    def create_refresh_token(
        self,
        user_id: str,
        organization_id: Optional[str],
        additional_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a JWT refresh token for a user.

        Refresh tokens have longer expiration (default 30 days) and are used
        to obtain new access tokens without requiring re-authentication.

        Args:
            user_id: User's UUID as string
            organization_id: Organization's UUID as string (None for system admins)
            additional_claims: Optional additional JWT claims

        Returns:
            str: Encoded JWT refresh token

        Example:
            >>> token = auth_service.create_refresh_token(
            ...     user_id="123e4567-e89b-12d3-a456-426614174000",
            ...     organization_id="987fcdeb-51a2-43f7-8b6a-123456789abc"
            ... )

        Token Claims:
            - sub: User ID (subject)
            - org_id: Organization ID (null for system admins)
            - type: "refresh"
            - exp: Expiration timestamp
            - iat: Issued at timestamp
            - Additional claims if provided

        Security:
            - Refresh tokens should be stored securely (httpOnly cookies recommended)
            - Consider implementing token rotation on refresh
            - Invalidate refresh tokens on logout

        Note:
            For admin users (role='admin'), organization_id is None.
        """
        now = datetime.utcnow()
        expire = now + self.refresh_token_expire

        claims = {
            "sub": user_id,
            "org_id": organization_id,  # None for admin users
            "type": "refresh",
            "exp": expire,
            "iat": now,
        }

        if additional_claims:
            claims.update(additional_claims)

        token = jwt.encode(claims, self.jwt_secret, algorithm=self.jwt_algorithm)
        self._logger.debug(f"Created refresh token for user {user_id} (expires in {self.refresh_token_expire})")

        return token

    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        Decode and validate a JWT token.

        Validates the token signature, expiration, and returns the payload.
        Raises exceptions for invalid tokens.

        Args:
            token: JWT token string to decode

        Returns:
            Dict[str, Any]: Token payload with claims

        Raises:
            jwt.ExpiredSignatureError: Token has expired
            jwt.InvalidTokenError: Token is invalid (bad signature, malformed, etc.)

        Example:
            >>> token = auth_service.create_access_token(user_id="...", organization_id="...")
            >>> payload = auth_service.decode_token(token)
            >>> print(payload)
            {
                'sub': '123e4567-e89b-12d3-a456-426614174000',
                'org_id': '987fcdeb-51a2-43f7-8b6a-123456789abc',
                'role': 'member',
                'type': 'access',
                'exp': 1234567890,
                'iat': 1234564290
            }

        Security:
            - Always validate tokens before trusting claims
            - Check token type (access vs refresh) for appropriate endpoints
            - Verify organization_id matches expected context
        """
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            self._logger.warning("Token has expired")
            raise
        except jwt.InvalidTokenError as e:
            self._logger.warning(f"Invalid token: {e}")
            raise

    def verify_token_type(self, payload: Dict[str, Any], expected_type: str) -> bool:
        """
        Verify that a token payload has the expected type.

        Args:
            payload: Decoded JWT payload
            expected_type: Expected token type ("access" or "refresh")

        Returns:
            bool: True if token type matches, False otherwise

        Example:
            >>> payload = auth_service.decode_token(access_token)
            >>> is_access = auth_service.verify_token_type(payload, "access")
            >>> print(is_access)
            True
        """
        token_type = payload.get("type")
        if token_type != expected_type:
            self._logger.warning(f"Token type mismatch: expected {expected_type}, got {token_type}")
            return False
        return True

    # =========================================================================
    # API KEY GENERATION & VALIDATION
    # =========================================================================

    def generate_api_key(self) -> Tuple[str, str, str]:
        """
        Generate a new API key with prefix and hash.

        API keys are generated using cryptographically secure random bytes,
        prefixed with the configured prefix (default: "cur_"), and hashed
        with bcrypt for storage.

        Returns:
            Tuple[str, str, str]: (full_key, key_hash, prefix)
                - full_key: Complete API key to show user (ONLY SHOWN ONCE)
                - key_hash: Bcrypt hash to store in database
                - prefix: Key prefix for display (e.g., "cur_abcd1234")

        Example:
            >>> full_key, key_hash, prefix = auth_service.generate_api_key()
            >>> print(f"Your API key (save this!): {full_key}")
            Your API key (save this!): cur_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p
            >>> print(f"Prefix for display: {prefix}")
            Prefix for display: cur_1a2b3c4d
            >>> print(f"Hash to store: {key_hash}")
            Hash to store: $2b$12$...

        Security:
            - Use secrets module for cryptographically secure random generation
            - Store only the hash in database, never the plaintext key
            - Show the full key to user ONLY ONCE on creation
            - Prefix allows displaying partial key for user identification
        """
        # Generate 32 bytes of random data (64 hex characters)
        random_bytes = secrets.token_hex(32)

        # Create full key with prefix
        full_key = f"{self.api_key_prefix}{random_bytes}"

        # Create prefix for display (prefix + first 8 chars)
        display_prefix = full_key[:len(self.api_key_prefix) + 8]

        # Hash the full key for storage
        key_hash = bcrypt.hashpw(full_key.encode("utf-8"), bcrypt.gensalt(rounds=self.bcrypt_rounds))
        key_hash_str = key_hash.decode("utf-8")

        self._logger.info(f"Generated new API key with prefix {display_prefix}")

        return full_key, key_hash_str, display_prefix

    async def verify_api_key(self, plain_key: str, hashed_key: str) -> bool:
        """
        Verify an API key against its bcrypt hash.

        Uses constant-time comparison to prevent timing attacks.

        Args:
            plain_key: Plain text API key from request
            hashed_key: Bcrypt hash from database

        Returns:
            bool: True if key matches, False otherwise

        Example:
            >>> full_key, key_hash, prefix = auth_service.generate_api_key()
            >>> is_valid = await auth_service.verify_api_key(full_key, key_hash)
            >>> print(is_valid)
            True
            >>> is_valid = await auth_service.verify_api_key("wrong_key", key_hash)
            >>> print(is_valid)
            False

        Security:
            - Uses constant-time comparison to prevent timing attacks
            - Returns False for any errors (invalid hash, etc.)
        """
        self._logger.debug("Verifying API key")
        try:
            key_bytes = plain_key.encode("utf-8")
            hash_bytes = hashed_key.encode("utf-8")
            return bcrypt.checkpw(key_bytes, hash_bytes)
        except Exception as e:
            self._logger.warning(f"API key verification failed: {e}")
            return False

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_token_expiration(self, token: str) -> Optional[datetime]:
        """
        Get the expiration datetime of a token.

        Args:
            token: JWT token string

        Returns:
            Optional[datetime]: Expiration datetime, or None if token is invalid

        Example:
            >>> token = auth_service.create_access_token(user_id="...", organization_id="...")
            >>> exp = auth_service.get_token_expiration(token)
            >>> print(f"Token expires at: {exp}")
            Token expires at: 2024-01-12 15:30:00
        """
        try:
            payload = self.decode_token(token)
            exp_timestamp = payload.get("exp")
            if exp_timestamp:
                return datetime.fromtimestamp(exp_timestamp)
            return None
        except Exception:
            return None

    def is_token_expired(self, token: str) -> bool:
        """
        Check if a token is expired without raising an exception.

        Args:
            token: JWT token string

        Returns:
            bool: True if expired or invalid, False if still valid

        Example:
            >>> is_expired = auth_service.is_token_expired(old_token)
            >>> if is_expired:
            ...     print("Token needs refresh")
        """
        try:
            self.decode_token(token)
            return False
        except jwt.ExpiredSignatureError:
            return True
        except jwt.InvalidTokenError:
            return True


# Global singleton instance
auth_service = AuthService()
