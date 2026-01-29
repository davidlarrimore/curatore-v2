"""
Page Renderer Service.

Handles page navigation, JavaScript execution waiting, and content capture
using Playwright browser contexts.
"""

import logging
import time
from typing import List, Optional

from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeout

from ..models import RenderRequest, RenderResponse, LinkInfo, DocumentLink
from .browser_pool import browser_pool
from .extractor import extract_content

logger = logging.getLogger("playwright.renderer")


class RenderError(Exception):
    """Raised when page rendering fails."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


async def render_page(request: RenderRequest) -> RenderResponse:
    """
    Render a page using Playwright and extract content.

    This function:
    1. Creates a browser context
    2. Navigates to the URL
    3. Waits for JavaScript execution
    4. Extracts content (HTML, markdown, links)
    5. Returns structured response

    Args:
        request: RenderRequest with URL and options

    Returns:
        RenderResponse with extracted content

    Raises:
        RenderError: If rendering fails
    """
    start_time = time.time()
    context: Optional[BrowserContext] = None

    try:
        # Get browser context
        context = await browser_pool.get_context(
            viewport_width=request.viewport_width,
            viewport_height=request.viewport_height,
        )

        # Create page
        page: Page = await context.new_page()

        # Navigate to URL
        logger.info(f"Navigating to {request.url}")

        try:
            response = await page.goto(
                request.url,
                timeout=request.timeout_ms,
                wait_until="networkidle",
            )
        except PlaywrightTimeout:
            raise RenderError(
                f"Page load timeout after {request.timeout_ms}ms: {request.url}",
                status_code=504,
            )

        if response is None:
            raise RenderError(f"Failed to get response from {request.url}", status_code=502)

        status_code = response.status

        # Check for error status codes
        if status_code >= 400:
            raise RenderError(f"HTTP {status_code} for {request.url}", status_code=status_code)

        # Wait for optional selector
        if request.wait_for_selector:
            logger.debug(f"Waiting for selector: {request.wait_for_selector}")
            try:
                await page.wait_for_selector(
                    request.wait_for_selector,
                    timeout=request.wait_timeout_ms,
                )
            except PlaywrightTimeout:
                logger.warning(
                    f"Selector '{request.wait_for_selector}' not found within "
                    f"{request.wait_timeout_ms}ms, continuing anyway"
                )

        # Additional wait for any lazy-loaded content
        await page.wait_for_load_state("domcontentloaded")

        # Small delay for any final JavaScript execution
        await page.wait_for_timeout(500)

        # Get final URL (after redirects)
        final_url = page.url

        # Get rendered HTML
        html = await page.content()

        # Extract content
        markdown, text, title, links, document_links = extract_content(
            html=html,
            base_url=final_url,
            document_extensions=request.document_extensions,
        )

        # Filter document links if extraction disabled
        if not request.extract_documents:
            document_links = []

        # Calculate render time
        render_time_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"Rendered {request.url} in {render_time_ms}ms: "
            f"{len(links)} links, {len(document_links)} documents"
        )

        return RenderResponse(
            html=html,
            markdown=markdown,
            text=text,
            title=title,
            links=links,
            document_links=document_links,
            final_url=final_url,
            status_code=status_code,
            render_time_ms=render_time_ms,
        )

    except RenderError:
        raise
    except PlaywrightTimeout as e:
        raise RenderError(f"Timeout rendering {request.url}: {e}", status_code=504)
    except Exception as e:
        logger.exception(f"Error rendering {request.url}")
        raise RenderError(f"Failed to render {request.url}: {e}", status_code=500)

    finally:
        if context:
            await browser_pool.release_context(context)
