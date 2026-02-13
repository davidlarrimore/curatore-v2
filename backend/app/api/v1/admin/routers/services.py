# backend/app/api/v1/admin/routers/services.py
"""
System services management endpoints for Curatore v2 API (v1).

Provides endpoints for managing system-scoped infrastructure services
like LLM providers, extraction services, and browser rendering services.

These endpoints are admin-only and operate at the system level, not
organization level.

Endpoints:
    GET /services - List all system services
    POST /services - Create a new service
    GET /services/{service_id} - Get service details
    PUT /services/{service_id} - Update a service
    DELETE /services/{service_id} - Delete a service
    POST /services/{service_id}/test - Test service health

Security:
    - All endpoints require system admin role
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.v1.admin.schemas import (
    ServiceCreateRequest,
    ServiceListResponse,
    ServiceResponse,
    ServiceUpdateRequest,
)
from app.core.database.models import Service, User
from app.core.shared.database_service import database_service
from app.dependencies import require_admin

# Initialize router
router = APIRouter(prefix="/services", tags=["Services"])

# Initialize logger
logger = logging.getLogger("curatore.api.services")

# Sensitive fields to redact in responses
SENSITIVE_FIELDS = {"api_key", "client_secret", "password", "token", "secret"}


def _redact_secrets(config: dict) -> dict:
    """Redact sensitive fields in configuration."""
    if not config:
        return config
    result = {}
    for key, value in config.items():
        if any(sensitive in key.lower() for sensitive in SENSITIVE_FIELDS):
            result[key] = "***REDACTED***"
        elif isinstance(value, dict):
            result[key] = _redact_secrets(value)
        else:
            result[key] = value
    return result


# =========================================================================
# SERVICE CRUD ENDPOINTS
# =========================================================================


@router.get(
    "",
    response_model=ServiceListResponse,
    summary="List all system services",
    description="List all system-scoped infrastructure services. Admin only.",
)
async def list_services(
    service_type: Optional[str] = Query(None, description="Filter by service type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    user: User = Depends(require_admin),
) -> ServiceListResponse:
    """List all system services."""
    logger.info(f"Admin {user.email} listing services")

    async with database_service.get_session() as session:
        # Build query
        query = select(Service)

        if service_type:
            query = query.where(Service.service_type == service_type)
        if is_active is not None:
            query = query.where(Service.is_active == is_active)

        # Get total count
        count_query = select(func.count()).select_from(Service)
        if service_type:
            count_query = count_query.where(Service.service_type == service_type)
        if is_active is not None:
            count_query = count_query.where(Service.is_active == is_active)

        result = await session.execute(count_query)
        total = result.scalar() or 0

        # Apply pagination
        query = query.order_by(Service.name).offset(skip).limit(limit)
        result = await session.execute(query)
        services = result.scalars().all()

        return ServiceListResponse(
            services=[
                ServiceResponse(
                    id=str(s.id),
                    name=s.name,
                    service_type=s.service_type,
                    description=s.description,
                    config=_redact_secrets(s.config or {}),
                    is_active=s.is_active,
                    last_tested_at=s.last_tested_at,
                    test_status=s.test_status,
                    test_result=s.test_result,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                )
                for s in services
            ],
            total=total,
        )


@router.post(
    "",
    response_model=ServiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new system service",
    description="Create a new system-scoped infrastructure service. Admin only.",
)
async def create_service(
    request: ServiceCreateRequest,
    user: User = Depends(require_admin),
) -> ServiceResponse:
    """Create a new system service."""
    logger.info(f"Admin {user.email} creating service: {request.name}")

    async with database_service.get_session() as session:
        # Check for duplicate name
        result = await session.execute(
            select(Service).where(Service.name == request.name)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Service with name '{request.name}' already exists",
            )

        # Create service
        service = Service(
            name=request.name,
            service_type=request.service_type,
            description=request.description,
            config=request.config,
            is_active=request.is_active,
        )
        session.add(service)
        await session.commit()
        await session.refresh(service)

        logger.info(f"Created service: {service.name} (id: {service.id})")

        return ServiceResponse(
            id=str(service.id),
            name=service.name,
            service_type=service.service_type,
            description=service.description,
            config=_redact_secrets(service.config or {}),
            is_active=service.is_active,
            last_tested_at=service.last_tested_at,
            test_status=service.test_status,
            test_result=service.test_result,
            created_at=service.created_at,
            updated_at=service.updated_at,
        )


@router.get(
    "/{service_id}",
    response_model=ServiceResponse,
    summary="Get service details",
    description="Get details of a specific system service. Admin only.",
)
async def get_service(
    service_id: UUID,
    user: User = Depends(require_admin),
) -> ServiceResponse:
    """Get service details."""
    async with database_service.get_session() as session:
        result = await session.execute(
            select(Service).where(Service.id == service_id)
        )
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service not found",
            )

        return ServiceResponse(
            id=str(service.id),
            name=service.name,
            service_type=service.service_type,
            description=service.description,
            config=_redact_secrets(service.config or {}),
            is_active=service.is_active,
            last_tested_at=service.last_tested_at,
            test_status=service.test_status,
            test_result=service.test_result,
            created_at=service.created_at,
            updated_at=service.updated_at,
        )


@router.put(
    "/{service_id}",
    response_model=ServiceResponse,
    summary="Update a service",
    description="Update a system service configuration. Admin only.",
)
async def update_service(
    service_id: UUID,
    request: ServiceUpdateRequest,
    user: User = Depends(require_admin),
) -> ServiceResponse:
    """Update a system service."""
    logger.info(f"Admin {user.email} updating service {service_id}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(Service).where(Service.id == service_id)
        )
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service not found",
            )

        # Update fields
        if request.description is not None:
            service.description = request.description
        if request.config is not None:
            service.config = request.config
        if request.is_active is not None:
            service.is_active = request.is_active

        service.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(service)

        logger.info(f"Updated service: {service.name}")

        return ServiceResponse(
            id=str(service.id),
            name=service.name,
            service_type=service.service_type,
            description=service.description,
            config=_redact_secrets(service.config or {}),
            is_active=service.is_active,
            last_tested_at=service.last_tested_at,
            test_status=service.test_status,
            test_result=service.test_result,
            created_at=service.created_at,
            updated_at=service.updated_at,
        )


@router.delete(
    "/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a service",
    description="Delete a system service. Admin only.",
)
async def delete_service(
    service_id: UUID,
    user: User = Depends(require_admin),
) -> None:
    """Delete a system service."""
    logger.info(f"Admin {user.email} deleting service {service_id}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(Service).where(Service.id == service_id)
        )
        service = result.scalar_one_or_none()

        if not service:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service not found",
            )

        await session.delete(service)
        await session.commit()

        logger.info(f"Deleted service: {service.name}")
