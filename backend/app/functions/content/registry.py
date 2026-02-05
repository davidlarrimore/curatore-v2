# backend/app/functions/content/registry.py
"""
ContentTypeRegistry - Type definitions for the ContentItem system.

Defines available content types and their properties:
- Model class mappings
- Text source configuration
- Child relationships
- Display name variations
- Field mappings

This registry enables the ContentService to fetch and transform
database records into ContentItem instances consistently.
"""

from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("curatore.functions.content.registry")


# Type definitions for all supported content types
CONTENT_TYPE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "asset": {
        "formal_name": "Asset",
        "model": "Asset",
        "has_text": True,
        "text_source": "extraction",  # Text comes from ExtractionResult
        "text_format": "markdown",
        "children": [],  # Assets don't have children
        "display_names": {
            "default": "Document",
            "solicitation": "Attachment",
            "notice": "Attachment",
            "scraped_asset": "Download",
            "sharepoint_sync": "SharePoint File",
            "upload": "Uploaded Document",
            "sam_gov": "SAM.gov Attachment",
        },
        "fields": {
            "original_filename": "original_filename",
            "content_type": "content_type",
            "file_size": "file_size",
            "status": "status",
            "source_type": "source_type",
            "extraction_tier": "extraction_tier",
            "indexed_at": "indexed_at",
            "file_hash": "file_hash",
        },
        "metadata_fields": {
            "raw_bucket": "raw_bucket",
            "raw_object_key": "raw_object_key",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
        "title_field": "original_filename",
    },

    "solicitation": {
        "formal_name": "Solicitation",
        "model": "SamSolicitation",
        "has_text": True,
        "text_source": "record",  # Text is JSON of the record itself
        "text_format": "json",
        "children": [
            {"type": "notice", "relation": "notices", "display_name": "Notice"},
            {"type": "asset", "relation": "attachments.asset", "display_name": "Attachment"},
        ],
        "display_names": {
            "default": "Solicitation",
            "sam": "Opportunity",
            "search": "Contract Opportunity",
        },
        "fields": {
            "notice_id": "notice_id",
            "solicitation_number": "solicitation_number",
            "title": "title",
            "description": "description",
            "notice_type": "notice_type",
            "agency_name": "agency_name",
            "bureau_name": "bureau_name",
            "office_name": "office_name",
            "naics_code": "naics_code",
            "psc_code": "psc_code",
            "set_aside_code": "set_aside_code",
            "status": "status",
            "posted_date": "posted_date",
            "response_deadline": "response_deadline",
            "ui_link": "ui_link",
            "notice_count": "notice_count",
            "attachment_count": "attachment_count",
            "summary_status": "summary_status",
        },
        "metadata_fields": {
            "contact_info": "contact_info",
            "place_of_performance": "place_of_performance",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
        "title_field": "title",
        "summary_field": "description",  # For auto-generated summary text
    },

    "notice": {
        "formal_name": "Notice",
        "model": "SamNotice",
        "has_text": True,
        "text_source": "record",  # Text is JSON of the record
        "text_format": "json",
        "children": [
            {"type": "asset", "relation": "attachments.asset", "display_name": "Attachment"},
        ],
        "display_names": {
            "default": "Notice",
            "solicitation": "Amendment",
            "standalone": "Special Notice",
        },
        "fields": {
            "sam_notice_id": "sam_notice_id",
            "notice_type": "notice_type",
            "version_number": "version_number",
            "title": "title",
            "description": "description",
            "posted_date": "posted_date",
            "response_deadline": "response_deadline",
            "agency_name": "agency_name",
            "bureau_name": "bureau_name",
            "office_name": "office_name",
        },
        "metadata_fields": {
            "raw_json_bucket": "raw_json_bucket",
            "raw_json_key": "raw_json_key",
            "changes_summary": "changes_summary",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
        "title_field": "title",
        "parent_type": "solicitation",
        "parent_field": "solicitation_id",
    },

    "scraped_asset": {
        "formal_name": "Scraped Asset",
        "model": "ScrapedAsset",
        "has_text": True,
        "text_source": "linked_asset",  # Text from linked Asset's extraction
        "text_format": "markdown",
        "children": [],
        "display_names": {
            "default": "Scraped Content",
            "page": "Web Page",
            "record": "Captured Document",
        },
        "fields": {
            "url": "url",
            "url_path": "url_path",
            "parent_url": "parent_url",
            "asset_subtype": "asset_subtype",
            "crawl_depth": "crawl_depth",
            "is_promoted": "is_promoted",
        },
        "metadata_fields": {
            "scrape_metadata": "scrape_metadata",
            "promoted_at": "promoted_at",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
        "title_field": None,  # Title comes from scrape_metadata or asset
        "linked_asset_field": "asset_id",  # Points to Asset for text content
        "parent_type": "scrape_collection",
        "parent_field": "collection_id",
    },

    "scrape_collection": {
        "formal_name": "Scrape Collection",
        "model": "ScrapeCollection",
        "has_text": False,  # Collections don't have text content
        "text_source": None,
        "children": [
            {"type": "scraped_asset", "relation": "scraped_assets", "display_name": "Page"},
        ],
        "display_names": {
            "default": "Collection",
            "active": "Active Collection",
            "archived": "Archived Collection",
        },
        "fields": {
            "name": "name",
            "slug": "slug",
            "description": "description",
            "collection_mode": "collection_mode",
            "root_url": "root_url",
            "status": "status",
        },
        "metadata_fields": {
            "url_patterns": "url_patterns",
            "crawl_config": "crawl_config",
            "stats": "stats",
            "last_crawl_at": "last_crawl_at",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
        "title_field": "name",
    },
}


class ContentTypeRegistry:
    """
    Registry for content type definitions.

    Provides lookup methods for content type configuration,
    display names, and field mappings.

    Usage:
        registry = ContentTypeRegistry()

        # Get type config
        config = registry.get_type_config("asset")

        # Get context-aware display name
        name = registry.get_display_name("asset", context="solicitation")
        # Returns "Attachment"
    """

    def __init__(self, type_definitions: Optional[Dict[str, Any]] = None):
        """
        Initialize the registry with type definitions.

        Args:
            type_definitions: Custom type definitions (uses default if None)
        """
        self._types = type_definitions or CONTENT_TYPE_REGISTRY

    def get_type_config(self, type_name: str) -> Optional[Dict[str, Any]]:
        """
        Get the full configuration for a content type.

        Args:
            type_name: Content type name (asset, solicitation, notice, scraped_asset)

        Returns:
            Type configuration dict or None if not found
        """
        return self._types.get(type_name)

    def get_display_name(self, type_name: str, context: str = "default") -> str:
        """
        Get the context-aware display name for a content type.

        Args:
            type_name: Content type name
            context: Display context (e.g., "solicitation", "notice", "default")

        Returns:
            Display name string (falls back to type name if not found)
        """
        config = self.get_type_config(type_name)
        if not config:
            return type_name.replace("_", " ").title()

        display_names = config.get("display_names", {})
        return display_names.get(context, display_names.get("default", type_name.title()))

    def get_formal_name(self, type_name: str) -> str:
        """Get the formal name for a content type (for documentation)."""
        config = self.get_type_config(type_name)
        if not config:
            return type_name.replace("_", " ").title()
        return config.get("formal_name", type_name.title())

    def get_model_name(self, type_name: str) -> Optional[str]:
        """Get the SQLAlchemy model class name for a content type."""
        config = self.get_type_config(type_name)
        return config.get("model") if config else None

    def get_title_field(self, type_name: str) -> Optional[str]:
        """Get the field name to use as title for a content type."""
        config = self.get_type_config(type_name)
        return config.get("title_field") if config else None

    def get_text_source(self, type_name: str) -> Optional[str]:
        """Get the text source type for a content type."""
        config = self.get_type_config(type_name)
        return config.get("text_source") if config else None

    def get_text_format(self, type_name: str) -> str:
        """Get the text format (markdown/json) for a content type."""
        config = self.get_type_config(type_name)
        return config.get("text_format", "markdown") if config else "markdown"

    def has_text(self, type_name: str) -> bool:
        """Check if a content type has text content."""
        config = self.get_type_config(type_name)
        return config.get("has_text", False) if config else False

    def get_children_config(self, type_name: str) -> List[Dict[str, str]]:
        """Get the child type configurations for a content type."""
        config = self.get_type_config(type_name)
        return config.get("children", []) if config else []

    def has_children(self, type_name: str) -> bool:
        """Check if a content type can have children."""
        return len(self.get_children_config(type_name)) > 0

    def get_field_mapping(self, type_name: str) -> Dict[str, str]:
        """Get the field name mapping for a content type."""
        config = self.get_type_config(type_name)
        return config.get("fields", {}) if config else {}

    def get_metadata_mapping(self, type_name: str) -> Dict[str, str]:
        """Get the metadata field mapping for a content type."""
        config = self.get_type_config(type_name)
        return config.get("metadata_fields", {}) if config else {}

    def list_types(self) -> List[str]:
        """List all registered content type names."""
        return list(self._types.keys())

    def is_valid_type(self, type_name: str) -> bool:
        """Check if a type name is valid/registered."""
        return type_name in self._types


# Global singleton instance
content_type_registry = ContentTypeRegistry()
