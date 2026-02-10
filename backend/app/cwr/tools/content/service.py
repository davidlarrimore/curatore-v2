# backend/app/functions/content/service.py
"""
ContentService - Unified service for fetching and transforming content.

Provides a consistent interface for:
- Fetching content by type and ID → ContentItem
- Searching content with filters → List[ContentItem]
- Extracting text for LLM consumption

This service abstracts away the differences between content types
(Asset, SamSolicitation, SamNotice, ScrapedAsset, SalesforceAccount,
SalesforceContact, SalesforceOpportunity) and provides a unified
ContentItem interface.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Union
from uuid import UUID

from sqlalchemy import select, and_, or_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .content_item import ContentItem
from .registry import content_type_registry, CONTENT_TYPE_REGISTRY

logger = logging.getLogger("curatore.functions.content.service")


class ContentService:
    """
    Unified service for fetching and transforming content to ContentItem.

    This service provides a type-agnostic interface for working with
    different content types in the Curatore system.

    Usage:
        service = ContentService()

        # Get a single item
        item = await service.get(
            session, org_id, "asset", "uuid",
            include_children=True, include_text=True
        )

        # Search for items
        items = await service.search(
            session, org_id, "solicitation",
            filters={"status": "active", "naics_code": "541512"},
            limit=50
        )

        # Extract text for LLM
        text = service.extract_text(item, include_children=True)
    """

    def __init__(self):
        """Initialize the content service."""
        self._model_cache: Dict[str, Type] = {}

    def _get_model_class(self, model_name: str) -> Optional[Type]:
        """
        Get the SQLAlchemy model class by name.

        Lazy loads and caches model classes to avoid circular imports.
        """
        if model_name in self._model_cache:
            return self._model_cache[model_name]

        try:
            from app.core.database.models import (
                Asset,
                SamSolicitation,
                SamNotice,
                ScrapedAsset,
                ScrapeCollection,
                SalesforceAccount,
                SalesforceContact,
                SalesforceOpportunity,
            )

            models = {
                "Asset": Asset,
                "SamSolicitation": SamSolicitation,
                "SamNotice": SamNotice,
                "ScrapedAsset": ScrapedAsset,
                "ScrapeCollection": ScrapeCollection,
                "SalesforceAccount": SalesforceAccount,
                "SalesforceContact": SalesforceContact,
                "SalesforceOpportunity": SalesforceOpportunity,
            }
            model = models.get(model_name)
            if model:
                self._model_cache[model_name] = model
            return model
        except ImportError as e:
            logger.error(f"Failed to import model {model_name}: {e}")
            return None

    async def get(
        self,
        session: AsyncSession,
        organization_id: UUID,
        item_type: str,
        item_id: Union[str, UUID],
        include_children: bool = True,
        include_text: bool = True,
        context: str = "default",
        minio_service: Optional[Any] = None,
    ) -> Optional[ContentItem]:
        """
        Get a single content item by type and ID.

        Args:
            session: Database session
            organization_id: Organization ID for multi-tenancy
            item_type: Content type (asset, solicitation, notice, scraped_asset)
            item_id: UUID of the item
            include_children: Whether to load child items
            include_text: Whether to load text content
            context: Display context for type names
            minio_service: MinIO service for loading text (optional)

        Returns:
            ContentItem or None if not found
        """
        config = content_type_registry.get_type_config(item_type)
        if not config:
            logger.warning(f"Unknown content type: {item_type}")
            return None

        model_name = config.get("model")
        model = self._get_model_class(model_name)
        if not model:
            logger.error(f"Model not found for type: {item_type}")
            return None

        # Convert ID to UUID if needed
        if isinstance(item_id, str):
            item_id = UUID(item_id)

        # Build query based on type
        record = await self._fetch_record(
            session, model, organization_id, item_id, item_type, include_children
        )
        if not record:
            return None

        return await self._record_to_content_item(
            session=session,
            record=record,
            item_type=item_type,
            config=config,
            include_children=include_children,
            include_text=include_text,
            context=context,
            organization_id=organization_id,
            minio_service=minio_service,
        )

    async def _fetch_record(
        self,
        session: AsyncSession,
        model: Type,
        organization_id: UUID,
        item_id: UUID,
        item_type: str,
        include_children: bool,
    ) -> Optional[Any]:
        """Fetch a record from the database by type."""
        # Build base query
        query = select(model).where(model.id == item_id)

        # Add organization filter based on type
        if item_type in (
            "asset", "solicitation", "scrape_collection",
            "salesforce_account", "salesforce_contact", "salesforce_opportunity",
        ):
            query = query.where(model.organization_id == organization_id)
        elif item_type == "notice":
            # Notices may be standalone (have organization_id) or linked to solicitation
            query = query.where(
                or_(
                    model.organization_id == organization_id,
                    model.solicitation.has(organization_id=organization_id),
                )
            )
        elif item_type == "scraped_asset":
            # ScrapedAsset links to Asset which has organization_id
            query = query.where(
                model.asset.has(organization_id=organization_id)
            )

        # Add eager loading for children
        if include_children:
            if item_type == "solicitation":
                from app.core.database.models import SamSolicitation
                query = query.options(
                    selectinload(SamSolicitation.notices),
                    selectinload(SamSolicitation.attachments),
                )
            elif item_type == "notice":
                from app.core.database.models import SamNotice
                query = query.options(
                    selectinload(SamNotice.attachments),
                )
            elif item_type == "scraped_asset":
                from app.core.database.models import ScrapedAsset
                query = query.options(
                    selectinload(ScrapedAsset.asset),
                )
            elif item_type == "salesforce_account":
                from app.core.database.models import SalesforceAccount
                query = query.options(
                    selectinload(SalesforceAccount.contacts),
                    selectinload(SalesforceAccount.opportunities),
                )

        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def _record_to_content_item(
        self,
        session: AsyncSession,
        record: Any,
        item_type: str,
        config: Dict[str, Any],
        include_children: bool,
        include_text: bool,
        context: str,
        organization_id: UUID,
        minio_service: Optional[Any] = None,
    ) -> ContentItem:
        """Convert a database record to a ContentItem."""
        # Get display type
        display_type = content_type_registry.get_display_name(item_type, context)

        # Extract fields
        fields = self._extract_fields(record, config.get("fields", {}))
        metadata = self._extract_fields(record, config.get("metadata_fields", {}))

        # Get title
        title_field = config.get("title_field")
        title = getattr(record, title_field, None) if title_field else None

        # Handle scraped_asset title (from linked asset or metadata)
        if item_type == "scraped_asset" and not title:
            if hasattr(record, "asset") and record.asset:
                title = record.asset.original_filename
            elif hasattr(record, "scrape_metadata") and record.scrape_metadata:
                title = record.scrape_metadata.get("title")

        # Handle salesforce_contact title (computed from first + last name)
        if item_type == "salesforce_contact" and not title:
            first = getattr(record, "first_name", "") or ""
            last = getattr(record, "last_name", "") or ""
            title = f"{first} {last}".strip() or None

        # Get text content
        text = None
        text_format = config.get("text_format", "markdown")
        text_ref = None

        if include_text and config.get("has_text"):
            text, text_ref = await self._get_text_content(
                session, record, item_type, config, organization_id, minio_service
            )

        # Build children
        children = []
        if include_children and config.get("children"):
            children = await self._build_children(
                session, record, item_type, config, organization_id, context, minio_service
            )

        # Get parent info
        parent_id = None
        parent_type = None
        if "parent_field" in config:
            parent_id_value = getattr(record, config["parent_field"], None)
            if parent_id_value:
                parent_id = str(parent_id_value)
                parent_type = config.get("parent_type")

        return ContentItem(
            id=str(record.id),
            type=item_type,
            display_type=display_type,
            text=text,
            text_format=text_format,
            title=title,
            fields=fields,
            metadata=metadata,
            children=children,
            parent_id=parent_id,
            parent_type=parent_type,
            text_ref=text_ref,
        )

    def _extract_fields(self, record: Any, field_mapping: Dict[str, str]) -> Dict[str, Any]:
        """Extract fields from a record using the field mapping."""
        fields = {}
        for target_name, source_name in field_mapping.items():
            value = getattr(record, source_name, None)
            # Convert datetime to ISO format
            if isinstance(value, datetime):
                value = value.isoformat()
            # Convert UUID to string
            elif isinstance(value, UUID):
                value = str(value)
            fields[target_name] = value
        return fields

    async def _get_text_content(
        self,
        session: AsyncSession,
        record: Any,
        item_type: str,
        config: Dict[str, Any],
        organization_id: UUID,
        minio_service: Optional[Any] = None,
    ) -> tuple[Optional[str], Optional[Dict[str, str]]]:
        """
        Get text content for a record based on its text_source configuration.

        Returns:
            Tuple of (text, text_ref) where text_ref is for lazy loading
        """
        text_source = config.get("text_source")

        if text_source == "extraction":
            # Get text from ExtractionResult (for assets)
            return await self._get_extraction_text(session, record, minio_service)

        elif text_source == "record":
            # Convert record fields to JSON (for solicitations, notices)
            return self._get_record_as_json(record, config), None

        elif text_source == "linked_asset":
            # Get text from linked asset (for scraped_assets)
            if hasattr(record, "asset") and record.asset:
                return await self._get_extraction_text(session, record.asset, minio_service)
            return None, None

        return None, None

    async def _get_extraction_text(
        self,
        session: AsyncSession,
        asset: Any,
        minio_service: Optional[Any] = None,
    ) -> tuple[Optional[str], Optional[Dict[str, str]]]:
        """Get extracted text content for an asset."""
        from app.core.database.models import ExtractionResult

        # Find the latest completed extraction
        query = (
            select(ExtractionResult)
            .where(
                ExtractionResult.asset_id == asset.id,
                ExtractionResult.status == "completed",
            )
            .order_by(ExtractionResult.created_at.desc())
            .limit(1)
        )
        result = await session.execute(query)
        extraction = result.scalar_one_or_none()

        if not extraction:
            return None, None

        # Return text_ref for lazy loading if no minio_service
        text_ref = None
        if extraction.extracted_bucket and extraction.extracted_object_key:
            text_ref = {
                "bucket": extraction.extracted_bucket,
                "key": extraction.extracted_object_key,
            }

        # Load text if minio_service is provided
        if minio_service and text_ref:
            try:
                content_io = minio_service.get_object(
                    bucket=text_ref["bucket"],
                    key=text_ref["key"],
                )
                if content_io:
                    content = content_io.read()
                    text = content.decode("utf-8") if isinstance(content, bytes) else content
                    return text, text_ref
            except Exception as e:
                logger.warning(f"Failed to load extraction text: {e}")

        return None, text_ref

    def _get_record_as_json(self, record: Any, config: Dict[str, Any]) -> str:
        """Convert a record to JSON text representation."""
        # Get all fields from the field mapping
        fields = self._extract_fields(record, config.get("fields", {}))

        # Add summary field if present
        summary_field = config.get("summary_field")
        if summary_field:
            summary = getattr(record, summary_field, None)
            if summary:
                fields["_summary"] = summary[:1000] if len(summary) > 1000 else summary

        return json.dumps(fields, indent=2, default=str)

    async def _build_children(
        self,
        session: AsyncSession,
        record: Any,
        item_type: str,
        config: Dict[str, Any],
        organization_id: UUID,
        context: str,
        minio_service: Optional[Any] = None,
    ) -> List[ContentItem]:
        """Build child ContentItems for a record."""
        children = []
        children_config = config.get("children", [])

        for child_config in children_config:
            child_type = child_config["type"]
            relation = child_config["relation"]

            # Handle dotted relation paths (e.g., "attachments.asset")
            parts = relation.split(".")
            child_records = getattr(record, parts[0], None)

            if not child_records:
                continue

            # Ensure it's iterable
            if not isinstance(child_records, (list, tuple)):
                child_records = [child_records]

            for child_record in child_records:
                # Handle dotted paths (e.g., get asset from attachment)
                target_record = child_record
                for part in parts[1:]:
                    target_record = getattr(target_record, part, None)
                    if not target_record:
                        break

                if not target_record:
                    continue

                # Get child config
                child_type_config = content_type_registry.get_type_config(child_type)
                if not child_type_config:
                    continue

                # Convert child to ContentItem (without recursing children)
                child_item = await self._record_to_content_item(
                    session=session,
                    record=target_record,
                    item_type=child_type,
                    config=child_type_config,
                    include_children=False,  # Don't recurse
                    include_text=False,  # Don't load text for children by default
                    context=item_type,  # Parent type as context
                    organization_id=organization_id,
                    minio_service=minio_service,
                )
                child_item.parent_id = str(record.id)
                child_item.parent_type = item_type
                children.append(child_item)

        return children

    async def search(
        self,
        session: AsyncSession,
        organization_id: UUID,
        item_type: str,
        filters: Optional[Dict[str, Any]] = None,
        include_children: bool = False,
        include_text: bool = False,
        limit: int = 100,
        offset: int = 0,
        order_by: Optional[str] = None,
        context: str = "default",
    ) -> List[ContentItem]:
        """
        Search for content items with filters.

        Args:
            session: Database session
            organization_id: Organization ID for multi-tenancy
            item_type: Content type to search
            filters: Type-specific filters (e.g., {"status": "active"})
            include_children: Whether to load child items
            include_text: Whether to load text content
            limit: Maximum results
            offset: Pagination offset
            order_by: Field to order by (prefix with - for descending)
            context: Display context for type names

        Returns:
            List of ContentItem instances
        """
        config = content_type_registry.get_type_config(item_type)
        if not config:
            logger.warning(f"Unknown content type: {item_type}")
            return []

        model_name = config.get("model")
        model = self._get_model_class(model_name)
        if not model:
            logger.error(f"Model not found for type: {item_type}")
            return []

        # Build base query with organization filter
        query = select(model)

        if item_type in (
            "asset", "solicitation", "scrape_collection",
            "salesforce_account", "salesforce_contact", "salesforce_opportunity",
        ):
            query = query.where(model.organization_id == organization_id)
        elif item_type == "notice":
            from app.core.database.models import SamSolicitation
            query = query.where(
                or_(
                    model.organization_id == organization_id,
                    model.solicitation.has(
                        SamSolicitation.organization_id == organization_id
                    ),
                )
            )
        elif item_type == "scraped_asset":
            from app.core.database.models import Asset
            query = query.where(
                model.asset.has(Asset.organization_id == organization_id)
            )

        # Apply filters
        if filters:
            query = self._apply_filters(query, model, filters, config)

        # Apply ordering
        if order_by:
            desc_order = order_by.startswith("-")
            field_name = order_by.lstrip("-")
            if hasattr(model, field_name):
                order_col = getattr(model, field_name)
                query = query.order_by(desc(order_col) if desc_order else order_col)
        else:
            # Default ordering by created_at desc
            if hasattr(model, "created_at"):
                query = query.order_by(desc(model.created_at))

        # Apply pagination
        query = query.offset(offset).limit(limit)

        # Execute query
        result = await session.execute(query)
        records = result.scalars().all()

        # Convert to ContentItems
        items = []
        for record in records:
            item = await self._record_to_content_item(
                session=session,
                record=record,
                item_type=item_type,
                config=config,
                include_children=include_children,
                include_text=include_text,
                context=context,
                organization_id=organization_id,
            )
            items.append(item)

        return items

    def _apply_filters(
        self,
        query,
        model: Type,
        filters: Dict[str, Any],
        config: Dict[str, Any],
    ):
        """Apply filters to a query based on filter dict."""
        field_mapping = config.get("fields", {})

        for key, value in filters.items():
            # Skip None values
            if value is None:
                continue

            # Get the actual field name from mapping, or use key directly
            field_name = field_mapping.get(key, key)

            if not hasattr(model, field_name):
                logger.warning(f"Unknown filter field: {field_name} for {model.__name__}")
                continue

            field = getattr(model, field_name)

            # Handle different filter types
            if isinstance(value, list):
                query = query.where(field.in_(value))
            elif isinstance(value, dict) and "gte" in value:
                query = query.where(field >= value["gte"])
            elif isinstance(value, dict) and "lte" in value:
                query = query.where(field <= value["lte"])
            elif isinstance(value, str) and value.startswith("%") or value.endswith("%"):
                query = query.where(field.ilike(value))
            else:
                query = query.where(field == value)

        return query

    def extract_text(
        self,
        item: ContentItem,
        include_children: bool = True,
        max_depth: int = 2,
        separator: str = "\n\n",
    ) -> str:
        """
        Extract all text content from a ContentItem for LLM consumption.

        Recursively extracts text from the item and its children,
        formatting it as markdown for LLM prompts.

        Args:
            item: ContentItem to extract from
            include_children: Whether to include child text
            max_depth: Maximum recursion depth for children
            separator: Text separator between sections

        Returns:
            Combined text content as markdown
        """
        parts = []

        # Add title as heading
        if item.title:
            parts.append(f"# {item.title}")

        # Add type indicator
        parts.append(f"*Type: {item.display_type}*")

        # Add main text
        if item.text:
            if item.text_format == "json":
                # Format JSON nicely
                try:
                    data = json.loads(item.text)
                    formatted = self._format_json_for_llm(data)
                    parts.append(formatted)
                except json.JSONDecodeError:
                    parts.append(item.text)
            else:
                parts.append(item.text)

        # Add children
        if include_children and item.children and max_depth > 0:
            for child in item.children:
                display = child.display_type or child.type.title()
                child_title = child.title or "Untitled"
                parts.append(f"\n## {display}: {child_title}")

                child_text = self.extract_text(
                    child,
                    include_children=True,
                    max_depth=max_depth - 1,
                    separator=separator,
                )
                if child_text:
                    parts.append(child_text)

        return separator.join(filter(None, parts))

    def _format_json_for_llm(self, data: Dict[str, Any]) -> str:
        """Format JSON data as readable markdown for LLM."""
        lines = []
        for key, value in data.items():
            if value is None:
                continue
            # Skip internal fields
            if key.startswith("_"):
                continue
            # Format key nicely
            nice_key = key.replace("_", " ").title()
            # Handle different value types
            if isinstance(value, dict):
                lines.append(f"**{nice_key}:** {json.dumps(value)}")
            elif isinstance(value, list):
                if value:
                    lines.append(f"**{nice_key}:** {', '.join(str(v) for v in value)}")
            else:
                lines.append(f"**{nice_key}:** {value}")
        return "\n".join(lines)


# Global singleton instance
content_service = ContentService()
