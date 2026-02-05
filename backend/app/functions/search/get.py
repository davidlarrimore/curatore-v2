# backend/app/functions/search/get.py
"""
Get function - Retrieve a single content item by type and ID.

Generic content retrieval function that works with any content type
(asset, solicitation, notice, scraped_asset) and returns a ContentItem.
"""

from typing import Any, Dict, Optional
from uuid import UUID
import logging

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
)
from ..context import FunctionContext
from ..content import ContentItem, content_service, content_type_registry

logger = logging.getLogger("curatore.functions.search.get")


class GetFunction(BaseFunction):
    """
    Get a single content item by type and ID.

    Generic retrieval function that works with any content type
    (asset, solicitation, notice, scraped_asset). Returns a ContentItem
    with optional text content and children.

    Example:
        # Get an asset with text
        result = await fn.get(ctx,
            item_type="asset",
            item_id="uuid",
            include_text=True,
        )

        # Get a solicitation with attachments
        result = await fn.get(ctx,
            item_type="solicitation",
            item_id="uuid",
            include_children=True,
        )
    """

    meta = FunctionMeta(
        name="get",
        category=FunctionCategory.SEARCH,
        description="Get a single content item by type and ID, returns ContentItem",
        parameters=[
            ParameterDoc(
                name="item_type",
                type="str",
                description="Content type to retrieve",
                required=True,
                enum_values=[
                    "asset", "solicitation", "notice", "scraped_asset",
                    "salesforce_account", "salesforce_contact", "salesforce_opportunity",
                ],
            ),
            ParameterDoc(
                name="item_id",
                type="str",
                description="UUID of the item to retrieve",
                required=True,
            ),
            ParameterDoc(
                name="include_text",
                type="bool",
                description="Whether to load text content",
                required=False,
                default=True,
            ),
            ParameterDoc(
                name="include_children",
                type="bool",
                description="Whether to load child items (e.g., attachments)",
                required=False,
                default=True,
            ),
            ParameterDoc(
                name="context",
                type="str",
                description="Display context for type names",
                required=False,
                default="default",
            ),
        ],
        returns="ContentItem: The retrieved content item",
        tags=["search", "content", "get"],
        requires_llm=False,
        examples=[
            {
                "description": "Get asset with text",
                "params": {
                    "item_type": "asset",
                    "item_id": "uuid",
                    "include_text": True,
                },
            },
            {
                "description": "Get solicitation with children",
                "params": {
                    "item_type": "solicitation",
                    "item_id": "uuid",
                    "include_children": True,
                },
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Get content item by type and ID."""
        item_type = params["item_type"]
        item_id = params["item_id"]
        include_text = params.get("include_text", True)
        include_children = params.get("include_children", True)
        context = params.get("context", "default")

        # Validate item_type
        if not content_type_registry.is_valid_type(item_type):
            return FunctionResult.failed_result(
                error=f"Invalid item_type: {item_type}",
                message=f"Valid types: {', '.join(content_type_registry.list_types())}",
            )

        # Validate and convert item_id
        try:
            item_uuid = UUID(item_id) if isinstance(item_id, str) else item_id
        except ValueError as e:
            return FunctionResult.failed_result(
                error=f"Invalid item_id: {e}",
                message="Item ID must be a valid UUID",
            )

        try:
            # Use ContentService to get the item
            item = await content_service.get(
                session=ctx.session,
                organization_id=ctx.organization_id,
                item_type=item_type,
                item_id=item_uuid,
                include_children=include_children,
                include_text=include_text,
                context=context,
                minio_service=ctx.minio_service,
            )

            if not item:
                type_name = content_type_registry.get_formal_name(item_type)
                return FunctionResult.failed_result(
                    error=f"{type_name} not found",
                    message=f"No {type_name.lower()} found with ID {item_id}",
                )

            return FunctionResult.success_result(
                data=item,
                message=f"Retrieved {item.display_type}: {item.title or item.id}",
                metadata={
                    "item_type": item_type,
                    "item_id": str(item_uuid),
                    "has_text": item.text is not None,
                    "has_text_ref": item.text_ref is not None,
                    "children_count": len(item.children),
                    "result_type": "ContentItem",
                },
            )

        except Exception as e:
            logger.exception(f"Failed to get {item_type}: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message=f"Failed to retrieve {item_type}",
            )
