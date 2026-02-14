# backend/tests/test_delegated_auth.py
"""Tests for delegated authentication (ServiceAccount + X-On-Behalf-Of)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from contextlib import asynccontextmanager

from app.core.database.models import ServiceAccount, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(email="alice@company.com", org_id=None, role="member", is_active=True):
    """Create a mock User object that passes isinstance(obj, User)."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.organization_id = org_id or uuid.uuid4()
    user.role = role
    user.is_active = is_active
    return user


def _make_service_account(name="MCP Gateway", org_id=None, is_active=True):
    """Create a mock ServiceAccount object that passes isinstance(obj, ServiceAccount)."""
    sa = MagicMock(spec=ServiceAccount)
    sa.id = uuid.uuid4()
    sa.name = name
    sa.organization_id = org_id or uuid.uuid4()
    sa.is_active = is_active
    sa.last_used_at = None
    return sa


def _mock_db_with_result(return_value):
    """Create a mock database_service whose get_session yields a session
    that returns ``return_value`` from ``session.execute().scalar_one_or_none()``."""
    mock_db = MagicMock()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = return_value
    mock_session.execute.return_value = mock_result

    @asynccontextmanager
    async def _fake_get_session():
        yield mock_session

    mock_db.get_session = _fake_get_session
    return mock_db


# ---------------------------------------------------------------------------
# get_delegated_user tests
# ---------------------------------------------------------------------------

class TestGetDelegatedUser:
    """Tests for get_delegated_user dependency."""

    @pytest.mark.asyncio
    async def test_valid_delegation(self):
        """ServiceAccount key + valid X-On-Behalf-Of → returns resolved User."""
        from app.dependencies import get_delegated_user

        sa = _make_service_account()
        user = _make_user(email="alice@company.com")

        with patch("app.dependencies.get_current_principal_from_api_key", new_callable=AsyncMock) as mock_principal:
            mock_principal.return_value = sa

            with patch("app.dependencies.database_service", _mock_db_with_result(user)):
                result = await get_delegated_user(
                    x_api_key="cur_test1234abcdefghij",
                    x_on_behalf_of="alice@company.com",
                )

                assert result == user
                assert result.email == "alice@company.com"

    @pytest.mark.asyncio
    async def test_user_key_rejected(self):
        """User API key (not ServiceAccount) → 403."""
        from app.dependencies import get_delegated_user

        user = _make_user()

        with patch("app.dependencies.get_current_principal_from_api_key", new_callable=AsyncMock) as mock_principal:
            mock_principal.return_value = user  # User, not ServiceAccount

            with pytest.raises(HTTPException) as exc_info:
                await get_delegated_user(
                    x_api_key="cur_test1234abcdefghij",
                    x_on_behalf_of="alice@company.com",
                )

            assert exc_info.value.status_code == 403
            assert "ServiceAccount" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_on_behalf_of(self):
        """ServiceAccount key but no X-On-Behalf-Of → 400."""
        from app.dependencies import get_delegated_user

        sa = _make_service_account()

        with patch("app.dependencies.get_current_principal_from_api_key", new_callable=AsyncMock) as mock_principal:
            mock_principal.return_value = sa

            # No DB call needed — fails before querying
            with pytest.raises(HTTPException) as exc_info:
                await get_delegated_user(
                    x_api_key="cur_test1234abcdefghij",
                    x_on_behalf_of=None,
                )

            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_email(self):
        """ServiceAccount key + unknown email → 404."""
        from app.dependencies import get_delegated_user

        sa = _make_service_account()

        with patch("app.dependencies.get_current_principal_from_api_key", new_callable=AsyncMock) as mock_principal:
            mock_principal.return_value = sa

            with patch("app.dependencies.database_service", _mock_db_with_result(None)):
                with pytest.raises(HTTPException) as exc_info:
                    await get_delegated_user(
                        x_api_key="cur_test1234abcdefghij",
                        x_on_behalf_of="nobody@company.com",
                    )

                assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_inactive_user(self):
        """ServiceAccount key + inactive user email → 401."""
        from app.dependencies import get_delegated_user

        sa = _make_service_account()
        user = _make_user(email="inactive@company.com", is_active=False)

        with patch("app.dependencies.get_current_principal_from_api_key", new_callable=AsyncMock) as mock_principal:
            mock_principal.return_value = sa

            with patch("app.dependencies.database_service", _mock_db_with_result(user)):
                with pytest.raises(HTTPException) as exc_info:
                    await get_delegated_user(
                        x_api_key="cur_test1234abcdefghij",
                        x_on_behalf_of="inactive@company.com",
                    )

                assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user_or_delegated tests
# ---------------------------------------------------------------------------

class TestGetCurrentUserOrDelegated:
    """Tests for get_current_user_or_delegated dependency."""

    @pytest.mark.asyncio
    async def test_jwt_auth_works(self):
        """JWT Bearer token → standard user auth (unchanged)."""
        from app.dependencies import get_current_user_or_delegated

        user = _make_user()
        mock_credentials = MagicMock()
        mock_credentials.credentials = "test-jwt-token"

        with patch("app.dependencies.settings") as mock_settings:
            mock_settings.enable_auth = True
            with patch("app.dependencies.get_current_user_from_jwt", new_callable=AsyncMock) as mock_jwt:
                mock_jwt.return_value = user

                result = await get_current_user_or_delegated(
                    credentials=mock_credentials,
                    x_api_key=None,
                    x_on_behalf_of=None,
                )

                assert result == user
                mock_jwt.assert_called_once_with(mock_credentials)

    @pytest.mark.asyncio
    async def test_user_api_key_auth_works(self):
        """X-API-Key (user key, no X-On-Behalf-Of) → standard user API key auth."""
        from app.dependencies import get_current_user_or_delegated

        user = _make_user()

        with patch("app.dependencies.settings") as mock_settings:
            mock_settings.enable_auth = True
            with patch("app.dependencies.get_current_user_from_api_key", new_callable=AsyncMock) as mock_api_key:
                mock_api_key.return_value = user

                result = await get_current_user_or_delegated(
                    credentials=None,
                    x_api_key="cur_test1234abcdefghij",
                    x_on_behalf_of=None,
                )

                assert result == user
                mock_api_key.assert_called_once()

    @pytest.mark.asyncio
    async def test_delegated_auth_works(self):
        """X-API-Key + X-On-Behalf-Of → delegated auth (resolves end-user)."""
        from app.dependencies import get_current_user_or_delegated

        user = _make_user(email="alice@company.com")

        with patch("app.dependencies.settings") as mock_settings:
            mock_settings.enable_auth = True
            with patch("app.dependencies.get_delegated_user", new_callable=AsyncMock) as mock_delegated:
                mock_delegated.return_value = user

                result = await get_current_user_or_delegated(
                    credentials=None,
                    x_api_key="cur_test1234abcdefghij",
                    x_on_behalf_of="alice@company.com",
                )

                assert result == user
                assert result.email == "alice@company.com"
                mock_delegated.assert_called_once_with(
                    "cur_test1234abcdefghij", "alice@company.com"
                )

    @pytest.mark.asyncio
    async def test_no_credentials_raises_401(self):
        """No auth credentials at all → 401."""
        from app.dependencies import get_current_user_or_delegated

        with patch("app.dependencies.settings") as mock_settings:
            mock_settings.enable_auth = True

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_or_delegated(
                    credentials=None,
                    x_api_key=None,
                    x_on_behalf_of=None,
                )

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_disabled_returns_default_user(self):
        """ENABLE_AUTH=false → returns default admin user."""
        from app.dependencies import get_current_user_or_delegated

        admin_user = _make_user(role="admin")

        with patch("app.dependencies.settings") as mock_settings:
            mock_settings.enable_auth = False
            with patch("app.dependencies.database_service", _mock_db_with_result(admin_user)):
                result = await get_current_user_or_delegated(
                    credentials=None,
                    x_api_key=None,
                    x_on_behalf_of=None,
                )

                assert result == admin_user
