"""
Browser Pool Service.

Manages a pool of Playwright browser instances for efficient page rendering.
Handles browser lifecycle, context creation, and resource cleanup.
"""

import asyncio
import logging
from typing import Optional

from playwright.async_api import async_playwright, Browser, Playwright, BrowserContext

from ..config import settings

logger = logging.getLogger("playwright.browser_pool")


class BrowserPool:
    """
    Manages a pool of Chromium browser instances.

    The pool maintains a configurable number of browser instances that can be
    reused across requests. Each render request gets a fresh browser context
    for isolation.
    """

    def __init__(self, pool_size: int = 3, headless: bool = True):
        self.pool_size = pool_size
        self.headless = headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._active_contexts: int = 0
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the browser pool."""
        async with self._lock:
            if self._initialized:
                return

            logger.info(f"Initializing browser pool (size={self.pool_size}, headless={self.headless})")

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-setuid-sandbox",
                    "--no-sandbox",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )

            self._initialized = True
            logger.info("Browser pool initialized successfully")

    async def shutdown(self) -> None:
        """Shutdown the browser pool and release resources."""
        async with self._lock:
            if not self._initialized:
                return

            logger.info("Shutting down browser pool")

            if self._browser:
                await self._browser.close()
                self._browser = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            self._initialized = False
            logger.info("Browser pool shut down")

    async def get_context(
        self,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
    ) -> BrowserContext:
        """
        Get a fresh browser context for rendering.

        Each context is isolated and will be closed after use.

        Args:
            viewport_width: Viewport width in pixels
            viewport_height: Viewport height in pixels

        Returns:
            BrowserContext for page rendering
        """
        if not self._initialized:
            await self.initialize()

        context = await self._browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Curatore/2.0",
            java_script_enabled=True,
            ignore_https_errors=True,
        )

        async with self._lock:
            self._active_contexts += 1

        return context

    async def release_context(self, context: BrowserContext) -> None:
        """
        Release a browser context.

        Args:
            context: BrowserContext to close
        """
        try:
            await context.close()
        except Exception as e:
            logger.warning(f"Error closing browser context: {e}")
        finally:
            async with self._lock:
                self._active_contexts = max(0, self._active_contexts - 1)

    @property
    def active_contexts(self) -> int:
        """Number of currently active browser contexts."""
        return self._active_contexts

    @property
    def is_initialized(self) -> bool:
        """Whether the pool is initialized."""
        return self._initialized


# Singleton instance
browser_pool = BrowserPool(
    pool_size=settings.browser_pool_size,
    headless=settings.browser_headless,
)
