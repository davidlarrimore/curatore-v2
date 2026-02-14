# backend/app/api/v1/routers/users.py
"""
User management endpoints for Curatore v2 API (v1).

Provides endpoints for organization admins to manage users within their organization.
Includes user listing, inviting, updating roles, and deactivation.

Endpoints:
    GET /organizations/me/users - List users in organization
    POST /organizations/me/users - Invite new user
    GET /organizations/me/users/{user_id} - Get user details
    PUT /organizations/me/users/{user_id} - Update user (role, name)
    DELETE /organizations/me/users/{user_id} - Deactivate user
    POST /organizations/me/users/{user_id}/reactivate - Reactivate user

Security:
    - All endpoints require authentication
    - Only org_admin can manage users
    - Users can only manage users in their own organization
    - Cannot deactivate yourself
"""

import logging
import secrets
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.v1.admin.schemas import (
    UserInviteRequest,
    UserInviteResponse,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.core.auth.auth_service import auth_service
from app.core.database.models import Organization, PasswordResetToken, User
from app.core.shared.database_service import database_service
from app.dependencies import get_current_org_id, require_admin

# Initialize router
router = APIRouter(prefix="/organizations/me/users", tags=["User Management"])

# Initialize logger
logger = logging.getLogger("curatore.api.users")


# =========================================================================
# USER MANAGEMENT ENDPOINTS
# =========================================================================


@router.get(
    "",
    response_model=UserListResponse,
    summary="List organization users",
    description="List all users in the current user's organization. Requires org_admin role.",
)
async def list_organization_users(
    is_active: bool = Query(None, description="Filter by active status (optional)"),
    role: str = Query(None, description="Filter by role (optional)"),
    skip: int = Query(0, ge=0, description="Number of users to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max users to return"),
    current_user: User = Depends(require_admin),
    org_id: UUID = Depends(get_current_org_id),
) -> UserListResponse:
    """
    List users in organization.

    Returns a paginated list of users in the same organization as the
    authenticated user. Supports filtering by active status and role.

    Args:
        is_active: Filter by active status (optional)
        role: Filter by role (optional)
        skip: Number of users to skip (for pagination)
        limit: Maximum users to return
        current_user: Current user (must be org_admin)

    Returns:
        UserListResponse: List of users with total count

    Example:
        GET /api/v1/organizations/me/users?is_active=true&role=member
        Authorization: Bearer <access_token>

        Response:
        {
            "users": [...],
            "total": 10
        }
    """
    logger.info(f"User list requested by {current_user.email} (org: {org_id})")

    async with database_service.get_session() as session:
        # Build query
        query = select(User).where(User.organization_id == org_id)

        # Apply filters
        if is_active is not None:
            query = query.where(User.is_active == is_active)

        if role:
            query = query.where(User.role == role)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        # Apply pagination and execute
        query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(query)
        users = result.scalars().all()

        logger.info(f"Returning {len(users)} users (total: {total})")

        return UserListResponse(
            users=[
                UserResponse(
                    id=str(user.id),
                    email=user.email,
                    username=user.username,
                    full_name=user.full_name,
                    role=user.role,
                    is_active=user.is_active,
                    is_verified=user.is_verified,
                    created_at=user.created_at,
                    last_login_at=user.last_login_at,
                )
                for user in users
            ],
            total=total,
        )


@router.post(
    "",
    response_model=UserInviteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite new user",
    description="Invite a new user to the organization. Requires org_admin role.",
)
async def invite_user(
    request: UserInviteRequest,
    current_user: User = Depends(require_admin),
    org_id: UUID = Depends(get_current_org_id),
) -> UserInviteResponse:
    """
    Invite new user to organization.

    Creates a new user account in the same organization as the admin.
    A temporary password is generated and should be sent to the user
    (email functionality not yet implemented).

    Args:
        request: User invitation details
        current_user: Current user (must be org_admin)

    Returns:
        UserResponse: Created user details

    Raises:
        HTTPException: 400 if email or username already exists
        HTTPException: 400 if invalid role specified

    Example:
        POST /api/v1/organizations/me/users
        Authorization: Bearer <access_token>
        Content-Type: application/json

        {
            "email": "newuser@example.com",
            "username": "newuser",
            "full_name": "New User",
            "role": "member"
        }

    Note:
        In production, this should send an email with a password reset link
        instead of generating a temporary password.
    """
    # Block user assignment to system org
    from app.config import SYSTEM_ORG_SLUG
    async with database_service.get_session() as check_session:
        from app.core.database.models import Organization as OrgModel
        org_result = await check_session.execute(
            select(OrgModel.slug).where(OrgModel.id == org_id)
        )
        if org_result.scalar_one_or_none() == SYSTEM_ORG_SLUG:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add users to the system organization",
            )

    logger.info(f"User invite requested by {current_user.email} for {request.email}")

    # Validate role - admin role requires current user to be admin
    valid_roles = ["member"]
    if current_user.role == "admin":
        valid_roles.append("admin")

    if request.role not in valid_roles:
        if request.role == "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only system admins can create admin users",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}",
        )

    async with database_service.get_session() as session:
        # Check if email already exists
        result = await session.execute(select(User).where(User.email == request.email))
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Check if username already exists
        result = await session.execute(select(User).where(User.username == request.username))
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )

        # Generate temporary password (20 chars, secure random)
        temp_password = secrets.token_urlsafe(15)
        password_hash = await auth_service.hash_password(temp_password)

        # Admin users have no organization (system-wide access)
        # Other users belong to the current org context
        user_org_id = None if request.role == "admin" else org_id

        # Create user
        new_user = User(
            id=uuid4(),
            organization_id=user_org_id,
            email=request.email,
            username=request.username,
            password_hash=password_hash,
            full_name=request.full_name,
            role=request.role,
            is_active=True,
            is_verified=False,  # Should verify email
        )

        session.add(new_user)

        if request.send_email:
            # Generate a password reset token the user can use to set their password
            invitation_token = secrets.token_urlsafe(32)
            reset_token = PasswordResetToken(
                user_id=new_user.id,
                token=invitation_token,
                expires_at=datetime.utcnow() + timedelta(hours=72),
            )
            session.add(reset_token)

        await session.commit()
        await session.refresh(new_user)

        user_response = UserResponse(
            id=str(new_user.id),
            email=new_user.email,
            username=new_user.username,
            full_name=new_user.full_name,
            role=new_user.role,
            is_active=new_user.is_active,
            is_verified=new_user.is_verified,
            created_at=new_user.created_at,
            last_login_at=new_user.last_login_at,
        )

        if request.send_email:
            # Get organization name for the email
            org_result = await session.execute(
                select(Organization).where(Organization.id == org_id)
            )
            org = org_result.scalar_one_or_none()
            org_name = org.display_name or org.name if org else "Curatore"

            # Queue invitation email via Celery
            from app.core.tasks import send_invitation_email_task

            try:
                send_invitation_email_task.delay(
                    user_email=new_user.email,
                    user_name=new_user.full_name or new_user.username,
                    invitation_token=invitation_token,
                    invited_by=current_user.full_name or current_user.username,
                    organization_name=org_name,
                )
                logger.info(f"Invitation email queued for {new_user.email}")
            except Exception as e:
                logger.error(f"Failed to queue invitation email for {new_user.email}: {e}")

            logger.info(f"User created with email invitation: {new_user.email} (id: {new_user.id})")
            return UserInviteResponse(
                message="User invited successfully. An invitation email has been sent.",
                user=user_response,
            )
        else:
            logger.info(f"User created with temp password: {new_user.email} (id: {new_user.id})")
            return UserInviteResponse(
                message="User created successfully.",
                user=user_response,
                temporary_password=temp_password,
            )


@router.get(
    "/all",
    response_model=UserListResponse,
    summary="List all users (system admin)",
    description="List all users across all organizations. Requires system admin role.",
)
async def list_all_users(
    is_active: bool = Query(None, description="Filter by active status (optional)"),
    role: str = Query(None, description="Filter by role (optional)"),
    organization_id: str = Query(None, description="Filter by organization ID (optional)"),
    skip: int = Query(0, ge=0, description="Number of users to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max users to return"),
    current_user: User = Depends(require_admin),
) -> UserListResponse:
    """List all users across all organizations. System admin only."""
    logger.info(f"All users list requested by {current_user.email}")

    async with database_service.get_session() as session:
        query = select(User, Organization.display_name, Organization.name).outerjoin(
            Organization, User.organization_id == Organization.id
        )

        if is_active is not None:
            query = query.where(User.is_active == is_active)
        if role:
            query = query.where(User.role == role)
        if organization_id:
            query = query.where(User.organization_id == UUID(organization_id))

        count_query = select(func.count()).select_from(
            select(User).where(
                *([User.is_active == is_active] if is_active is not None else []),
                *([User.role == role] if role else []),
                *([User.organization_id == UUID(organization_id)] if organization_id else []),
            ).subquery()
        )
        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
        result = await session.execute(query)
        rows = result.all()

        logger.info(f"Returning {len(rows)} users (total: {total})")

        return UserListResponse(
            users=[
                UserResponse(
                    id=str(user.id),
                    email=user.email,
                    username=user.username,
                    full_name=user.full_name,
                    role=user.role,
                    is_active=user.is_active,
                    is_verified=user.is_verified,
                    created_at=user.created_at,
                    last_login_at=user.last_login_at,
                    organization_id=str(user.organization_id) if user.organization_id else None,
                    organization_name=display_name or org_name if (display_name or org_name) else None,
                )
                for user, display_name, org_name in rows
            ],
            total=total,
        )


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get user details",
    description="Get details of a specific user in the organization. Requires org_admin role.",
)
async def get_user(
    user_id: str,
    current_user: User = Depends(require_admin),
    org_id: UUID = Depends(get_current_org_id),
) -> UserResponse:
    """
    Get user details.

    Returns detailed information about a specific user in the organization.

    Args:
        user_id: User UUID
        current_user: Current user (must be org_admin)

    Returns:
        UserResponse: User details

    Raises:
        HTTPException: 404 if user not found or not in same organization

    Example:
        GET /api/v1/organizations/me/users/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <access_token>
    """
    logger.info(f"User details requested for {user_id} by {current_user.email}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(User)
            .where(User.id == UUID(user_id))
            .where(User.organization_id == org_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in this organization",
            )

        return UserResponse(
            id=str(user.id),
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update user",
    description="Update user details (name, role). Requires org_admin role.",
)
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    current_user: User = Depends(require_admin),
    org_id: UUID = Depends(get_current_org_id),
) -> UserResponse:
    """
    Update user details.

    Allows updating user's full name and role. Organization admins can
    modify any user in their organization except they cannot change their
    own role (prevents accidental lockout).

    Args:
        user_id: User UUID
        request: Update details
        current_user: Current user (must be org_admin)

    Returns:
        UserResponse: Updated user details

    Raises:
        HTTPException: 400 if trying to change own role
        HTTPException: 400 if invalid role specified
        HTTPException: 404 if user not found or not in same organization

    Example:
        PUT /api/v1/organizations/me/users/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <access_token>
        Content-Type: application/json

        {
            "full_name": "John Smith",
            "role": "member"
        }
    """
    logger.info(f"User update requested for {user_id} by {current_user.email}")

    # Validate role if provided - admin role requires current user to be admin
    if request.role:
        valid_roles = ["member"]
        if current_user.role == "admin":
            valid_roles.append("admin")

        if request.role not in valid_roles:
            if request.role == "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only system admins can assign the admin role",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}",
            )

    async with database_service.get_session() as session:
        result = await session.execute(
            select(User)
            .where(User.id == UUID(user_id))
            .where(User.organization_id == org_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in this organization",
            )

        # Prevent changing own role (avoid lockout)
        if request.role and user.id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change your own role. Ask another admin to do it.",
            )

        # Update fields
        if request.full_name is not None:
            user.full_name = request.full_name
            logger.info(f"Updated full_name to: {request.full_name}")

        if request.role is not None:
            old_role = user.role
            user.role = request.role
            # Admin users have no organization
            if request.role == "admin":
                user.organization_id = None
            elif old_role == "admin" and request.role != "admin":
                # Demoting from admin — must assign an org
                if not org_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Must specify organization context (X-Organization-Id header) when demoting from admin role",
                    )
                user.organization_id = org_id
            logger.info(f"Updated role from {old_role} to {request.role}")

        user.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(user)

        logger.info(f"User updated successfully: {user.email}")

        return UserResponse(
            id=str(user.id),
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate user",
    description="Deactivate a user (soft delete). Requires org_admin role.",
)
async def deactivate_user(
    user_id: str,
    current_user: User = Depends(require_admin),
    org_id: UUID = Depends(get_current_org_id),
) -> None:
    """
    Deactivate user.

    Performs a soft delete by setting is_active=False. The user account
    remains in the database but cannot log in. Can be reactivated later.

    Args:
        user_id: User UUID
        current_user: Current user (must be org_admin)

    Raises:
        HTTPException: 400 if trying to deactivate yourself
        HTTPException: 404 if user not found or not in same organization

    Example:
        DELETE /api/v1/organizations/me/users/123e4567-e89b-12d3-a456-426614174000
        Authorization: Bearer <access_token>

    Note:
        To permanently delete a user, you would need a separate hard delete
        endpoint (not implemented for data retention/audit purposes).
    """
    logger.info(f"User deactivation requested for {user_id} by {current_user.email}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(User)
            .where(User.id == UUID(user_id))
            .where(User.organization_id == org_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in this organization",
            )

        # Prevent deactivating yourself
        if user.id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate yourself. Ask another admin to do it.",
            )

        user.is_active = False
        user.updated_at = datetime.utcnow()

        await session.commit()

        logger.info(f"User deactivated: {user.email}")


@router.post(
    "/{user_id}/reactivate",
    response_model=UserResponse,
    summary="Reactivate user",
    description="Reactivate a previously deactivated user. Requires org_admin role.",
)
async def reactivate_user(
    user_id: str,
    current_user: User = Depends(require_admin),
    org_id: UUID = Depends(get_current_org_id),
) -> UserResponse:
    """
    Reactivate user.

    Sets is_active=True on a previously deactivated user, allowing them
    to log in again.

    Args:
        user_id: User UUID
        current_user: Current user (must be org_admin)

    Returns:
        UserResponse: Reactivated user details

    Raises:
        HTTPException: 400 if user is already active
        HTTPException: 404 if user not found or not in same organization

    Example:
        POST /api/v1/organizations/me/users/123e4567-e89b-12d3-a456-426614174000/reactivate
        Authorization: Bearer <access_token>
    """
    logger.info(f"User reactivation requested for {user_id} by {current_user.email}")

    async with database_service.get_session() as session:
        result = await session.execute(
            select(User)
            .where(User.id == UUID(user_id))
            .where(User.organization_id == org_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in this organization",
            )

        if user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already active",
            )

        user.is_active = True
        user.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(user)

        logger.info(f"User reactivated: {user.email}")

        return UserResponse(
            id=str(user.id),
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            is_verified=user.is_verified,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )
