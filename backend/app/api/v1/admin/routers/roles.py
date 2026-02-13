"""
Roles management endpoints.

Provides API endpoints for listing available roles.
Roles are predefined and stored in the roles table.
"""

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.core.database.models import Role
from app.core.shared.database_service import database_service
from app.dependencies import get_current_user

from ..schemas import RoleResponse, RoleListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get(
    "",
    response_model=RoleListResponse,
    status_code=status.HTTP_200_OK,
    summary="List available roles",
    description="Get all available roles that can be assigned to users.",
)
async def list_roles(
    current_user=Depends(get_current_user),
):
    """
    List all available roles.

    Returns all roles with their permissions and metadata.
    The 'admin' role (system role) is only shown to admin users.

    Returns:
        RoleListResponse with list of roles and total count.
    """
    async with database_service.get_session() as session:
        # Build query - non-admins don't see the admin role
        query = select(Role).order_by(Role.id)

        if current_user.role != "admin":
            query = query.where(Role.is_system_role == False)

        result = await session.execute(query)
        roles = result.scalars().all()

        return RoleListResponse(
            roles=[
                RoleResponse(
                    id=role.id,
                    name=role.name,
                    display_name=role.display_name,
                    description=role.description,
                    is_system_role=role.is_system_role,
                    can_manage_users=role.can_manage_users,
                    can_manage_org=role.can_manage_org,
                    can_manage_system=role.can_manage_system,
                )
                for role in roles
            ],
            total=len(roles),
        )


@router.get(
    "/{role_name}",
    response_model=RoleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get role details",
    description="Get details for a specific role by name.",
)
async def get_role(
    role_name: str,
    current_user=Depends(get_current_user),
):
    """
    Get details for a specific role.

    Args:
        role_name: The role name (admin, org_admin, member, viewer)

    Returns:
        RoleResponse with role details.
    """
    async with database_service.get_session() as session:
        result = await session.execute(
            select(Role).where(Role.name == role_name)
        )
        role = result.scalar_one_or_none()

        if not role:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role '{role_name}' not found",
            )

        # Non-admins can't see system roles
        if role.is_system_role and current_user.role != "admin":
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role '{role_name}' not found",
            )

        return RoleResponse(
            id=role.id,
            name=role.name,
            display_name=role.display_name,
            description=role.description,
            is_system_role=role.is_system_role,
            can_manage_users=role.can_manage_users,
            can_manage_org=role.can_manage_org,
            can_manage_system=role.can_manage_system,
        )
