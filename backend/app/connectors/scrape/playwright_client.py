"""Backward-compatibility shim — real implementation in connectors/adapters/."""
from app.connectors.adapters.playwright_adapter import (
    DocumentLink,
    LinkInfo,
    PlaywrightClient,
    PlaywrightError,
    RenderResponse,
    get_playwright_client,
    playwright_client,
)

__all__ = [
    "PlaywrightClient",
    "PlaywrightError",
    "RenderResponse",
    "LinkInfo",
    "DocumentLink",
    "get_playwright_client",
    "playwright_client",
]
