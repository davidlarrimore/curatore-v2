"""
Unit tests for AuthService.

Tests JWT token management, API key generation/validation, and password hashing
for user authentication and authorization.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from app.config import settings
from app.core.auth.auth_service import AuthService, auth_service


@pytest.fixture
def auth_service_instance():
    """Create AuthService instance for testing."""
    return AuthService()


class TestAuthServiceInitialization:
    """Test AuthService initialization."""

    def test_initialization(self, auth_service_instance):
        """Test service initializes with correct settings."""
        assert auth_service_instance.jwt_secret is not None
        assert auth_service_instance.jwt_algorithm is not None
        assert auth_service_instance.access_token_expire is not None
        assert auth_service_instance.refresh_token_expire is not None
        assert auth_service_instance.bcrypt_rounds > 0
        assert auth_service_instance.api_key_prefix is not None

    def test_singleton_instance(self):
        """Test that auth_service is a singleton instance."""
        assert auth_service is not None
        assert isinstance(auth_service, AuthService)

    def test_configuration_loaded(self, auth_service_instance):
        """Test that configuration is loaded from settings."""
        assert auth_service_instance.jwt_secret == settings.jwt_secret_key
        assert auth_service_instance.jwt_algorithm == settings.jwt_algorithm
        assert auth_service_instance.bcrypt_rounds == settings.bcrypt_rounds
        assert auth_service_instance.api_key_prefix == settings.api_key_prefix


class TestPasswordHashing:
    """Test password hashing and verification."""

    @pytest.mark.asyncio
    async def test_hash_password(self, auth_service_instance):
        """Test password hashing."""
        password = "password123"
        hashed = await auth_service_instance.hash_password(password)

        # Verify hash format (bcrypt hashes start with $2b$)
        assert hashed.startswith("$2b$")
        assert len(hashed) == 60  # Bcrypt hashes are always 60 chars

    @pytest.mark.asyncio
    async def test_hash_password_different_each_time(self, auth_service_instance):
        """Test that hashing the same password produces different hashes (due to salt)."""
        password = "password123"
        hash1 = await auth_service_instance.hash_password(password)
        hash2 = await auth_service_instance.hash_password(password)

        # Hashes should be different (different salts)
        assert hash1 != hash2

    @pytest.mark.asyncio
    async def test_verify_password_correct(self, auth_service_instance):
        """Test password verification with correct password."""
        password = "password123"
        hashed = await auth_service_instance.hash_password(password)

        is_valid = await auth_service_instance.verify_password(password, hashed)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_verify_password_incorrect(self, auth_service_instance):
        """Test password verification with incorrect password."""
        password = "password123"
        hashed = await auth_service_instance.hash_password(password)

        is_valid = await auth_service_instance.verify_password("wrong_password", hashed)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_verify_password_empty(self, auth_service_instance):
        """Test password verification with empty password."""
        password = "password123"
        hashed = await auth_service_instance.hash_password(password)

        is_valid = await auth_service_instance.verify_password("", hashed)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_verify_password_invalid_hash(self, auth_service_instance):
        """Test password verification with invalid hash."""
        is_valid = await auth_service_instance.verify_password("password123", "invalid_hash")
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_hash_special_characters(self, auth_service_instance):
        """Test hashing password with special characters."""
        password = "P@ssw0rd!#$%&*()_+-=[]{}|;:',.<>?/"
        hashed = await auth_service_instance.hash_password(password)

        is_valid = await auth_service_instance.verify_password(password, hashed)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_hash_unicode_characters(self, auth_service_instance):
        """Test hashing password with unicode characters."""
        password = "pässwörd123密码"
        hashed = await auth_service_instance.hash_password(password)

        is_valid = await auth_service_instance.verify_password(password, hashed)
        assert is_valid is True


class TestAccessTokenGeneration:
    """Test JWT access token generation."""

    def test_create_access_token_basic(self, auth_service_instance):
        """Test creating access token with basic parameters."""
        user_id = "123e4567-e89b-12d3-a456-426614174000"
        org_id = "987fcdeb-51a2-43f7-8b6a-123456789abc"

        token = auth_service_instance.create_access_token(
            user_id=user_id,
            organization_id=org_id,
        )

        # Verify token is a string
        assert isinstance(token, str)
        assert len(token) > 0

        # Decode and verify payload
        payload = auth_service_instance.decode_token(token)
        assert payload["sub"] == user_id
        assert payload["org_id"] == org_id
        assert payload["type"] == "access"
        assert payload["role"] == "member"  # Default role

    def test_create_access_token_with_role(self, auth_service_instance):
        """Test creating access token with specific role."""
        user_id = "user-123"
        org_id = "org-456"
        role = "member"

        token = auth_service_instance.create_access_token(
            user_id=user_id,
            organization_id=org_id,
            role=role,
        )

        payload = auth_service_instance.decode_token(token)
        assert payload["role"] == role

    def test_create_access_token_with_additional_claims(self, auth_service_instance):
        """Test creating access token with additional claims."""
        user_id = "user-123"
        org_id = "org-456"
        additional_claims = {
            "email": "user@example.com",
            "custom_field": "custom_value",
        }

        token = auth_service_instance.create_access_token(
            user_id=user_id,
            organization_id=org_id,
            additional_claims=additional_claims,
        )

        payload = auth_service_instance.decode_token(token)
        assert payload["email"] == "user@example.com"
        assert payload["custom_field"] == "custom_value"

    def test_access_token_expiration_set(self, auth_service_instance):
        """Test that access token has expiration set."""
        token = auth_service_instance.create_access_token(
            user_id="user-123",
            organization_id="org-456",
        )

        payload = auth_service_instance.decode_token(token)
        assert "exp" in payload
        assert "iat" in payload

        # Verify expiration is in the future
        exp = datetime.fromtimestamp(payload["exp"])
        iat = datetime.fromtimestamp(payload["iat"])
        assert exp > iat

        # Verify expiration is approximately correct
        expected_expire = timedelta(minutes=settings.jwt_access_token_expire_minutes)
        actual_expire = exp - iat
        assert abs(actual_expire.total_seconds() - expected_expire.total_seconds()) < 5


class TestRefreshTokenGeneration:
    """Test JWT refresh token generation."""

    def test_create_refresh_token_basic(self, auth_service_instance):
        """Test creating refresh token with basic parameters."""
        user_id = "user-789"
        org_id = "org-abc"

        token = auth_service_instance.create_refresh_token(
            user_id=user_id,
            organization_id=org_id,
        )

        # Verify token is a string
        assert isinstance(token, str)
        assert len(token) > 0

        # Decode and verify payload
        payload = auth_service_instance.decode_token(token)
        assert payload["sub"] == user_id
        assert payload["org_id"] == org_id
        assert payload["type"] == "refresh"

    def test_create_refresh_token_with_additional_claims(self, auth_service_instance):
        """Test creating refresh token with additional claims."""
        user_id = "user-123"
        org_id = "org-456"
        additional_claims = {"session_id": "sess-xyz"}

        token = auth_service_instance.create_refresh_token(
            user_id=user_id,
            organization_id=org_id,
            additional_claims=additional_claims,
        )

        payload = auth_service_instance.decode_token(token)
        assert payload["session_id"] == "sess-xyz"

    def test_refresh_token_expiration_longer_than_access(self, auth_service_instance):
        """Test that refresh token expiration is longer than access token."""
        user_id = "user-123"
        org_id = "org-456"

        access_token = auth_service_instance.create_access_token(user_id, org_id)
        refresh_token = auth_service_instance.create_refresh_token(user_id, org_id)

        access_payload = auth_service_instance.decode_token(access_token)
        refresh_payload = auth_service_instance.decode_token(refresh_token)

        access_exp = datetime.fromtimestamp(access_payload["exp"])
        refresh_exp = datetime.fromtimestamp(refresh_payload["exp"])

        # Refresh token should expire much later than access token
        assert refresh_exp > access_exp

    def test_refresh_token_no_role_claim(self, auth_service_instance):
        """Test that refresh token does not include role claim."""
        token = auth_service_instance.create_refresh_token(
            user_id="user-123",
            organization_id="org-456",
        )

        payload = auth_service_instance.decode_token(token)
        assert "role" not in payload


class TestTokenDecoding:
    """Test JWT token decoding and validation."""

    def test_decode_valid_token(self, auth_service_instance):
        """Test decoding a valid token."""
        user_id = "user-123"
        org_id = "org-456"

        token = auth_service_instance.create_access_token(user_id, org_id)
        payload = auth_service_instance.decode_token(token)

        assert payload["sub"] == user_id
        assert payload["org_id"] == org_id

    def test_decode_invalid_token(self, auth_service_instance):
        """Test decoding an invalid token."""
        with pytest.raises(jwt.InvalidTokenError):
            auth_service_instance.decode_token("invalid.token.here")

    def test_decode_expired_token(self, auth_service_instance):
        """Test decoding an expired token."""
        # Create a token that expires immediately
        with patch.object(auth_service_instance, 'access_token_expire', timedelta(seconds=-1)):
            token = auth_service_instance.create_access_token(
                user_id="user-123",
                organization_id="org-456",
            )

        # Wait a moment to ensure expiration
        import time
        time.sleep(0.1)

        # Should raise ExpiredSignatureError
        with pytest.raises(jwt.ExpiredSignatureError):
            auth_service_instance.decode_token(token)

    def test_decode_tampered_token(self, auth_service_instance):
        """Test decoding a tampered token."""
        token = auth_service_instance.create_access_token(
            user_id="user-123",
            organization_id="org-456",
        )

        # Tamper with the token
        tampered = token[:-10] + "tamperedXX"

        with pytest.raises(jwt.InvalidTokenError):
            auth_service_instance.decode_token(tampered)

    def test_decode_token_wrong_secret(self, auth_service_instance):
        """Test decoding token signed with wrong secret."""
        # Create token with different secret
        wrong_secret = "wrong_secret_key_12345"
        payload = {"sub": "user-123", "org_id": "org-456"}
        token = jwt.encode(payload, wrong_secret, algorithm="HS256")

        with pytest.raises(jwt.InvalidTokenError):
            auth_service_instance.decode_token(token)


class TestTokenTypeVerification:
    """Test token type verification."""

    def test_verify_access_token_type(self, auth_service_instance):
        """Test verifying access token type."""
        token = auth_service_instance.create_access_token(
            user_id="user-123",
            organization_id="org-456",
        )
        payload = auth_service_instance.decode_token(token)

        is_valid = auth_service_instance.verify_token_type(payload, "access")
        assert is_valid is True

    def test_verify_refresh_token_type(self, auth_service_instance):
        """Test verifying refresh token type."""
        token = auth_service_instance.create_refresh_token(
            user_id="user-123",
            organization_id="org-456",
        )
        payload = auth_service_instance.decode_token(token)

        is_valid = auth_service_instance.verify_token_type(payload, "refresh")
        assert is_valid is True

    def test_verify_wrong_token_type(self, auth_service_instance):
        """Test verifying wrong token type."""
        token = auth_service_instance.create_access_token(
            user_id="user-123",
            organization_id="org-456",
        )
        payload = auth_service_instance.decode_token(token)

        # Expect refresh but got access
        is_valid = auth_service_instance.verify_token_type(payload, "refresh")
        assert is_valid is False

    def test_verify_token_type_missing(self, auth_service_instance):
        """Test verifying token with missing type claim."""
        payload = {"sub": "user-123", "org_id": "org-456"}

        is_valid = auth_service_instance.verify_token_type(payload, "access")
        assert is_valid is False


class TestAPIKeyGeneration:
    """Test API key generation."""

    def test_generate_api_key(self, auth_service_instance):
        """Test generating an API key."""
        full_key, key_hash, prefix = auth_service_instance.generate_api_key()

        # Verify full key format
        assert full_key.startswith(settings.api_key_prefix)
        assert len(full_key) == len(settings.api_key_prefix) + 64  # prefix + 32 bytes hex

        # Verify hash format
        assert key_hash.startswith("$2b$")
        assert len(key_hash) == 60  # Bcrypt hash length

        # Verify prefix format
        assert prefix.startswith(settings.api_key_prefix)
        assert len(prefix) == len(settings.api_key_prefix) + 8

    def test_generate_api_key_unique(self, auth_service_instance):
        """Test that generated API keys are unique."""
        key1, hash1, prefix1 = auth_service_instance.generate_api_key()
        key2, hash2, prefix2 = auth_service_instance.generate_api_key()

        # Keys should be different
        assert key1 != key2
        assert hash1 != hash2
        assert prefix1 != prefix2

    def test_generate_api_key_prefix_visible(self, auth_service_instance):
        """Test that prefix is first N characters of full key."""
        full_key, _, prefix = auth_service_instance.generate_api_key()

        # Prefix should be the beginning of full key
        assert full_key.startswith(prefix)

    def test_api_key_format(self, auth_service_instance):
        """Test API key format (prefix + hex)."""
        full_key, _, _ = auth_service_instance.generate_api_key()

        # Remove prefix and verify remaining is hex
        key_without_prefix = full_key[len(settings.api_key_prefix):]
        assert all(c in "0123456789abcdef" for c in key_without_prefix)


class TestAPIKeyVerification:
    """Test API key verification."""

    @pytest.mark.asyncio
    async def test_verify_api_key_correct(self, auth_service_instance):
        """Test verifying correct API key."""
        full_key, key_hash, _ = auth_service_instance.generate_api_key()

        is_valid = await auth_service_instance.verify_api_key(full_key, key_hash)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_verify_api_key_incorrect(self, auth_service_instance):
        """Test verifying incorrect API key."""
        full_key, key_hash, _ = auth_service_instance.generate_api_key()

        is_valid = await auth_service_instance.verify_api_key("wrong_key", key_hash)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_verify_api_key_invalid_hash(self, auth_service_instance):
        """Test verifying API key with invalid hash."""
        full_key, _, _ = auth_service_instance.generate_api_key()

        is_valid = await auth_service_instance.verify_api_key(full_key, "invalid_hash")
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_verify_api_key_empty(self, auth_service_instance):
        """Test verifying empty API key."""
        _, key_hash, _ = auth_service_instance.generate_api_key()

        is_valid = await auth_service_instance.verify_api_key("", key_hash)
        assert is_valid is False


class TestTokenExpirationUtilities:
    """Test token expiration utility methods."""

    def test_get_token_expiration(self, auth_service_instance):
        """Test getting token expiration datetime."""
        token = auth_service_instance.create_access_token(
            user_id="user-123",
            organization_id="org-456",
        )

        exp_datetime = auth_service_instance.get_token_expiration(token)

        assert exp_datetime is not None
        assert isinstance(exp_datetime, datetime)
        # Compare against local time since get_token_expiration returns local time
        assert exp_datetime > datetime.now()

    def test_get_token_expiration_invalid_token(self, auth_service_instance):
        """Test getting expiration for invalid token."""
        exp_datetime = auth_service_instance.get_token_expiration("invalid.token")

        assert exp_datetime is None

    def test_is_token_expired_valid(self, auth_service_instance):
        """Test checking if valid token is expired."""
        token = auth_service_instance.create_access_token(
            user_id="user-123",
            organization_id="org-456",
        )

        is_expired = auth_service_instance.is_token_expired(token)
        assert is_expired is False

    def test_is_token_expired_expired(self, auth_service_instance):
        """Test checking if expired token is expired."""
        # Create token that expires immediately
        with patch.object(auth_service_instance, 'access_token_expire', timedelta(seconds=-1)):
            token = auth_service_instance.create_access_token(
                user_id="user-123",
                organization_id="org-456",
            )

        import time
        time.sleep(0.1)

        is_expired = auth_service_instance.is_token_expired(token)
        assert is_expired is True

    def test_is_token_expired_invalid(self, auth_service_instance):
        """Test checking if invalid token is expired."""
        is_expired = auth_service_instance.is_token_expired("invalid.token")
        assert is_expired is True  # Invalid tokens are considered expired


class TestSecurityProperties:
    """Test security properties of the auth service."""

    @pytest.mark.asyncio
    async def test_password_constant_time_comparison(self, auth_service_instance):
        """Test that password verification uses constant-time comparison."""
        password = "password123"
        hashed = await auth_service_instance.hash_password(password)

        # Both correct and incorrect should take similar time (constant-time)
        # This is ensured by bcrypt.checkpw
        import time

        start = time.time()
        await auth_service_instance.verify_password("wrong", hashed)
        wrong_time = time.time() - start

        start = time.time()
        await auth_service_instance.verify_password(password, hashed)
        correct_time = time.time() - start

        # Time difference should be minimal (within 10x)
        # Note: This is a simplified test; timing attacks are complex
        assert abs(wrong_time - correct_time) < 1.0

    def test_jwt_secret_not_exposed(self, auth_service_instance):
        """Test that JWT secret is not exposed in tokens."""
        token = auth_service_instance.create_access_token(
            user_id="user-123",
            organization_id="org-456",
        )

        # Decode without verification to check contents
        unverified = jwt.decode(token, options={"verify_signature": False})

        # Secret should not be in payload
        assert settings.jwt_secret_key not in str(unverified)

    @pytest.mark.asyncio
    async def test_password_hash_includes_salt(self, auth_service_instance):
        """Test that password hashes include unique salts."""
        password = "password123"

        # Generate multiple hashes
        hashes = [await auth_service_instance.hash_password(password) for _ in range(5)]

        # All hashes should be different (different salts)
        assert len(set(hashes)) == 5

    def test_api_key_cryptographically_secure(self, auth_service_instance):
        """Test that API keys use cryptographically secure random generation."""
        # Generate many keys
        keys = [auth_service_instance.generate_api_key()[0] for _ in range(100)]

        # All should be unique
        assert len(set(keys)) == 100

        # Keys should have high entropy (no obvious patterns)
        # Check that keys don't start with common patterns
        for key in keys:
            key_part = key[len(settings.api_key_prefix):]
            assert not key_part.startswith("00000")
            assert not key_part.startswith("11111")
            assert not key_part.startswith("aaaaa")


class TestErrorHandling:
    """Test error handling in auth service."""

    @pytest.mark.asyncio
    async def test_verify_password_handles_malformed_hash(self, auth_service_instance):
        """Test that password verification handles malformed hashes gracefully."""
        is_valid = await auth_service_instance.verify_password("password", "malformed_hash")
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_verify_api_key_handles_malformed_hash(self, auth_service_instance):
        """Test that API key verification handles malformed hashes gracefully."""
        is_valid = await auth_service_instance.verify_api_key("key", "malformed_hash")
        assert is_valid is False

    def test_decode_token_handles_none(self, auth_service_instance):
        """Test that decode_token handles None gracefully."""
        with pytest.raises((jwt.InvalidTokenError, AttributeError, TypeError)):
            auth_service_instance.decode_token(None)

    def test_decode_token_handles_empty_string(self, auth_service_instance):
        """Test that decode_token handles empty string gracefully."""
        with pytest.raises(jwt.InvalidTokenError):
            auth_service_instance.decode_token("")


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_hash_very_long_password(self, auth_service_instance):
        """Test hashing very long password."""
        password = "a" * 1000  # Very long password
        hashed = await auth_service_instance.hash_password(password)

        is_valid = await auth_service_instance.verify_password(password, hashed)
        assert is_valid is True

    def test_create_token_with_empty_user_id(self, auth_service_instance):
        """Test creating token with empty user ID."""
        token = auth_service_instance.create_access_token(
            user_id="",
            organization_id="org-456",
        )

        payload = auth_service_instance.decode_token(token)
        assert payload["sub"] == ""

    def test_create_token_with_very_long_claims(self, auth_service_instance):
        """Test creating token with very long additional claims."""
        long_value = "x" * 10000
        token = auth_service_instance.create_access_token(
            user_id="user-123",
            organization_id="org-456",
            additional_claims={"long_field": long_value},
        )

        payload = auth_service_instance.decode_token(token)
        assert payload["long_field"] == long_value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
