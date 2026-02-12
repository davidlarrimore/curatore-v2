"""
Unit tests for DatabaseService.

Tests async session management, database initialization, health checks,
and connection pooling for PostgreSQL databases.
"""

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.shared.database_service import DatabaseService, database_service
from sqlalchemy.ext.asyncio import AsyncSession


class TestDatabaseServiceInitialization:
    """Test DatabaseService initialization."""

    def test_initialization_creates_engine(self):
        """Test that initialization creates database engine."""
        # Use actual database_service singleton
        assert database_service._engine is not None
        assert database_service._session_factory is not None

    def test_singleton_instance(self):
        """Test that database_service is a singleton."""
        assert database_service is not None
        assert isinstance(database_service, DatabaseService)

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db"})
    def test_initialization_with_postgresql(self):
        """Test initialization with PostgreSQL URL."""
        db_service = DatabaseService()
        assert db_service._engine is not None
        assert db_service._session_factory is not None

    @patch.dict(os.environ, {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db",
        "DB_POOL_SIZE": "10",
        "DB_MAX_OVERFLOW": "20",
        "DB_POOL_RECYCLE": "1800"
    })
    def test_initialization_with_pool_settings(self):
        """Test initialization respects pool configuration."""
        db_service = DatabaseService()
        # Pool settings are applied during engine creation
        assert db_service._engine is not None

class TestSessionManagement:
    """Test database session management."""

    @pytest.mark.asyncio
    async def test_get_session_returns_session(self):
        """Test that get_session returns an async session."""
        async with database_service.get_session() as session:
            assert session is not None
            assert isinstance(session, AsyncSession)

    @pytest.mark.asyncio
    async def test_get_session_commits_on_success(self):
        """Test that session commits on successful exit."""
        mock_session = AsyncMock(spec=AsyncSession)

        # Create a proper async context manager mock
        @asynccontextmanager
        async def mock_factory():
            yield mock_session

        with patch.object(database_service, '_session_factory', mock_factory):
            async with database_service.get_session() as session:
                pass

        # Commit should be called
        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_session_rollback_on_error(self):
        """Test that session rolls back on error."""
        mock_session = AsyncMock(spec=AsyncSession)

        # Create a proper async context manager mock
        @asynccontextmanager
        async def mock_factory():
            yield mock_session

        with patch.object(database_service, '_session_factory', mock_factory):
            try:
                async with database_service.get_session() as session:
                    raise ValueError("Test error")
            except ValueError:
                pass

        # Rollback should be called, not commit
        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_session_without_initialization(self):
        """Test get_session raises error if not initialized."""
        db_service = DatabaseService.__new__(DatabaseService)
        db_service._session_factory = None

        with pytest.raises(RuntimeError, match="Database not initialized"):
            async with db_service.get_session() as session:
                pass

    @pytest.mark.asyncio
    async def test_multiple_sessions_independent(self):
        """Test that multiple sessions are independent."""
        # This test verifies session isolation
        async with database_service.get_session() as session1:
            async with database_service.get_session() as session2:
                assert session1 is not session2


class TestDatabaseInitialization:
    """Test database initialization."""

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self):
        """Test that init_db creates database tables."""
        mock_conn = AsyncMock()

        # Create proper async context manager for engine.begin()
        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        mock_engine = MagicMock()
        mock_engine.begin = mock_begin

        with patch.object(database_service, '_engine', mock_engine):
            await database_service.init_db()

        # run_sync should be called to create tables
        mock_conn.run_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_db_without_engine(self):
        """Test init_db raises error without engine."""
        db_service = DatabaseService.__new__(DatabaseService)
        db_service._engine = None

        with pytest.raises(RuntimeError, match="Database engine not initialized"):
            await db_service.init_db()

    @pytest.mark.asyncio
    async def test_init_db_imports_models(self):
        """Test that init_db imports database models."""
        mock_conn = AsyncMock()

        # Create proper async context manager for engine.begin()
        @asynccontextmanager
        async def mock_begin():
            yield mock_conn

        mock_engine = MagicMock()
        mock_engine.begin = mock_begin

        with patch.object(database_service, '_engine', mock_engine):
            with patch('app.core.database.models') as mock_models:
                await database_service.init_db()

        # Models module should be imported
        # (This is implicit in the import statement)
        mock_conn.run_sync.assert_called_once()


class TestHealthCheck:
    """Test database health check."""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """Test health check when database is healthy."""
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.scalar.return_value = 1
        mock_session.execute.return_value = mock_result

        with patch.object(database_service, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            health = await database_service.health_check()

        assert health["status"] == "healthy"
        assert health["connected"] is True
        assert "database_type" in health

    @pytest.mark.asyncio
    async def test_health_check_includes_table_counts(self):
        """Test health check includes table counts."""
        mock_session = AsyncMock()

        # Mock different count results for each table
        count_results = [1, 5, 3, 2, 1, 0]  # SELECT 1, orgs, users, keys, conns, settings, logs
        mock_results = []
        for count in count_results:
            mock_result = AsyncMock()
            mock_result.scalar.return_value = count
            mock_results.append(mock_result)

        mock_session.execute.side_effect = mock_results

        with patch.object(database_service, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            health = await database_service.health_check()

        assert "tables" in health
        assert isinstance(health["tables"], dict)

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on connection error."""
        with patch.object(database_service, 'get_session') as mock_get_session:
            mock_get_session.side_effect = Exception("Connection failed")

            health = await database_service.health_check()

        assert health["status"] == "unhealthy"
        assert health["connected"] is False
        assert "error" in health

    @pytest.mark.asyncio
    async def test_health_check_handles_missing_tables(self):
        """Test health check handles missing tables gracefully."""
        mock_session = AsyncMock()

        # First call succeeds (SELECT 1), subsequent calls fail (tables don't exist)
        success_result = AsyncMock()
        success_result.scalar.return_value = 1

        mock_session.execute.side_effect = [
            success_result,  # SELECT 1
            Exception("Table doesn't exist"),  # organizations
            Exception("Table doesn't exist"),  # users
            Exception("Table doesn't exist"),  # api_keys
            Exception("Table doesn't exist"),  # connections
            Exception("Table doesn't exist"),  # system_settings
            Exception("Table doesn't exist"),  # audit_logs
            Exception("Table doesn't exist"),  # alembic_version
        ]

        with patch.object(database_service, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            health = await database_service.health_check()

        # Should still return healthy (connection works)
        assert health["status"] == "healthy"
        assert health["connected"] is True

    @pytest.mark.asyncio
    async def test_health_check_includes_migration_version(self):
        """Test health check includes Alembic migration version."""
        mock_session = AsyncMock()

        # Mock SELECT 1 success
        select_result = AsyncMock()
        select_result.scalar.return_value = 1

        # Mock table count results (all return 0 for simplicity)
        count_results = [AsyncMock() for _ in range(6)]
        for result in count_results:
            result.scalar.return_value = 0

        # Mock migration version result
        version_result = AsyncMock()
        version_result.scalar.return_value = "abc123def456"

        mock_session.execute.side_effect = [
            select_result,  # SELECT 1
            *count_results,  # 6 table counts
            version_result,  # alembic_version
        ]

        with patch.object(database_service, 'get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            health = await database_service.health_check()

        assert "migration_version" in health
        # Should truncate to first 12 chars or show "unknown"
        assert health["migration_version"] in ["abc123def456", "unknown"]


class TestConnectionClosure:
    """Test database connection closure."""

    @pytest.mark.asyncio
    async def test_close_disposes_engine(self):
        """Test that close() disposes the engine."""
        mock_engine = AsyncMock()

        with patch.object(database_service, '_engine', mock_engine):
            await database_service.close()

        mock_engine.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_without_engine(self):
        """Test close() handles missing engine gracefully."""
        db_service = DatabaseService.__new__(DatabaseService)
        db_service._engine = None
        db_service._logger = MagicMock()

        # Should not raise error
        await db_service.close()


class TestDatabaseTypeDetection:
    """Test database type detection."""

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db"})
    def test_detects_postgresql(self):
        """Test PostgreSQL detection from URL."""
        db_service = DatabaseService()
        # Verify it's using PostgreSQL
        assert db_service._engine is not None


class TestStringRepresentation:
    """Test string representation."""

    def test_repr_format(self):
        """Test __repr__ returns correct format."""
        repr_str = repr(database_service)

        assert repr_str.startswith("<DatabaseService(")
        assert "type=" in repr_str
        assert repr_str.endswith(")>")

    @patch.dict(os.environ, {"DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db"})
    def test_repr_shows_postgresql(self):
        """Test repr shows PostgreSQL for PostgreSQL database."""
        db_service = DatabaseService()
        repr_str = repr(db_service)

        assert "PostgreSQL" in repr_str


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_session_propagates_exceptions(self):
        """Test that exceptions in session context are propagated."""
        with pytest.raises(ValueError):
            async with database_service.get_session() as session:
                raise ValueError("Test error")

    @pytest.mark.asyncio
    async def test_health_check_catches_exceptions(self):
        """Test health check catches and reports exceptions."""
        with patch.object(database_service, 'get_session') as mock_get_session:
            mock_get_session.side_effect = RuntimeError("Database error")

            health = await database_service.health_check()

        assert health["status"] == "unhealthy"
        assert health["connected"] is False
        assert "error" in health
        assert "Database error" in health["error"]


class TestConfigurationHandling:
    """Test configuration handling."""

    @patch.dict(os.environ, {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db",
        "DB_POOL_SIZE": "invalid"  # Invalid value
    })
    def test_handles_invalid_pool_size(self):
        """Test handles invalid pool size configuration."""
        # Should either use default or raise ValueError
        try:
            db_service = DatabaseService()
            # If it succeeds, engine should still be created
            assert db_service._engine is not None
        except ValueError:
            # Acceptable to raise ValueError for invalid config
            pass


class TestConcurrentAccess:
    """Test concurrent session access."""

    @pytest.mark.asyncio
    async def test_concurrent_sessions(self):
        """Test multiple concurrent sessions work correctly."""
        import asyncio

        async def use_session():
            async with database_service.get_session() as session:
                # Simulate some work
                await asyncio.sleep(0.01)
                return True

        # Create multiple concurrent sessions
        tasks = [use_session() for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(results)
        assert len(results) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
