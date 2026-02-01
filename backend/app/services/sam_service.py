"""
SAM.gov Service for Federal Opportunity Management.

Provides CRUD operations and management for SamSearch, SamSolicitation,
SamNotice, SamAttachment, and SamSolicitationSummary models. This is the
core service for Phase 7: Native SAM.gov Domain Integration.

Key Features:
- Create and manage SAM searches with configurable filters
- Track solicitations and their version history (notices)
- Manage attachments and link them to Assets
- Track LLM-generated summaries with experiment support
- Agency/sub-agency reference data management

Usage:
    from app.services.sam_service import sam_service

    # Create a search
    search = await sam_service.create_search(
        session=session,
        organization_id=org_id,
        name="IT Services Opportunities",
        search_config={
            "naics_codes": ["541512"],
            "active_only": True,
        },
    )

    # Get solicitations for an organization
    solicitations, total = await sam_service.list_solicitations(
        session=session,
        organization_id=org_id,
    )

    # Create a summary
    summary = await sam_service.create_summary(
        session=session,
        solicitation_id=solicitation.id,
        summary_type="executive",
        model="gpt-4o",
        summary="...",
    )
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database.models import (
    Asset,
    Run,
    SamAgency,
    SamAttachment,
    SamNotice,
    SamSearch,
    SamSolicitation,
    SamSolicitationSummary,
    SamSubAgency,
)

logger = logging.getLogger("curatore.sam_service")


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:255]


class SamService:
    """
    Service for managing SAM.gov searches and related operations.

    Handles CRUD operations for searches, solicitations, notices,
    attachments, and summaries with organization isolation.
    """

    # =========================================================================
    # SEARCH OPERATIONS
    # =========================================================================

    async def create_search(
        self,
        session: AsyncSession,
        organization_id: UUID,
        name: str,
        search_config: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        pull_frequency: str = "manual",
        created_by: Optional[UUID] = None,
    ) -> SamSearch:
        """
        Create a new SAM search.

        Args:
            session: Database session
            organization_id: Organization UUID
            name: Search name
            search_config: Filter configuration (NAICS codes, agencies, etc.)
            description: Optional description
            pull_frequency: How often to pull (manual, hourly, daily)
            created_by: User who created the search

        Returns:
            Created SamSearch instance
        """
        slug = slugify(name)

        # Ensure slug is unique within org
        existing = await session.execute(
            select(SamSearch).where(
                and_(
                    SamSearch.organization_id == organization_id,
                    SamSearch.slug == slug,
                )
            )
        )
        if existing.scalar_one_or_none():
            # Append timestamp to make unique
            slug = f"{slug}-{int(datetime.utcnow().timestamp())}"

        search = SamSearch(
            organization_id=organization_id,
            name=name,
            slug=slug,
            description=description,
            search_config=search_config or {},
            pull_frequency=pull_frequency,
            created_by=created_by,
        )

        session.add(search)
        await session.commit()
        await session.refresh(search)

        logger.info(f"Created SAM search {search.id}: {name}")

        return search

    async def get_search(
        self,
        session: AsyncSession,
        search_id: UUID,
    ) -> Optional[SamSearch]:
        """Get search by ID."""
        result = await session.execute(
            select(SamSearch).where(SamSearch.id == search_id)
        )
        return result.scalar_one_or_none()

    async def get_search_by_slug(
        self,
        session: AsyncSession,
        organization_id: UUID,
        slug: str,
    ) -> Optional[SamSearch]:
        """Get search by slug within organization."""
        result = await session.execute(
            select(SamSearch).where(
                and_(
                    SamSearch.organization_id == organization_id,
                    SamSearch.slug == slug,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_searches(
        self,
        session: AsyncSession,
        organization_id: UUID,
        status: Optional[str] = None,
        is_active: Optional[bool] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SamSearch], int]:
        """
        List searches for an organization.

        Args:
            include_archived: If False (default), excludes archived searches

        Returns:
            Tuple of (searches list, total count)
        """
        query = select(SamSearch).where(
            SamSearch.organization_id == organization_id
        )

        # Exclude archived by default
        if not include_archived and status != "archived":
            query = query.where(SamSearch.status != "archived")

        if status:
            query = query.where(SamSearch.status == status)
        if is_active is not None:
            query = query.where(SamSearch.is_active == is_active)

        # Get total count
        count_query = select(func.count(SamSearch.id)).where(
            SamSearch.organization_id == organization_id
        )
        # Exclude archived by default in count too
        if not include_archived and status != "archived":
            count_query = count_query.where(SamSearch.status != "archived")
        if status:
            count_query = count_query.where(SamSearch.status == status)
        if is_active is not None:
            count_query = count_query.where(SamSearch.is_active == is_active)

        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results
        query = query.order_by(SamSearch.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        searches = list(result.scalars().all())

        return searches, total

    async def update_search(
        self,
        session: AsyncSession,
        search_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        search_config: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        is_active: Optional[bool] = None,
        pull_frequency: Optional[str] = None,
    ) -> Optional[SamSearch]:
        """Update search properties."""
        search = await self.get_search(session, search_id)
        if not search:
            return None

        if name is not None:
            search.name = name
        if description is not None:
            search.description = description
        if search_config is not None:
            search.search_config = search_config
        if status is not None:
            search.status = status
        if is_active is not None:
            search.is_active = is_active
        if pull_frequency is not None:
            search.pull_frequency = pull_frequency

        await session.commit()
        await session.refresh(search)

        logger.info(f"Updated SAM search {search_id}")

        return search

    async def delete_search(
        self,
        session: AsyncSession,
        search_id: UUID,
    ) -> bool:
        """Delete a search (soft delete by setting status to archived)."""
        search = await self.get_search(session, search_id)
        if not search:
            return False

        search.status = "archived"
        search.is_active = False
        await session.commit()

        logger.info(f"Archived SAM search {search_id}")

        return True

    async def update_search_pull_status(
        self,
        session: AsyncSession,
        search_id: UUID,
        status: str,
        run_id: Optional[UUID] = None,
    ) -> Optional[SamSearch]:
        """Update search pull status after a pull operation."""
        search = await self.get_search(session, search_id)
        if not search:
            return None

        search.last_pull_at = datetime.utcnow()
        search.last_pull_status = status
        if run_id:
            search.last_pull_run_id = run_id

        await session.commit()
        await session.refresh(search)

        return search

    # =========================================================================
    # SOLICITATION OPERATIONS
    # =========================================================================

    async def create_solicitation(
        self,
        session: AsyncSession,
        organization_id: UUID,
        notice_id: str,
        title: str,
        notice_type: str,
        solicitation_number: Optional[str] = None,
        description: Optional[str] = None,
        naics_code: Optional[str] = None,
        psc_code: Optional[str] = None,
        set_aside_code: Optional[str] = None,
        posted_date: Optional[datetime] = None,
        response_deadline: Optional[datetime] = None,
        ui_link: Optional[str] = None,
        api_link: Optional[str] = None,
        contact_info: Optional[Dict[str, Any]] = None,
        place_of_performance: Optional[Dict[str, Any]] = None,
        sub_agency_id: Optional[UUID] = None,
        agency_name: Optional[str] = None,
        bureau_name: Optional[str] = None,
        office_name: Optional[str] = None,
        full_parent_path: Optional[str] = None,
    ) -> SamSolicitation:
        """
        Create a new solicitation.

        Args:
            session: Database session
            organization_id: Organization UUID
            notice_id: SAM.gov unique notice ID
            title: Opportunity title
            notice_type: Type code (o, p, k, r, s)
            solicitation_number: Contract number
            description: Full description
            naics_code: NAICS classification
            psc_code: Product/Service code
            set_aside_code: Set-aside type
            posted_date: Original post date
            response_deadline: Due date
            ui_link: SAM.gov UI link
            api_link: SAM.gov API link
            contact_info: Contact information (JSONB)
            place_of_performance: Location (JSONB)
            sub_agency_id: Issuing sub-agency
            agency_name: Top-level agency (e.g., "HOMELAND SECURITY, DEPARTMENT OF")
            bureau_name: Bureau/sub-agency (e.g., "US COAST GUARD")
            office_name: Office (e.g., "AVIATION LOGISTICS CENTER")
            full_parent_path: Original fullParentPathName from API

        Returns:
            Created SamSolicitation instance
        """
        solicitation = SamSolicitation(
            organization_id=organization_id,
            notice_id=notice_id,
            solicitation_number=solicitation_number,
            title=title,
            description=description,
            notice_type=notice_type,
            naics_code=naics_code,
            psc_code=psc_code,
            set_aside_code=set_aside_code,
            posted_date=posted_date,
            response_deadline=response_deadline,
            ui_link=ui_link,
            api_link=api_link,
            contact_info=contact_info,
            place_of_performance=place_of_performance,
            sub_agency_id=sub_agency_id,
            agency_name=agency_name,
            bureau_name=bureau_name,
            office_name=office_name,
            full_parent_path=full_parent_path,
        )

        session.add(solicitation)
        await session.commit()
        await session.refresh(solicitation)

        logger.info(f"Created solicitation {solicitation.id}: {notice_id}")

        return solicitation

    async def get_solicitation(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        include_notices: bool = False,
        include_attachments: bool = False,
        include_summaries: bool = False,
    ) -> Optional[SamSolicitation]:
        """Get solicitation by ID with optional eager loading."""
        query = select(SamSolicitation).where(SamSolicitation.id == solicitation_id)

        options = []
        if include_notices:
            options.append(selectinload(SamSolicitation.notices))
        if include_attachments:
            options.append(selectinload(SamSolicitation.attachments))
        if include_summaries:
            options.append(selectinload(SamSolicitation.summaries))

        if options:
            query = query.options(*options)

        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def get_solicitation_by_notice_id(
        self,
        session: AsyncSession,
        notice_id: str,
    ) -> Optional[SamSolicitation]:
        """Get solicitation by SAM.gov notice ID."""
        result = await session.execute(
            select(SamSolicitation).where(SamSolicitation.notice_id == notice_id)
        )
        return result.scalar_one_or_none()

    async def get_solicitation_by_number(
        self,
        session: AsyncSession,
        organization_id: UUID,
        solicitation_number: str,
    ) -> Optional[SamSolicitation]:
        """
        Get solicitation by solicitation number within an organization.

        This is the primary deduplication method - solicitation_number
        is the unique identifier for a solicitation in SAM.gov.
        Multiple notices (amendments) can belong to the same solicitation.
        """
        result = await session.execute(
            select(SamSolicitation).where(
                and_(
                    SamSolicitation.organization_id == organization_id,
                    SamSolicitation.solicitation_number == solicitation_number,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_solicitations(
        self,
        session: AsyncSession,
        organization_id: UUID,
        status: Optional[str] = None,
        notice_type: Optional[str] = None,
        naics_code: Optional[str] = None,
        keyword: Optional[str] = None,
        deadline_before: Optional[datetime] = None,
        deadline_after: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SamSolicitation], int]:
        """
        List solicitations with filters.

        Solicitations are organization-wide and not tied to any specific search.

        Returns:
            Tuple of (solicitations list, total count)
        """
        query = select(SamSolicitation).where(
            SamSolicitation.organization_id == organization_id
        )

        if status:
            query = query.where(SamSolicitation.status == status)
        if notice_type:
            query = query.where(SamSolicitation.notice_type == notice_type)
        if naics_code:
            query = query.where(SamSolicitation.naics_code == naics_code)
        if keyword:
            keyword_filter = f"%{keyword}%"
            query = query.where(
                or_(
                    SamSolicitation.title.ilike(keyword_filter),
                    SamSolicitation.description.ilike(keyword_filter),
                )
            )
        if deadline_before:
            query = query.where(SamSolicitation.response_deadline <= deadline_before)
        if deadline_after:
            query = query.where(SamSolicitation.response_deadline >= deadline_after)

        # Build count query with same filters
        count_query = select(func.count(SamSolicitation.id)).where(
            SamSolicitation.organization_id == organization_id
        )
        if status:
            count_query = count_query.where(SamSolicitation.status == status)
        if notice_type:
            count_query = count_query.where(SamSolicitation.notice_type == notice_type)
        if naics_code:
            count_query = count_query.where(SamSolicitation.naics_code == naics_code)
        if keyword:
            count_query = count_query.where(
                or_(
                    SamSolicitation.title.ilike(keyword_filter),
                    SamSolicitation.description.ilike(keyword_filter),
                )
            )
        if deadline_before:
            count_query = count_query.where(SamSolicitation.response_deadline <= deadline_before)
        if deadline_after:
            count_query = count_query.where(SamSolicitation.response_deadline >= deadline_after)

        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results
        query = query.order_by(SamSolicitation.response_deadline.asc().nullslast())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        solicitations = list(result.scalars().all())

        return solicitations, total

    async def update_solicitation(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        response_deadline: Optional[datetime] = None,
        archive_date: Optional[datetime] = None,
    ) -> Optional[SamSolicitation]:
        """Update solicitation properties."""
        solicitation = await self.get_solicitation(session, solicitation_id)
        if not solicitation:
            return None

        if title is not None:
            solicitation.title = title
        if description is not None:
            solicitation.description = description
        if status is not None:
            solicitation.status = status
        if response_deadline is not None:
            solicitation.response_deadline = response_deadline
        if archive_date is not None:
            solicitation.archive_date = archive_date

        await session.commit()
        await session.refresh(solicitation)

        return solicitation

    async def update_solicitation_counts(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
    ) -> Optional[SamSolicitation]:
        """Update denormalized counts for a solicitation."""
        solicitation = await self.get_solicitation(session, solicitation_id)
        if not solicitation:
            return None

        # Count notices
        notice_count = await session.execute(
            select(func.count(SamNotice.id)).where(
                SamNotice.solicitation_id == solicitation_id
            )
        )
        solicitation.notice_count = notice_count.scalar_one()

        # Count attachments
        attachment_count = await session.execute(
            select(func.count(SamAttachment.id)).where(
                SamAttachment.solicitation_id == solicitation_id
            )
        )
        solicitation.attachment_count = attachment_count.scalar_one()

        await session.commit()
        await session.refresh(solicitation)

        return solicitation

    # =========================================================================
    # NOTICE OPERATIONS
    # =========================================================================

    async def create_notice(
        self,
        session: AsyncSession,
        solicitation_id: Optional[UUID],
        sam_notice_id: str,
        notice_type: str,
        version_number: int = 1,
        title: Optional[str] = None,
        description: Optional[str] = None,
        posted_date: Optional[datetime] = None,
        response_deadline: Optional[datetime] = None,
        raw_json_bucket: Optional[str] = None,
        raw_json_key: Optional[str] = None,
        # For standalone notices (when solicitation_id is None)
        organization_id: Optional[UUID] = None,
        naics_code: Optional[str] = None,
        psc_code: Optional[str] = None,
        set_aside_code: Optional[str] = None,
        agency_name: Optional[str] = None,
        bureau_name: Optional[str] = None,
        office_name: Optional[str] = None,
        ui_link: Optional[str] = None,
    ) -> SamNotice:
        """
        Create a new notice.

        Can be either:
        - A version of a solicitation (solicitation_id provided)
        - A standalone notice like Special Notices (organization_id provided, no solicitation_id)

        Args:
            session: Database session
            solicitation_id: Parent solicitation UUID (None for standalone notices)
            sam_notice_id: SAM.gov notice ID
            notice_type: Type code (o, p, k, r, s, a)
            version_number: Version number (1=original, 2+=amendments)
            title: Title at this version
            description: Description at this version
            posted_date: When this version was posted
            response_deadline: Deadline at this version
            raw_json_bucket: MinIO bucket for raw JSON
            raw_json_key: MinIO key for raw JSON
            organization_id: Organization UUID (required for standalone notices)
            naics_code: NAICS code (for standalone notices)
            psc_code: PSC code (for standalone notices)
            set_aside_code: Set-aside code (for standalone notices)
            agency_name: Agency name (for standalone notices)
            bureau_name: Bureau name (for standalone notices)
            office_name: Office name (for standalone notices)
            ui_link: SAM.gov UI link

        Returns:
            Created SamNotice instance
        """
        notice = SamNotice(
            solicitation_id=solicitation_id,
            organization_id=organization_id,
            sam_notice_id=sam_notice_id,
            notice_type=notice_type,
            version_number=version_number,
            title=title,
            description=description,
            posted_date=posted_date,
            response_deadline=response_deadline,
            raw_json_bucket=raw_json_bucket,
            raw_json_key=raw_json_key,
            naics_code=naics_code,
            psc_code=psc_code,
            set_aside_code=set_aside_code,
            agency_name=agency_name,
            bureau_name=bureau_name,
            office_name=office_name,
            ui_link=ui_link,
            summary_status="pending" if solicitation_id is None else None,
        )

        session.add(notice)
        await session.commit()
        await session.refresh(notice)

        if solicitation_id:
            logger.info(f"Created notice {notice.id} (v{version_number}) for solicitation {solicitation_id}")
        else:
            logger.info(f"Created standalone notice {notice.id} ({notice_type}): {title}")

        return notice

    async def get_notice(
        self,
        session: AsyncSession,
        notice_id: UUID,
    ) -> Optional[SamNotice]:
        """Get notice by ID."""
        result = await session.execute(
            select(SamNotice)
            .options(selectinload(SamNotice.attachments))
            .where(SamNotice.id == notice_id)
        )
        return result.scalar_one_or_none()

    async def list_notices(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
    ) -> List[SamNotice]:
        """List all notices for a solicitation ordered by version."""
        result = await session.execute(
            select(SamNotice)
            .where(SamNotice.solicitation_id == solicitation_id)
            .order_by(SamNotice.version_number.asc())
        )
        return list(result.scalars().all())

    async def get_latest_notice(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
    ) -> Optional[SamNotice]:
        """Get the latest notice for a solicitation."""
        result = await session.execute(
            select(SamNotice)
            .where(SamNotice.solicitation_id == solicitation_id)
            .order_by(SamNotice.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_notice_by_sam_notice_id(
        self,
        session: AsyncSession,
        sam_notice_id: str,
        organization_id: Optional[UUID] = None,
    ) -> Optional[SamNotice]:
        """
        Get a notice by its SAM.gov notice ID.

        For standalone notices, also filter by organization_id to ensure
        proper multi-tenant isolation.

        Args:
            session: Database session
            sam_notice_id: SAM.gov notice ID
            organization_id: Optional organization filter (for standalone notices)

        Returns:
            SamNotice or None
        """
        query = select(SamNotice).where(SamNotice.sam_notice_id == sam_notice_id)

        if organization_id:
            # For standalone notices, filter by organization
            query = query.where(
                (SamNotice.organization_id == organization_id) |
                (SamNotice.solicitation_id.isnot(None))  # Allow solicitation-linked notices
            )

        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def update_notice_changes_summary(
        self,
        session: AsyncSession,
        notice_id: UUID,
        changes_summary: str,
    ) -> Optional[SamNotice]:
        """Update the changes summary for a notice."""
        notice = await self.get_notice(session, notice_id)
        if not notice:
            return None

        notice.changes_summary = changes_summary
        await session.commit()
        await session.refresh(notice)

        return notice

    async def update_notice(
        self,
        session: AsyncSession,
        notice_id: UUID,
        title: Optional[str] = None,
        description: Optional[str] = None,
        response_deadline: Optional[datetime] = None,
    ) -> Optional[SamNotice]:
        """
        Update a notice with new data.

        Args:
            session: Database session
            notice_id: Notice UUID
            title: New title (optional)
            description: New description (optional)
            response_deadline: New response deadline (optional)

        Returns:
            Updated notice or None if not found
        """
        notice = await self.get_notice(session, notice_id)
        if not notice:
            return None

        if title is not None:
            notice.title = title
        if description is not None:
            notice.description = description
        if response_deadline is not None:
            notice.response_deadline = response_deadline

        await session.commit()
        await session.refresh(notice)

        logger.info(f"Updated notice {notice_id}")
        return notice

    # =========================================================================
    # ATTACHMENT OPERATIONS
    # =========================================================================

    async def create_attachment(
        self,
        session: AsyncSession,
        solicitation_id: Optional[UUID],
        resource_id: str,
        filename: str,
        notice_id: Optional[UUID] = None,
        file_type: Optional[str] = None,
        file_size: Optional[int] = None,
        description: Optional[str] = None,
        download_url: Optional[str] = None,
    ) -> SamAttachment:
        """
        Create a new attachment record.

        Can be attached to either a solicitation or a standalone notice.

        Args:
            session: Database session
            solicitation_id: Parent solicitation UUID (None for standalone notice attachments)
            resource_id: SAM.gov resource identifier
            filename: Original filename
            notice_id: Notice that introduced this attachment
            file_type: File extension (pdf, docx, etc.)
            file_size: Size in bytes
            description: File description
            download_url: SAM.gov download URL

        Returns:
            Created SamAttachment instance
        """
        attachment = SamAttachment(
            solicitation_id=solicitation_id,
            notice_id=notice_id,
            resource_id=resource_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            description=description,
            download_url=download_url,
        )

        session.add(attachment)
        await session.commit()
        await session.refresh(attachment)

        logger.info(f"Created attachment {attachment.id}: {filename}")

        return attachment

    async def get_attachment(
        self,
        session: AsyncSession,
        attachment_id: UUID,
    ) -> Optional[SamAttachment]:
        """Get attachment by ID."""
        result = await session.execute(
            select(SamAttachment).where(SamAttachment.id == attachment_id)
        )
        return result.scalar_one_or_none()

    async def get_attachment_by_resource_id(
        self,
        session: AsyncSession,
        resource_id: str,
    ) -> Optional[SamAttachment]:
        """Get attachment by SAM.gov resource ID."""
        result = await session.execute(
            select(SamAttachment).where(SamAttachment.resource_id == resource_id)
        )
        return result.scalar_one_or_none()

    async def get_attachment_by_download_url(
        self,
        session: AsyncSession,
        download_url: str,
    ) -> Optional[SamAttachment]:
        """
        Get attachment by download URL.

        This is used for deduplication - if an attachment from the same URL
        has already been downloaded, we can link to the existing asset
        instead of downloading again.
        """
        result = await session.execute(
            select(SamAttachment).where(
                and_(
                    SamAttachment.download_url == download_url,
                    SamAttachment.download_status == "downloaded",
                    SamAttachment.asset_id.isnot(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_attachment_by_resource_or_url(
        self,
        session: AsyncSession,
        resource_id: Optional[str] = None,
        download_url: Optional[str] = None,
    ) -> Optional[SamAttachment]:
        """
        Get attachment by resource ID or download URL.

        Checks resource_id first (if provided), then falls back to download_url.
        Used for deduplication to avoid creating duplicate attachment records.
        """
        # Try resource_id first
        if resource_id:
            result = await session.execute(
                select(SamAttachment).where(SamAttachment.resource_id == resource_id)
            )
            attachment = result.scalar_one_or_none()
            if attachment:
                return attachment

        # Fall back to download_url
        if download_url:
            result = await session.execute(
                select(SamAttachment).where(SamAttachment.download_url == download_url)
            )
            return result.scalar_one_or_none()

        return None

    async def list_attachments(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        download_status: Optional[str] = None,
    ) -> List[SamAttachment]:
        """List attachments for a solicitation."""
        query = select(SamAttachment).where(
            SamAttachment.solicitation_id == solicitation_id
        )

        if download_status:
            query = query.where(SamAttachment.download_status == download_status)

        query = query.order_by(SamAttachment.created_at.asc())

        result = await session.execute(query)
        return list(result.scalars().all())

    async def list_notice_attachments(
        self,
        session: AsyncSession,
        notice_id: UUID,
        download_status: Optional[str] = None,
    ) -> List[SamAttachment]:
        """List attachments for a specific notice.

        Works for both solicitation-linked and standalone notices.
        """
        query = select(SamAttachment).where(SamAttachment.notice_id == notice_id)

        if download_status:
            query = query.where(SamAttachment.download_status == download_status)

        query = query.order_by(SamAttachment.created_at.asc())

        result = await session.execute(query)
        return list(result.scalars().all())

    async def update_attachment_download_status(
        self,
        session: AsyncSession,
        attachment_id: UUID,
        status: str,
        asset_id: Optional[UUID] = None,
        error: Optional[str] = None,
    ) -> Optional[SamAttachment]:
        """Update attachment download status."""
        attachment = await self.get_attachment(session, attachment_id)
        if not attachment:
            return None

        attachment.download_status = status
        if status == "downloaded":
            attachment.downloaded_at = datetime.utcnow()
        if asset_id:
            attachment.asset_id = asset_id
        if error:
            attachment.download_error = error

        await session.commit()
        await session.refresh(attachment)

        return attachment

    async def update_attachment(
        self,
        session: AsyncSession,
        attachment_id: UUID,
        filename: Optional[str] = None,
        file_type: Optional[str] = None,
        file_size: Optional[int] = None,
        description: Optional[str] = None,
    ) -> Optional[SamAttachment]:
        """
        Update attachment metadata.

        Used to update filename and other details after download when
        the real filename is discovered from Content-Disposition header.

        Args:
            session: Database session
            attachment_id: Attachment UUID
            filename: New filename (if discovered)
            file_type: File extension/type
            file_size: File size in bytes
            description: File description

        Returns:
            Updated attachment or None if not found
        """
        attachment = await self.get_attachment(session, attachment_id)
        if not attachment:
            return None

        if filename is not None:
            attachment.filename = filename
        if file_type is not None:
            attachment.file_type = file_type
        if file_size is not None:
            attachment.file_size = file_size
        if description is not None:
            attachment.description = description

        await session.commit()
        await session.refresh(attachment)

        return attachment

    # =========================================================================
    # SUMMARY OPERATIONS
    # =========================================================================

    async def create_summary(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        model: str,
        summary: str,
        summary_type: str = "full",
        prompt_template: Optional[str] = None,
        prompt_version: Optional[str] = None,
        key_requirements: Optional[List[Dict[str, Any]]] = None,
        compliance_checklist: Optional[List[Dict[str, Any]]] = None,
        confidence_score: Optional[float] = None,
        token_count: Optional[int] = None,
        asset_metadata_id: Optional[UUID] = None,
        is_canonical: bool = False,
    ) -> SamSolicitationSummary:
        """
        Create a new solicitation summary.

        Args:
            session: Database session
            solicitation_id: Parent solicitation UUID
            model: LLM model used
            summary: Generated summary text
            summary_type: Type of summary (full, executive, technical, compliance)
            prompt_template: Prompt used for generation
            prompt_version: Version of prompt template
            key_requirements: Structured key requirements
            compliance_checklist: Compliance items
            confidence_score: Quality/confidence score
            token_count: Tokens used for generation
            asset_metadata_id: Link to experiment system
            is_canonical: Whether this is the active summary

        Returns:
            Created SamSolicitationSummary instance
        """
        summary_obj = SamSolicitationSummary(
            solicitation_id=solicitation_id,
            model=model,
            summary=summary,
            summary_type=summary_type,
            prompt_template=prompt_template,
            prompt_version=prompt_version,
            key_requirements=key_requirements,
            compliance_checklist=compliance_checklist,
            confidence_score=confidence_score,
            token_count=token_count,
            asset_metadata_id=asset_metadata_id,
            is_canonical=is_canonical,
        )

        if is_canonical:
            summary_obj.promoted_at = datetime.utcnow()

        session.add(summary_obj)
        await session.commit()
        await session.refresh(summary_obj)

        logger.info(f"Created summary {summary_obj.id} for solicitation {solicitation_id}")

        return summary_obj

    async def get_summary(
        self,
        session: AsyncSession,
        summary_id: UUID,
    ) -> Optional[SamSolicitationSummary]:
        """Get summary by ID."""
        result = await session.execute(
            select(SamSolicitationSummary).where(SamSolicitationSummary.id == summary_id)
        )
        return result.scalar_one_or_none()

    async def list_summaries(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        summary_type: Optional[str] = None,
    ) -> List[SamSolicitationSummary]:
        """List summaries for a solicitation."""
        query = select(SamSolicitationSummary).where(
            SamSolicitationSummary.solicitation_id == solicitation_id
        )

        if summary_type:
            query = query.where(SamSolicitationSummary.summary_type == summary_type)

        query = query.order_by(SamSolicitationSummary.created_at.desc())

        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_canonical_summary(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        summary_type: str = "full",
    ) -> Optional[SamSolicitationSummary]:
        """Get the canonical summary for a solicitation and type."""
        result = await session.execute(
            select(SamSolicitationSummary).where(
                and_(
                    SamSolicitationSummary.solicitation_id == solicitation_id,
                    SamSolicitationSummary.summary_type == summary_type,
                    SamSolicitationSummary.is_canonical == True,
                )
            )
        )
        return result.scalar_one_or_none()

    async def promote_summary(
        self,
        session: AsyncSession,
        summary_id: UUID,
    ) -> Optional[SamSolicitationSummary]:
        """
        Promote a summary to canonical status.

        Demotes any existing canonical summary of the same type.
        """
        summary = await self.get_summary(session, summary_id)
        if not summary:
            return None

        # Demote existing canonical summary of same type
        await session.execute(
            update(SamSolicitationSummary)
            .where(
                and_(
                    SamSolicitationSummary.solicitation_id == summary.solicitation_id,
                    SamSolicitationSummary.summary_type == summary.summary_type,
                    SamSolicitationSummary.is_canonical == True,
                    SamSolicitationSummary.id != summary_id,
                )
            )
            .values(is_canonical=False)
        )

        # Promote this summary
        summary.is_canonical = True
        summary.promoted_at = datetime.utcnow()

        await session.commit()
        await session.refresh(summary)

        logger.info(f"Promoted summary {summary_id} to canonical")

        return summary

    async def delete_summary(
        self,
        session: AsyncSession,
        summary_id: UUID,
    ) -> bool:
        """Delete a summary (only non-canonical)."""
        summary = await self.get_summary(session, summary_id)
        if not summary:
            return False

        if summary.is_canonical:
            logger.warning(f"Cannot delete canonical summary {summary_id}")
            return False

        await session.delete(summary)
        await session.commit()

        logger.info(f"Deleted summary {summary_id}")

        return True

    # =========================================================================
    # AGENCY OPERATIONS
    # =========================================================================

    async def get_or_create_agency(
        self,
        session: AsyncSession,
        code: str,
        name: str,
        abbreviation: Optional[str] = None,
    ) -> SamAgency:
        """Get existing agency or create new one."""
        result = await session.execute(
            select(SamAgency).where(SamAgency.code == code)
        )
        agency = result.scalar_one_or_none()

        if agency:
            return agency

        agency = SamAgency(
            code=code,
            name=name,
            abbreviation=abbreviation,
        )
        session.add(agency)
        await session.commit()
        await session.refresh(agency)

        logger.info(f"Created agency {agency.id}: {code}")

        return agency

    async def get_or_create_sub_agency(
        self,
        session: AsyncSession,
        agency_id: UUID,
        code: str,
        name: str,
        abbreviation: Optional[str] = None,
    ) -> SamSubAgency:
        """Get existing sub-agency or create new one."""
        result = await session.execute(
            select(SamSubAgency).where(
                and_(
                    SamSubAgency.agency_id == agency_id,
                    SamSubAgency.code == code,
                )
            )
        )
        sub_agency = result.scalar_one_or_none()

        if sub_agency:
            return sub_agency

        sub_agency = SamSubAgency(
            agency_id=agency_id,
            code=code,
            name=name,
            abbreviation=abbreviation,
        )
        session.add(sub_agency)
        await session.commit()
        await session.refresh(sub_agency)

        logger.info(f"Created sub-agency {sub_agency.id}: {code}")

        return sub_agency

    async def list_agencies(
        self,
        session: AsyncSession,
        include_sub_agencies: bool = False,
    ) -> List[SamAgency]:
        """List all agencies."""
        query = select(SamAgency).where(SamAgency.is_active == True)

        if include_sub_agencies:
            query = query.options(selectinload(SamAgency.sub_agencies))

        query = query.order_by(SamAgency.name.asc())

        result = await session.execute(query)
        return list(result.scalars().all())

    # =========================================================================
    # STATISTICS
    # =========================================================================

    async def get_search_stats(
        self,
        session: AsyncSession,
        search_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get statistics for a search.

        Note: Since solicitations are decoupled from searches, this returns
        pull-related statistics only, not solicitation counts.
        """
        search = await self.get_search(session, search_id)
        if not search:
            return {}

        return {
            "pull_frequency": search.pull_frequency,
            "last_pull_at": search.last_pull_at.isoformat() if search.last_pull_at else None,
            "last_pull_status": search.last_pull_status,
            "is_active": search.is_active,
            "status": search.status,
        }

    # =========================================================================
    # DASHBOARD & ORG-WIDE QUERIES (Phase 7.6)
    # =========================================================================

    async def get_dashboard_stats(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """
        Get dashboard statistics for the organization.

        Returns aggregate counts for notices, solicitations, and recent activity.
        """
        from datetime import timedelta
        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)

        # Total notices
        total_notices = await session.execute(
            select(func.count(SamNotice.id))
            .join(SamSolicitation)
            .where(SamSolicitation.organization_id == organization_id)
        )

        # Total solicitations
        total_solicitations = await session.execute(
            select(func.count(SamSolicitation.id))
            .where(SamSolicitation.organization_id == organization_id)
        )

        # Recent notices (last 7 days)
        recent_notices = await session.execute(
            select(func.count(SamNotice.id))
            .join(SamSolicitation)
            .where(
                and_(
                    SamSolicitation.organization_id == organization_id,
                    SamNotice.created_at >= seven_days_ago,
                )
            )
        )

        # New solicitations (last 7 days - based on first notice)
        new_solicitations = await session.execute(
            select(func.count(SamSolicitation.id))
            .where(
                and_(
                    SamSolicitation.organization_id == organization_id,
                    SamSolicitation.created_at >= seven_days_ago,
                )
            )
        )

        # Updated solicitations (last 7 days - have notice after first)
        # Count solicitations where updated_at > created_at and within 7 days
        updated_solicitations = await session.execute(
            select(func.count(SamSolicitation.id))
            .where(
                and_(
                    SamSolicitation.organization_id == organization_id,
                    SamSolicitation.updated_at >= seven_days_ago,
                    SamSolicitation.notice_count > 1,
                )
            )
        )

        return {
            "total_notices": total_notices.scalar_one(),
            "total_solicitations": total_solicitations.scalar_one(),
            "recent_notices_7d": recent_notices.scalar_one(),
            "new_solicitations_7d": new_solicitations.scalar_one(),
            "updated_solicitations_7d": updated_solicitations.scalar_one(),
        }

    async def list_all_notices(
        self,
        session: AsyncSession,
        organization_id: UUID,
        agency: Optional[str] = None,
        sub_agency: Optional[str] = None,
        office: Optional[str] = None,
        notice_type: Optional[str] = None,
        posted_from: Optional[datetime] = None,
        posted_to: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[SamNotice], int]:
        """
        List all notices for an organization with filters.

        This queries across all solicitations in the organization,
        not limited to a single search.

        Returns:
            Tuple of (notices list, total count)
        """
        # Build base query with organization filter via solicitation join
        query = (
            select(SamNotice)
            .join(SamSolicitation)
            .where(SamSolicitation.organization_id == organization_id)
        )

        # Apply filters
        if agency:
            query = query.where(SamSolicitation.agency_name.ilike(f"%{agency}%"))
        if sub_agency:
            query = query.where(SamSolicitation.bureau_name.ilike(f"%{sub_agency}%"))
        if office:
            query = query.where(SamSolicitation.office_name.ilike(f"%{office}%"))
        if notice_type:
            query = query.where(SamNotice.notice_type == notice_type)
        if posted_from:
            query = query.where(SamNotice.posted_date >= posted_from)
        if posted_to:
            query = query.where(SamNotice.posted_date <= posted_to)

        # Build count query with same filters
        count_query = (
            select(func.count(SamNotice.id))
            .join(SamSolicitation)
            .where(SamSolicitation.organization_id == organization_id)
        )
        if agency:
            count_query = count_query.where(SamSolicitation.agency_name.ilike(f"%{agency}%"))
        if sub_agency:
            count_query = count_query.where(SamSolicitation.bureau_name.ilike(f"%{sub_agency}%"))
        if office:
            count_query = count_query.where(SamSolicitation.office_name.ilike(f"%{office}%"))
        if notice_type:
            count_query = count_query.where(SamNotice.notice_type == notice_type)
        if posted_from:
            count_query = count_query.where(SamNotice.posted_date >= posted_from)
        if posted_to:
            count_query = count_query.where(SamNotice.posted_date <= posted_to)

        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Get paginated results ordered by posted date descending
        query = query.order_by(SamNotice.posted_date.desc().nullslast())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        notices = list(result.scalars().all())

        return notices, total

    async def update_solicitation_summary_status(
        self,
        session: AsyncSession,
        solicitation_id: UUID,
        status: str,
        summary_generated_at: Optional[datetime] = None,
    ) -> Optional[SamSolicitation]:
        """
        Update the auto-summary status of a solicitation.

        Args:
            session: Database session
            solicitation_id: Solicitation UUID
            status: Summary status (pending, generating, ready, failed, no_llm)
            summary_generated_at: When summary was generated (for status=ready)

        Returns:
            Updated solicitation or None if not found
        """
        solicitation = await self.get_solicitation(session, solicitation_id)
        if not solicitation:
            return None

        solicitation.summary_status = status
        if summary_generated_at:
            solicitation.summary_generated_at = summary_generated_at

        await session.commit()
        await session.refresh(solicitation)

        logger.info(f"Updated solicitation {solicitation_id} summary_status to {status}")

        return solicitation


# Singleton instance
sam_service = SamService()
