# ============================================================================
# backend/app/api/v1/routers/render.py
# ============================================================================
"""
General Web Rendering API Endpoints.

Provides access to the Playwright rendering service for general-purpose
web scraping and content extraction WITHOUT coupling to the asset/storage
methodology. Use these endpoints when you need:

- To render and extract content from a URL without storing it
- To test rendering capabilities
- To integrate with external systems that manage their own storage

For crawling with storage integration, use the web scraping (crawl) endpoints
instead.

Usage:
    POST /api/v1/render
    POST /api/v1/render/extract
    POST /api/v1/render/links
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.connectors.scrape.playwright_client import (
    PlaywrightClient,
    PlaywrightError,
    get_playwright_client,
)
from app.dependencies import get_current_user

router = APIRouter(
    prefix="/render",
    tags=["Rendering"],
    dependencies=[Depends(get_current_user)],
)


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


class RenderRequest(BaseModel):
    """Request to render a URL and extract content."""

    url: str = Field(..., description="URL to render")
    wait_for_selector: Optional[str] = Field(
        None, description="CSS selector to wait for before extracting content"
    )
    wait_timeout_ms: int = Field(
        5000, ge=100, le=30000, description="Timeout for waiting on selector (ms)"
    )
    viewport_width: int = Field(
        1920, ge=320, le=3840, description="Browser viewport width"
    )
    viewport_height: int = Field(
        1080, ge=240, le=2160, description="Browser viewport height"
    )
    timeout_ms: int = Field(
        30000, ge=1000, le=120000, description="Total render timeout (ms)"
    )
    extract_documents: bool = Field(
        True, description="Whether to extract document links (PDFs, DOCXs, etc.)"
    )
    document_extensions: Optional[List[str]] = Field(
        None,
        description="File extensions to identify as documents",
        examples=[[".pdf", ".docx", ".xlsx"]],
    )


class RenderResult(BaseModel):
    """Full render result with all extracted content."""

    # Page content
    html: str = Field(..., description="Rendered HTML")
    markdown: str = Field(..., description="Extracted markdown content")
    text: str = Field(..., description="Plain text content")
    title: str = Field("", description="Page title")

    # Links
    links: List[Dict[str, Any]] = Field(
        default_factory=list, description="All discovered links"
    )
    document_links: List[Dict[str, Any]] = Field(
        default_factory=list, description="Document links (PDFs, DOCXs, etc.)"
    )

    # Metadata
    final_url: str = Field(..., description="Final URL after redirects")
    status_code: int = Field(..., description="HTTP status code")
    render_time_ms: int = Field(..., description="Time to render page (ms)")


class ExtractRequest(BaseModel):
    """Request to extract just text/markdown from a URL."""

    url: str = Field(..., description="URL to render and extract from")
    wait_for_selector: Optional[str] = Field(
        None, description="CSS selector to wait for"
    )
    timeout_ms: int = Field(
        30000, ge=1000, le=120000, description="Total render timeout (ms)"
    )
    format: str = Field(
        "markdown",
        description="Output format: 'markdown', 'text', or 'html'",
        pattern="^(markdown|text|html)$",
    )


class ExtractResult(BaseModel):
    """Extracted content from a URL."""

    url: str = Field(..., description="Original URL")
    final_url: str = Field(..., description="Final URL after redirects")
    title: str = Field("", description="Page title")
    content: str = Field(..., description="Extracted content in requested format")
    format: str = Field(..., description="Format of content")
    render_time_ms: int = Field(..., description="Time to render page (ms)")


class LinksRequest(BaseModel):
    """Request to extract links from a URL."""

    url: str = Field(..., description="URL to render and extract links from")
    wait_for_selector: Optional[str] = Field(
        None, description="CSS selector to wait for"
    )
    timeout_ms: int = Field(
        30000, ge=1000, le=120000, description="Total render timeout (ms)"
    )
    include_documents: bool = Field(
        True, description="Include document links (PDFs, DOCXs, etc.)"
    )
    document_extensions: Optional[List[str]] = Field(
        None, description="File extensions to identify as documents"
    )


class LinksResult(BaseModel):
    """Extracted links from a URL."""

    url: str = Field(..., description="Original URL")
    final_url: str = Field(..., description="Final URL after redirects")
    links: List[Dict[str, Any]] = Field(
        default_factory=list, description="All discovered links"
    )
    document_links: List[Dict[str, Any]] = Field(
        default_factory=list, description="Document links"
    )
    total_links: int = Field(..., description="Total number of links")
    total_document_links: int = Field(..., description="Total document links")
    render_time_ms: int = Field(..., description="Time to render page (ms)")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _get_client() -> PlaywrightClient:
    """Get Playwright client or raise 503 if not configured."""
    client = get_playwright_client()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="Playwright rendering service not configured. "
            "Set PLAYWRIGHT_SERVICE_URL environment variable.",
        )
    return client


# ============================================================================
# ENDPOINTS
# ============================================================================


@router.post("", response_model=RenderResult)
async def render_page(request: RenderRequest) -> RenderResult:
    """
    Render a URL and extract all content.

    This endpoint renders the page using a headless browser, executes JavaScript,
    and extracts:
    - HTML, Markdown, and plain text content
    - All links on the page
    - Document links (PDFs, DOCXs, etc.)
    - Page metadata (title, final URL, status code)

    Use this endpoint for full page rendering with all extracted data.
    For simpler use cases, see /extract (content only) or /links (links only).

    Note: This does NOT store anything to the database or object storage.
    For persistent storage, use the web scraping (crawl) endpoints.
    """
    client = _get_client()

    try:
        result = await client.render_page(
            url=request.url,
            wait_for_selector=request.wait_for_selector,
            wait_timeout_ms=request.wait_timeout_ms,
            viewport_width=request.viewport_width,
            viewport_height=request.viewport_height,
            timeout_ms=request.timeout_ms,
            extract_documents=request.extract_documents,
            document_extensions=request.document_extensions,
        )

        return RenderResult(
            html=result.html,
            markdown=result.markdown,
            text=result.text,
            title=result.title,
            links=[link.model_dump() for link in result.links],
            document_links=[doc.model_dump() for doc in result.document_links],
            final_url=result.final_url,
            status_code=result.status_code,
            render_time_ms=result.render_time_ms,
        )

    except PlaywrightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Rendering failed: {str(e)}"
        )


@router.post("/extract", response_model=ExtractResult)
async def extract_content(request: ExtractRequest) -> ExtractResult:
    """
    Extract text content from a URL.

    Simplified endpoint that renders a page and returns only the content
    in the requested format (markdown, text, or html).

    Use this when you only need the page content, not links or full metadata.
    """
    client = _get_client()

    try:
        result = await client.render_page(
            url=request.url,
            wait_for_selector=request.wait_for_selector,
            timeout_ms=request.timeout_ms,
            extract_documents=False,  # Not needed for content extraction
        )

        # Select content based on format
        if request.format == "markdown":
            content = result.markdown
        elif request.format == "text":
            content = result.text
        else:  # html
            content = result.html

        return ExtractResult(
            url=request.url,
            final_url=result.final_url,
            title=result.title,
            content=content,
            format=request.format,
            render_time_ms=result.render_time_ms,
        )

    except PlaywrightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Content extraction failed: {str(e)}"
        )


@router.post("/links", response_model=LinksResult)
async def extract_links(request: LinksRequest) -> LinksResult:
    """
    Extract all links from a URL.

    Renders the page and extracts all hyperlinks, optionally filtering
    for document links (PDFs, DOCXs, etc.).

    Use this for link discovery, sitemap generation, or finding downloadable
    documents on a page.
    """
    client = _get_client()

    try:
        result = await client.render_page(
            url=request.url,
            wait_for_selector=request.wait_for_selector,
            timeout_ms=request.timeout_ms,
            extract_documents=request.include_documents,
            document_extensions=request.document_extensions,
        )

        return LinksResult(
            url=request.url,
            final_url=result.final_url,
            links=[link.model_dump() for link in result.links],
            document_links=[doc.model_dump() for doc in result.document_links]
            if request.include_documents
            else [],
            total_links=len(result.links),
            total_document_links=len(result.document_links)
            if request.include_documents
            else 0,
            render_time_ms=result.render_time_ms,
        )

    except PlaywrightError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Link extraction failed: {str(e)}"
        )


@router.get("/status")
async def render_service_status() -> Dict[str, Any]:
    """
    Check Playwright rendering service status.

    Returns the health status and configuration of the Playwright service.
    """
    service_url = settings.playwright_service_url

    if not service_url:
        return {
            "status": "not_configured",
            "message": "Playwright service URL not configured",
            "configured": False,
        }

    client = get_playwright_client()
    if not client:
        return {
            "status": "error",
            "message": "Failed to create Playwright client",
            "configured": True,
            "service_url": service_url,
        }

    try:
        is_healthy = await client.health_check()
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "message": "Playwright service is responding"
            if is_healthy
            else "Playwright service not responding",
            "configured": True,
            "service_url": service_url,
            "timeout": client.timeout,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Health check failed: {str(e)}",
            "configured": True,
            "service_url": service_url,
        }
