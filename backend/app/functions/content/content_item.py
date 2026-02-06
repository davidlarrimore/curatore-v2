# backend/app/functions/content/content_item.py
"""
ContentItem - Universal data container for the Functions Framework.

ContentItem provides a consistent interface for working with different
content types (assets, solicitations, notices, scraped assets) across
functions and procedures. It enables:

- Uniform access patterns regardless of underlying data model
- Consistent text extraction for LLM operations
- Hierarchical relationships (parent/children)
- Lazy loading of large text content
- Serialization for API responses and Jinja2 templates

Key Design Principles:
    1. Type-agnostic: Same interface for all content types
    2. LLM-friendly: Easy text extraction for prompts
    3. Relationship-aware: Parent/child navigation
    4. Lazy-loadable: Large content fetched on demand
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime


@dataclass
class ContentItem:
    """
    Universal content container for functions and procedures.

    Wraps any content type (asset, solicitation, notice, scraped_asset)
    with a consistent interface for access, text extraction, and serialization.

    Attributes:
        id: Unique identifier (string UUID)
        type: Content type (asset, solicitation, notice, scraped_asset)
        display_type: Context-aware display name (e.g., "Attachment", "Opportunity")

        text: Primary text content for LLM consumption (markdown or JSON)
        text_format: Format of text content ("markdown" or "json")
        title: Display title for the item

        fields: Structured data fields from the source model
        metadata: Additional metadata (source info, timestamps, etc.)

        children: Nested ContentItems (e.g., attachments on a solicitation)
        parent_id: ID of parent item if this is a child
        parent_type: Type of parent item

        text_ref: Reference for lazy loading text ({bucket, key} for MinIO)

    Example:
        # Asset ContentItem
        asset_item = ContentItem(
            id="550e8400-e29b-41d4-a716-446655440000",
            type="asset",
            display_type="Document",
            title="Proposal.pdf",
            text="# Proposal Content...",
            fields={
                "original_filename": "Proposal.pdf",
                "content_type": "application/pdf",
                "file_size": 1024000,
                "status": "ready",
            },
        )

        # Solicitation ContentItem with children
        sol_item = ContentItem(
            id="660e8400-e29b-41d4-a716-446655440001",
            type="solicitation",
            display_type="Opportunity",
            title="IT Support Services",
            text='{"notice_id": "ABC123", "title": "IT Support Services", ...}',
            text_format="json",
            children=[attachment_item1, attachment_item2],
        )
    """

    # Identity
    id: str
    type: str
    display_type: str

    # Content
    text: Optional[str] = None
    text_format: str = "markdown"
    title: Optional[str] = None

    # Structured data
    fields: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Relationships
    children: List["ContentItem"] = field(default_factory=list)
    parent_id: Optional[str] = None
    parent_type: Optional[str] = None

    # Lazy loading reference
    text_ref: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for API responses and Jinja2 templates.

        Returns a serializable dict with all fields. Children are
        recursively converted.
        """
        return {
            "id": self.id,
            "type": self.type,
            "display_type": self.display_type,
            "title": self.title,
            "text": self.text,
            "text_format": self.text_format,
            "fields": self.fields,
            "metadata": self.metadata,
            "children": [c.to_dict() for c in self.children],
            "children_count": len(self.children),
            "parent_id": self.parent_id,
            "parent_type": self.parent_type,
            "has_text": self.text is not None,
            "has_text_ref": self.text_ref is not None,
        }

    def to_summary_dict(self) -> Dict[str, Any]:
        """
        Convert to summary dictionary (without full text content).

        Useful for list views and search results where full text
        is not needed.
        """
        return {
            "id": self.id,
            "type": self.type,
            "display_type": self.display_type,
            "title": self.title,
            "fields": self.fields,
            "metadata": self.metadata,
            "children_count": len(self.children),
            "parent_id": self.parent_id,
            "parent_type": self.parent_type,
            "has_text": self.text is not None,
        }

    @property
    def has_children(self) -> bool:
        """Check if this item has child items."""
        return len(self.children) > 0

    @property
    def is_child(self) -> bool:
        """Check if this item is a child of another item."""
        return self.parent_id is not None

    def get_child_by_type(self, child_type: str) -> List["ContentItem"]:
        """Get all children of a specific type."""
        return [c for c in self.children if c.type == child_type]

    def get_text_preview(self, max_length: int = 500) -> Optional[str]:
        """Get a truncated preview of the text content."""
        if not self.text:
            return None
        if len(self.text) <= max_length:
            return self.text
        return self.text[:max_length] + "..."

    def __repr__(self) -> str:
        return (
            f"<ContentItem(id={self.id}, type={self.type}, "
            f"title={self.title[:30] if self.title else None}...)>"
        )

    def __getattr__(self, name: str) -> Any:
        """
        Allow attribute-style access to fields for cleaner Jinja2 templates.

        This enables templates to use {{ item.source_url }} instead of
        {{ item.fields.source_url }}, making templates more readable.

        Args:
            name: Attribute name to look up

        Returns:
            Value from fields dict if found, None otherwise
        """
        # Safety check during dataclass initialization
        try:
            fields = object.__getattribute__(self, "fields")
        except AttributeError:
            return None
        if name in fields:
            return fields[name]
        # Also check metadata for common attributes
        try:
            metadata = object.__getattribute__(self, "metadata")
        except AttributeError:
            return None
        if name in metadata:
            return metadata[name]
        # Return None for undefined fields (Jinja2 friendly)
        return None
