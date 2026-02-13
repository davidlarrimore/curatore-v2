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
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
# SERVICE SYNC FROM CONFIG
# =========================================================================


def _safe_db_url(url: str) -> str:
    """Return a database URL with the password masked for display."""
    if not url:
        return url
    # postgresql+asyncpg://user:password@host:5432/db  →  …user:***@host:5432/db
    try:
        at_idx = url.index("@")
        scheme_end = url.index("://") + 3
        user_pass = url[scheme_end:at_idx]
        if ":" in user_pass:
            user, _ = user_pass.split(":", 1)
            return f"{url[:scheme_end]}{user}:***{url[at_idx:]}"
    except (ValueError, IndexError):
        pass
    return url


async def sync_services_from_config(session: AsyncSession) -> Dict[str, int]:
    """Sync infrastructure services from config.yml into the services table.

    Reads each config section via ``config_loader`` and upserts a ``Service``
    row keyed by ``name``.  Sensitive fields (api_key, secret_key, …) are
    **never** stored in the ``config`` JSONB column.

    Returns ``{"created": N, "updated": N, "unchanged": N}``.
    """
    import os

    from app.core.shared.config_loader import config_loader

    counts: Dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}

    # Build list of service definitions from config
    defs: list[Dict[str, Any]] = []

    # --- LLM ---
    llm = config_loader.get_llm_config()
    if llm:
        task_type_names = list(llm.task_types.keys()) if llm.task_types else []
        defs.append({
            "name": "llm",
            "service_type": "llm",
            "description": f"LLM provider ({llm.provider})",
            "is_active": True,
            "config": {
                "provider": llm.provider,
                "base_url": llm.base_url,
                "default_model": llm.default_model,
                "timeout": llm.timeout,
                "task_types": task_type_names,
            },
        })

    # --- Extraction engines ---
    ext = config_loader.get_extraction_config()
    if ext:
        for engine in ext.engines:
            defs.append({
                "name": engine.name,
                "service_type": "extraction",
                "description": engine.display_name,
                "is_active": engine.enabled,
                "config": {
                    "engine_type": engine.engine_type,
                    "service_url": engine.service_url,
                    "timeout": engine.timeout,
                },
            })

    # --- Playwright ---
    pw = config_loader.get_playwright_config()
    if pw:
        defs.append({
            "name": "playwright",
            "service_type": "browser",
            "description": "Playwright browser rendering service",
            "is_active": pw.enabled,
            "config": {
                "service_url": pw.service_url,
                "timeout": pw.timeout,
                "browser_pool_size": pw.browser_pool_size,
            },
        })

    # --- Object storage (MinIO / S3) ---
    minio = config_loader.get_minio_config()
    if minio:
        defs.append({
            "name": "object-storage",
            "service_type": "storage",
            "description": "S3/MinIO object storage",
            "is_active": minio.enabled,
            "config": {
                "endpoint": minio.endpoint,
                "secure": minio.secure,
                "bucket_uploads": minio.bucket_uploads,
                "bucket_processed": minio.bucket_processed,
                "bucket_temp": minio.bucket_temp,
            },
        })

    # --- Queue ---
    queue = config_loader.get_queue_config()
    if queue:
        queue_config: Dict[str, Any] = {
            "default_queue": queue.default_queue,
            "worker_concurrency": queue.worker_concurrency,
            "task_timeout": queue.task_timeout,
        }

        # Include per-queue-type settings from the initialized registry
        try:
            from app.core.ops.queue_registry import queue_registry
            queue_defs = queue_registry.get_all()
            if queue_defs:
                queues_detail: Dict[str, Any] = {}
                for qt, qdef in queue_defs.items():
                    queues_detail[qt] = {
                        "max_concurrent": qdef.max_concurrent,
                        "timeout_seconds": qdef.timeout_seconds,
                        "enabled": qdef.enabled,
                    }
                queue_config["queues"] = queues_detail
        except Exception:
            pass  # Registry may not be initialized yet

        defs.append({
            "name": "queue",
            "service_type": "queue",
            "description": "Celery task queue (Redis)",
            "is_active": True,
            "config": queue_config,
        })

    # --- Core Database + Search (always present) ---
    db_cfg = config_loader.get_database_config()
    search = config_loader.get_search_config()
    primary_url = (
        (db_cfg.database_url if db_cfg and db_cfg.database_url else None)
        or os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://curatore:curatore_dev_password@postgres:5432/curatore",
        )
    )
    db_search_config: Dict[str, Any] = {
        "database_url": _safe_db_url(primary_url),
    }
    if db_cfg:
        db_search_config["pool_size"] = db_cfg.pool_size
        db_search_config["max_overflow"] = db_cfg.max_overflow
        db_search_config["pool_recycle"] = db_cfg.pool_recycle
    else:
        db_search_config["pool_size"] = int(os.getenv("DB_POOL_SIZE", "20"))
        db_search_config["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "40"))
        db_search_config["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE", "3600"))

    # Add search config
    search_enabled = True
    if search:
        db_search_config["search_mode"] = search.default_mode
        db_search_config["semantic_weight"] = search.semantic_weight
        db_search_config["chunk_size"] = search.chunk_size
        db_search_config["chunk_overlap"] = search.chunk_overlap
        search_enabled = search.enabled
        if search.database_url:
            db_search_config["search_database_url"] = _safe_db_url(search.database_url)
            db_search_config["search_database"] = "dedicated pgvector instance"
        else:
            db_search_config["search_database"] = "shared (primary)"

    defs.append({
        "name": "database",
        "service_type": "database",
        "description": "PostgreSQL + pgvector (database & search)",
        "is_active": search_enabled,
        "config": db_search_config,
    })

    # --- Microsoft Graph ---
    mg = config_loader.get_microsoft_graph_config()
    if mg:
        defs.append({
            "name": "microsoft-graph",
            "service_type": "microsoft_graph",
            "description": "Microsoft Graph API",
            "is_active": mg.enabled,
            "config": {
                "tenant_id": mg.tenant_id,
                "graph_base_url": mg.graph_base_url,
                "sharepoint": True,
                "email": mg.enable_email,
                "email_sender": mg.email_sender_user_id,
            },
        })

    # Upsert each definition
    for d in defs:
        result = await session.execute(
            select(Service).where(Service.name == d["name"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            changed = False
            if existing.config != d["config"]:
                existing.config = d["config"]
                changed = True
            if existing.description != d["description"]:
                existing.description = d["description"]
                changed = True
            if existing.service_type != d["service_type"]:
                existing.service_type = d["service_type"]
                changed = True
            if existing.is_active != d["is_active"]:
                existing.is_active = d["is_active"]
                changed = True
            if changed:
                existing.updated_at = datetime.utcnow()
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
        else:
            session.add(Service(
                name=d["name"],
                service_type=d["service_type"],
                description=d["description"],
                config=d["config"],
                is_active=d["is_active"],
                test_status="not_tested",
            ))
            counts["created"] += 1

    return counts


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
