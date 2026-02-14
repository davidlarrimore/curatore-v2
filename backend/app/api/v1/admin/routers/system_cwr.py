"""System CWR endpoint — exposes system org info for frontend."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.config import SYSTEM_ORG_SLUG
from app.core.database.models import Organization, User
from app.core.shared.database_service import database_service
from app.dependencies import require_admin

logger = logging.getLogger("curatore.api.admin.system_cwr")

router = APIRouter(prefix="/system-cwr", tags=["Admin"])


class SystemOrgResponse(BaseModel):
    id: str
    slug: str
    name: str


@router.get(
    "/org",
    response_model=SystemOrgResponse,
    summary="Get system organization info",
    description="Returns the system organization ID for CWR operations. Admin only.",
)
async def get_system_org(
    user: User = Depends(require_admin),
) -> SystemOrgResponse:
    """Return the system org info so the frontend can target CWR endpoints."""
    async with database_service.get_session() as session:
        result = await session.execute(
            select(Organization).where(Organization.slug == SYSTEM_ORG_SLUG)
        )
        org = result.scalar_one_or_none()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System organization not found. Run startup or seed first.",
            )
        return SystemOrgResponse(
            id=str(org.id),
            slug=org.slug,
            name=org.name,
        )
