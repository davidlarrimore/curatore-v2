# backend/app/api/v1/routers/connections.py
"""
Connection management endpoints for Curatore v2 API (v1).

Provides endpoints for managing runtime-configurable connections to external services
(SharePoint, LLM, Extraction) with health testing and validation.

Endpoints:
    GET /connections/types - List available connection types
    GET /connections - List organization connections
    POST /connections - Create new connection
    GET /connections/{connection_id} - Get connection details
    PUT /connections/{connection_id} - Update connection
    DELETE /connections/{connection_id} - Delete connection
    POST /connections/{connection_id}/test - Test connection health
    POST /connections/{connection_id}/set-default - Set as default connection

Security:
    - All endpoints require authentication
    - Only org_admin can create/update/delete connections
    - Connections are organization-scoped
    - Secrets are redacted in responses
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update

from app.api.v1.admin.schemas import (
    ConnectionCreateRequest,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionTestResponse,
    ConnectionTypeInfo,
    ConnectionTypesResponse,
    ConnectionUpdateRequest,
)
from app.core.auth.connection_service import connection_service
from app.core.database.models import Connection, User
from app.core.shared.database_service import database_service
from app.dependencies import get_current_user, require_org_admin

# Initialize router
router = APIRouter(prefix="/connections", tags=["Connections"])

# Initialize logger
logger = logging.getLogger("curatore.api.connections")


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================


def _redact_secrets(config: dict) -> dict:
    """
    Redact sensitive fields in connection configuration.

    Args:
        config: Configuration dictionary

    Returns:
        dict: Configuration with secrets redacted
    """
    redacted = config.copy()
    secret_fields = ["api_key", "client_secret", "password", "token", "secret"]

    for field in secret_fields:
        if field in redacted:
            redacted[field] = "***REDACTED***"

    return redacted


# =========================================================================
# CONNECTION TYPE ENDPOINTS
# =========================================================================


@router.get(
    "/types",
    response_model=ConnectionTypesResponse,
    summary="List connection types",
    description="List all available connection types with their configuration schemas."
)
async def list_connection_types(
    current_user: User = Depends(get_current_user),
) -> ConnectionTypesResponse:
    """
    List available connection types.

    Returns metadata for all registered connection types including their
    configuration schemas for frontend form generation.

    Args:
        current_user: Current authenticated user

    Returns:
        ConnectionTypesResponse: List of connection types with schemas

    Example:
        GET /api/v1/connections/types
        Authorization: Bearer <token>

        Response:
        {
            "types": [
                {
                    "type": "llm",
                    "display_name": "LLM API",
                    "description": "Connect to OpenAI-compatible LLM APIs",
                    "schema": {...}
                }
            ]
        }
    """
    logger.info(f"Connection types requested by {current_user.email}")

    types_list = connection_service.registry.list_types()

    return ConnectionTypesResponse(
        types=[
            ConnectionTypeInfo(**type_info)
            for type_info in types_list
        ]
    )


# =========================================================================
# CONNECTION CRUD ENDPOINTS
# =========================================================================


@router.get(
    "",
    response_model=ConnectionListResponse,
    summary="List connections",
    description="List all connections for the current user's organization."
)
async def list_connections(
    connection_type: Optional[str] = Query(None, description="Filter by connection type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    is_default: Optional[bool] = Query(None, description="Filter by default status"),
    skip: int = Query(0, ge=0, description="Number of connections to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max connections to return"),
    current_user: User = Depends(get_current_user),
) -> ConnectionListResponse:
    """
    List organization connections.

    Returns a paginated list of connections for the authenticated user's
    organization. Supports filtering by type, active status, and default status.

    Args:
        connection_type: Filter by connection type (optional)
        is_active: Filter by active status (optional)
        is_default: Filter by default status (optional)
        skip: Number of connections to skip
        limit: Maximum connections to return
        current_user: Current authenticated user

    Returns:
        ConnectionListResponse: List of connections with total count

    Example:
        GET /api/v1/connections?connection_type=llm&is_active=true
        Authorization: Bearer <token>
    """
    logger.info(f"Connections list requested by {current_user.email}")

    async with database_service.get_session() as session:
        # Build query
        query = select(Connection).where(
            Connection.organization_id == current_user.organization_id
        )

        # Apply filters
        if connection_type:
            query = query.where(Connection.connection_type == connection_type)

        if is_active is not None:
            query = query.where(Connection.is_active == is_active)

        if is_default is not None:
            query = query.where(Connection.is_default == is_default)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination and execute
        query = query.order_by(Connection.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(query)
        connections = result.scalars().all()

        logger.info(f"Returning {len(connections)} connections (total: {total})")

        return ConnectionListResponse(
            connections=[
                ConnectionResponse(
                    id=str(conn.id),
                    organization_id=str(conn.organization_id),
                    name=conn.name,
                    description=conn.description,
                    connection_type=conn.connection_type,
                    config=_redact_secrets(conn.config),
                    is_active=conn.is_active,
                    is_default=conn.is_default,
                    is_managed=conn.is_managed,
                    managed_by=conn.managed_by,
                    last_tested_at=conn.last_tested_at,
                    test_status=conn.test_status,
                    test_result=conn.test_result,
                    scope=conn.scope,
                    created_at=conn.created_at,
                    updated_at=conn.updated_at,
                )
                for conn in connections
            ],
            total=total,
        )


@router.post(
    "",
    response_model=ConnectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create connection",
    description="Create a new connection. Requires org_admin role."
)
async def create_connection(
    request: ConnectionCreateRequest,
    current_user: User = Depends(require_org_admin),
) -> ConnectionResponse:
    """
    Create new connection.

    Creates a new connection with validation and optional health testing.
    Only organization admins can create connections.

    Args:
        request: Connection creation details
        current_user: Current user (must be org_admin)

    Returns:
        ConnectionResponse: Created connection with test results

    Raises:
        HTTPException: 400 if connection type not found or config invalid
        HTTPException: 403 if user is not org_admin

    Example:
        POST /api/v1/connections
        Authorization: Bearer <token>
        Content-Type: application/json

        {
            "name": "Production LLM",
            "connection_type": "llm",
            "config": {
                "api_key": "sk-...",
                "model": "gpt-4",
                "base_url": "https://api.openai.com/v1"
            },
            "is_default": true,
            "test_on_save": true
        }
    """
    logger.info(
        f"Connection creation requested by {current_user.email} "
        f"(type: {request.connection_type}, name: {request.name})"
    )

    # Validate connection type exists
    conn_type = connection_service.registry.get(request.connection_type)
    if not conn_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown connection type: {request.connection_type}"
        )

    # Validate configuration
    try:
        validated_config = conn_type.validate_config(request.config)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    async with database_service.get_session() as session:
        # If setting as default, unset other defaults of same type
        if request.is_default:
            await session.execute(
                update(Connection)
                .where(Connection.organization_id == current_user.organization_id)
                .where(Connection.connection_type == request.connection_type)
                .values(is_default=False)
            )

        # Create connection
        connection = Connection(
            id=uuid4(),
            organization_id=current_user.organization_id,
            name=request.name,
            description=request.description,
            connection_type=request.connection_type,
            config=validated_config,
            is_active=True,
            is_default=request.is_default,
            scope=request.scope,
            created_by=current_user.id,
        )

        session.add(connection)
        await session.commit()
        await session.refresh(connection)

        logger.info(f"Connection created: {connection.name} (id: {connection.id})")

        # Test connection if requested
        test_result = None
        if request.test_on_save:
            test_result = await connection_service.test_connection(session, connection.id)
            logger.info(f"Connection test: {test_result.status}")

        return ConnectionResponse(
            id=str(connection.id),
            organization_id=str(connection.organization_id),
            name=connection.name,
            description=connection.description,
            connection_type=connection.connection_type,
            config=_redact_secrets(connection.config),
            is_active=connection.is_active,
            is_default=connection.is_default,
            is_managed=connection.is_managed,
            managed_by=connection.managed_by,
            last_tested_at=connection.last_tested_at,
            test_status=connection.test_status,
            test_result=test_result.model_dump() if test_result else None,
            scope=connection.scope,
            created_at=connection.created_at,
            updated_at=connection.updated_at,
        )


@router.get(
    "/{connection_id}",
    response_model=ConnectionResponse,
    summary="Get connection",
    description="Get connection details by ID."
)
async def get_connection(
    connection_id: str,
    current_user: User = Depends(get_current_user),
) -> ConnectionResponse:
    """
    Get connection details.

    Returns detailed information about a specific connection.
    Secrets in configuration are redacted.

    Args:
        connection_id: Connection UUID
        current_user: Current authenticated user

    Returns:
        ConnectionResponse: Connection details

    Raises:
        HTTPException: 404 if connection not found or not in same organization

    Example:
        GET /api/v1/connections/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <token>
    """
    logger.info(f"Connection details requested for {connection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(Connection)
            .where(Connection.id == UUID(connection_id))
            .where(Connection.organization_id == current_user.organization_id)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found"
            )

        return ConnectionResponse(
            id=str(connection.id),
            organization_id=str(connection.organization_id),
            name=connection.name,
            description=connection.description,
            connection_type=connection.connection_type,
            config=_redact_secrets(connection.config),
            is_active=connection.is_active,
            is_default=connection.is_default,
            is_managed=connection.is_managed,
            managed_by=connection.managed_by,
            last_tested_at=connection.last_tested_at,
            test_status=connection.test_status,
            test_result=connection.test_result,
            scope=connection.scope,
            created_at=connection.created_at,
            updated_at=connection.updated_at,
        )


@router.put(
    "/{connection_id}",
    response_model=ConnectionResponse,
    summary="Update connection",
    description="Update connection details. Requires org_admin role."
)
async def update_connection(
    connection_id: str,
    request: ConnectionUpdateRequest,
    current_user: User = Depends(require_org_admin),
) -> ConnectionResponse:
    """
    Update connection details.

    Updates connection configuration, name, description, or status.
    Only organization admins can update connections.

    Args:
        connection_id: Connection UUID
        request: Update details
        current_user: Current user (must be org_admin)

    Returns:
        ConnectionResponse: Updated connection details

    Raises:
        HTTPException: 400 if config invalid
        HTTPException: 403 if user is not org_admin
        HTTPException: 404 if connection not found

    Example:
        PUT /api/v1/connections/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <token>
        Content-Type: application/json

        {
            "name": "Updated Connection Name",
            "is_default": true,
            "test_on_save": true
        }
    """
    logger.info(f"Connection update requested for {connection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(Connection)
            .where(Connection.id == UUID(connection_id))
            .where(Connection.organization_id == current_user.organization_id)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found"
            )

        # Check if connection is managed
        if connection.is_managed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This connection is managed by environment variables and cannot be edited. "
                       "Update your .env file and restart the application to modify this connection."
            )

        # Update fields
        if request.name is not None:
            connection.name = request.name

        if request.description is not None:
            connection.description = request.description

        if request.is_active is not None:
            connection.is_active = request.is_active

        if request.config is not None:
            # Validate new config
            conn_type = connection_service.registry.get(connection.connection_type)
            if conn_type:
                try:
                    validated_config = conn_type.validate_config(request.config)
                    connection.config = validated_config
                except ValueError as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=str(e)
                    )

        if request.is_default is not None and request.is_default:
            # Unset other defaults of same type
            await session.execute(
                update(Connection)
                .where(Connection.organization_id == current_user.organization_id)
                .where(Connection.connection_type == connection.connection_type)
                .where(Connection.id != connection.id)
                .values(is_default=False)
            )
            connection.is_default = True

        connection.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(connection)

        logger.info(f"Connection updated: {connection.name}")

        # Test connection if requested
        test_result = None
        if request.test_on_save:
            test_result = await connection_service.test_connection(session, connection.id)
            logger.info(f"Connection test: {test_result.status}")

        return ConnectionResponse(
            id=str(connection.id),
            organization_id=str(connection.organization_id),
            name=connection.name,
            description=connection.description,
            connection_type=connection.connection_type,
            config=_redact_secrets(connection.config),
            is_active=connection.is_active,
            is_default=connection.is_default,
            is_managed=connection.is_managed,
            managed_by=connection.managed_by,
            last_tested_at=connection.last_tested_at,
            test_status=connection.test_status,
            test_result=test_result.model_dump() if test_result else connection.test_result,
            scope=connection.scope,
            created_at=connection.created_at,
            updated_at=connection.updated_at,
        )


@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete connection",
    description="Delete a connection. Requires org_admin role."
)
async def delete_connection(
    connection_id: str,
    current_user: User = Depends(require_org_admin),
) -> None:
    """
    Delete connection.

    Performs a hard delete of the connection from the database.
    This action cannot be undone.

    Args:
        connection_id: Connection UUID
        current_user: Current user (must be org_admin)

    Raises:
        HTTPException: 403 if user is not org_admin
        HTTPException: 404 if connection not found

    Example:
        DELETE /api/v1/connections/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <token>

    Warning:
        This permanently deletes the connection. Consider deactivating instead
        (set is_active=False) to preserve historical data.
    """
    logger.info(f"Connection deletion requested for {connection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(Connection)
            .where(Connection.id == UUID(connection_id))
            .where(Connection.organization_id == current_user.organization_id)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found"
            )

        # Check if connection is managed
        if connection.is_managed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This connection is managed by environment variables and cannot be deleted. "
                       "Remove the environment variables and restart the application to delete this connection."
            )

        await session.delete(connection)
        await session.commit()

        logger.info(f"Connection deleted: {connection.name} (id: {connection_id})")


# =========================================================================
# CONNECTION TESTING ENDPOINTS
# =========================================================================


@router.post(
    "/{connection_id}/test",
    response_model=ConnectionTestResponse,
    summary="Test connection",
    description="Test connection health and connectivity."
)
async def test_connection_endpoint(
    connection_id: str,
    current_user: User = Depends(get_current_user),
) -> ConnectionTestResponse:
    """
    Test connection health.

    Performs a health check on the connection to verify it's properly
    configured and can communicate with the external service.

    Args:
        connection_id: Connection UUID
        current_user: Current authenticated user

    Returns:
        ConnectionTestResponse: Test results with status and details

    Raises:
        HTTPException: 404 if connection not found

    Example:
        POST /api/v1/connections/123e4567-e89b-12d3-a456-426614174000/test
        Authorization: Bearer <token>

        Response:
        {
            "connection_id": "123e4567-e89b-12d3-a456-426614174000",
            "success": true,
            "status": "healthy",
            "message": "Successfully connected to gpt-4",
            "details": {"model": "gpt-4"},
            "tested_at": "2026-01-13T01:00:00"
        }
    """
    logger.info(f"Connection test requested for {connection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        # Verify connection exists and belongs to user's org
        result = await session.execute(
            select(Connection)
            .where(Connection.id == UUID(connection_id))
            .where(Connection.organization_id == current_user.organization_id)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found"
            )

        # Test connection
        test_result = await connection_service.test_connection(session, UUID(connection_id))

        logger.info(f"Connection test completed: {test_result.status}")

        return ConnectionTestResponse(
            connection_id=connection_id,
            success=test_result.success,
            status=test_result.status,
            message=test_result.message,
            details=test_result.details,
            error=test_result.error,
            tested_at=datetime.utcnow(),
        )


@router.post(
    "/test-credentials",
    summary="Test LLM credentials and fetch models",
    description="Test LLM credentials and fetch available models without creating a connection."
)
async def test_llm_credentials(
    request: dict,
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Test LLM credentials and fetch available models.

    This endpoint allows testing credentials before creating a connection.
    For LLM connections, it will fetch the list of available models from the provider.

    Args:
        request: Dictionary with api_key, base_url, and optional provider info
        current_user: Current authenticated user

    Returns:
        dict: Success status, available models, and any errors

    Example:
        POST /api/v1/connections/test-credentials
        Authorization: Bearer <token>
        Content-Type: application/json

        {
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-..."
        }

        Response:
        {
            "success": true,
            "models": ["gpt-4", "gpt-3.5-turbo", ...],
            "message": "Successfully connected"
        }
    """
    import httpx

    base_url = request.get("base_url", "").rstrip("/")
    api_key = request.get("api_key", "")
    provider = request.get("provider", "openai")

    if not base_url or not api_key:
        return {
            "success": False,
            "error": "base_url and api_key are required",
            "models": []
        }

    try:
        # Try to fetch models from the /models endpoint
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {"Authorization": f"Bearer {api_key}"}

            # Handle different provider endpoints
            if provider == "bedrock":
                # Bedrock uses different auth mechanism
                return {
                    "success": False,
                    "error": "Bedrock model fetching requires AWS SDK - please enter model manually",
                    "models": [],
                    "requires_manual_model": True
                }

            # Standard OpenAI-compatible endpoint
            models_url = f"{base_url}/models"
            response = await client.get(models_url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                models = []

                # Parse response based on provider format
                if "data" in data and isinstance(data["data"], list):
                    # OpenAI format
                    models = [model.get("id") for model in data["data"] if model.get("id")]
                elif "models" in data and isinstance(data["models"], list):
                    # Alternative format
                    models = data["models"]

                return {
                    "success": True,
                    "models": sorted(models) if models else [],
                    "message": f"Successfully connected to {provider}"
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to fetch models: HTTP {response.status_code}",
                    "models": []
                }

    except httpx.TimeoutException:
        return {
            "success": False,
            "error": "Connection timeout - check your base URL",
            "models": []
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Connection failed: {str(e)}",
            "models": []
        }


@router.post(
    "/{connection_id}/set-default",
    response_model=ConnectionResponse,
    summary="Set default connection",
    description="Set connection as default for its type. Requires org_admin role."
)
async def set_default_connection(
    connection_id: str,
    current_user: User = Depends(require_org_admin),
) -> ConnectionResponse:
    """
    Set connection as default.

    Sets the connection as the default for its connection type.
    Unsets any other defaults of the same type.

    Args:
        connection_id: Connection UUID
        current_user: Current user (must be org_admin)

    Returns:
        ConnectionResponse: Updated connection details

    Raises:
        HTTPException: 403 if user is not org_admin
        HTTPException: 404 if connection not found

    Example:
        POST /api/v1/connections/123e4567-e89b-12d3-a456-426614174000/set-default
        Authorization: Bearer <token>
    """
    logger.info(f"Set default connection requested for {connection_id} by {current_user.email}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(Connection)
            .where(Connection.id == UUID(connection_id))
            .where(Connection.organization_id == current_user.organization_id)
        )
        connection = result.scalar_one_or_none()

        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Connection not found"
            )

        # Unset other defaults of same type
        await session.execute(
            update(Connection)
            .where(Connection.organization_id == current_user.organization_id)
            .where(Connection.connection_type == connection.connection_type)
            .where(Connection.id != connection.id)
            .values(is_default=False)
        )

        # Set this connection as default
        connection.is_default = True
        connection.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(connection)

        logger.info(f"Connection set as default: {connection.name}")

        return ConnectionResponse(
            id=str(connection.id),
            organization_id=str(connection.organization_id),
            name=connection.name,
            description=connection.description,
            connection_type=connection.connection_type,
            config=_redact_secrets(connection.config),
            is_active=connection.is_active,
            is_default=connection.is_default,
            is_managed=connection.is_managed,
            managed_by=connection.managed_by,
            last_tested_at=connection.last_tested_at,
            test_status=connection.test_status,
            test_result=connection.test_result,
            scope=connection.scope,
            created_at=connection.created_at,
            updated_at=connection.updated_at,
        )
