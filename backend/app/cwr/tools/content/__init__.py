# backend/app/cwr/tools/content/__init__.py
"""
Content module for the Curatore Functions Framework.

Provides a universal data model (ContentItem) and services for working
with different content types (assets, solicitations, notices, etc.) in a
consistent way across functions and procedures.

Key Components:
    - ContentItem: Universal container for any content type
    - ContentTypeRegistry: Defines available content types and their properties
    - ContentService: Fetches and transforms content to ContentItem instances

Usage:
    from app.cwr.tools.content import ContentItem, content_service

    # Get a single item
    item = await content_service.get(session, org_id, "asset", asset_id)

    # Search for items
    items = await content_service.search(session, org_id, "solicitation", filters={...})

    # Extract text for LLM
    text = content_service.extract_text(item, include_children=True)
"""

from .content_item import ContentItem
from .registry import ContentTypeRegistry, content_type_registry, CONTENT_TYPE_REGISTRY
from .service import ContentService, content_service

__all__ = [
    "ContentItem",
    "ContentTypeRegistry",
    "content_type_registry",
    "CONTENT_TYPE_REGISTRY",
    "ContentService",
    "content_service",
]
