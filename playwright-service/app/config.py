"""
Playwright Service Configuration.

Environment-driven settings for the Playwright rendering microservice.
"""

import json
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # =========================================================================
    # API SETTINGS
    # =========================================================================
    api_title: str = "Playwright Rendering Service"
    api_version: str = "1.0.0"
    debug: bool = Field(default=False, description="Enable verbose logging")

    # =========================================================================
    # CORS SETTINGS
    # =========================================================================
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="Allowed origins for CORS",
    )
    cors_credentials: bool = True
    cors_methods: List[str] = ["*"]
    cors_headers: List[str] = ["*"]

    # =========================================================================
    # BROWSER POOL SETTINGS
    # =========================================================================
    browser_pool_size: int = Field(
        default=3,
        description="Number of browser instances to maintain in the pool",
    )
    browser_headless: bool = Field(
        default=True,
        description="Run browsers in headless mode",
    )

    # =========================================================================
    # RENDERING DEFAULTS
    # =========================================================================
    default_viewport_width: int = Field(default=1920, description="Default viewport width")
    default_viewport_height: int = Field(default=1080, description="Default viewport height")
    default_timeout_ms: int = Field(default=30000, description="Default page load timeout in ms")
    default_wait_timeout_ms: int = Field(default=5000, description="Default wait for selector timeout")

    # =========================================================================
    # CONTENT EXTRACTION
    # =========================================================================
    default_document_extensions: List[str] = Field(
        default=[".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"],
        description="File extensions to identify as downloadable documents",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
