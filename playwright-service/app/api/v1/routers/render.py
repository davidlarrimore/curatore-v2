"""
Render Router - Page rendering endpoint.
"""

import logging

from fastapi import APIRouter, HTTPException

from ....models import RenderRequest, RenderResponse
from ....services.renderer import render_page, RenderError

logger = logging.getLogger("playwright.api.render")

router = APIRouter(tags=["render"])


@router.post("/render", response_model=RenderResponse)
async def render_url(request: RenderRequest) -> RenderResponse:
    """
    Render a URL using Playwright and extract content.

    This endpoint:
    1. Launches a browser context
    2. Navigates to the URL and waits for JavaScript execution
    3. Extracts content (HTML, markdown, links, document links)
    4. Returns structured response

    Args:
        request: RenderRequest with URL and rendering options

    Returns:
        RenderResponse with extracted content and metadata
    """
    try:
        result = await render_page(request)
        return result

    except RenderError as e:
        logger.warning(f"Render error for {request.url}: {e}")
        raise HTTPException(status_code=e.status_code, detail=str(e))

    except Exception as e:
        logger.exception(f"Unexpected error rendering {request.url}")
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
