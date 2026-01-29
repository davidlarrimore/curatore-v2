"""
Playwright Service Pydantic Models.

Request and response models for the rendering API.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class RenderRequest(BaseModel):
    """Request model for page rendering."""

    url: str = Field(..., description="URL to render")
    wait_for_selector: Optional[str] = Field(
        default=None,
        description="CSS selector to wait for before capturing content",
    )
    wait_timeout_ms: int = Field(
        default=5000,
        description="How long to wait for the selector (ms)",
    )
    viewport_width: int = Field(default=1920, description="Viewport width in pixels")
    viewport_height: int = Field(default=1080, description="Viewport height in pixels")
    timeout_ms: int = Field(
        default=30000,
        description="Total timeout for page load and rendering (ms)",
    )
    extract_documents: bool = Field(
        default=True,
        description="Whether to extract document links (PDFs, DOCXs, etc.)",
    )
    document_extensions: List[str] = Field(
        default=[".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"],
        description="File extensions to identify as downloadable documents",
    )


class LinkInfo(BaseModel):
    """Information about a discovered link."""

    url: str = Field(..., description="Absolute URL of the link")
    text: str = Field(default="", description="Link text content")
    rel: Optional[str] = Field(default=None, description="Rel attribute if present")


class DocumentLink(BaseModel):
    """Information about a discovered document link."""

    url: str = Field(..., description="Absolute URL of the document")
    filename: str = Field(..., description="Extracted filename from URL")
    extension: str = Field(..., description="File extension (lowercase)")
    link_text: str = Field(default="", description="Link text content")


class RenderResponse(BaseModel):
    """Response model for page rendering."""

    # Page content
    html: str = Field(..., description="Rendered HTML content")
    markdown: str = Field(..., description="Extracted markdown with structure")
    text: str = Field(..., description="Clean text content")
    title: str = Field(default="", description="Page title")

    # Links discovered
    links: List[LinkInfo] = Field(default_factory=list, description="All links for crawling")
    document_links: List[DocumentLink] = Field(
        default_factory=list,
        description="Document links (PDFs, DOCXs, etc.)",
    )

    # Metadata
    final_url: str = Field(..., description="Final URL after redirects")
    status_code: int = Field(..., description="HTTP status code")
    render_time_ms: int = Field(..., description="Time taken to render page")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(default="healthy", description="Service status")
    browser_pool_size: int = Field(..., description="Configured browser pool size")
    active_browsers: int = Field(..., description="Currently active browsers")
