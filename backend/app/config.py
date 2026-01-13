# ============================================================================
# Curatore v2 - Application Configuration
# ============================================================================
"""
Application configuration module using Pydantic Settings.

This module defines all configuration parameters for the Curatore v2 application,
including:
- API/CORS settings
- OpenAI/LLM configuration
- OCR settings
- File storage paths and limits
- Quality assessment thresholds

Environment Variables:
    See .env.example for a complete list of available settings.

Usage:
    from app.config import settings
    files_root = settings.files_root_path
"""

from pathlib import Path
from typing import List, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # =========================================================================
    # API SETTINGS
    # =========================================================================
    api_title: str = "Curatore API"
    api_version: str = "2.0.0"
    debug: bool = Field(default=False, description="Enable verbose logging & dev helpers")

    # =========================================================================
    # CORS SETTINGS
    # =========================================================================
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed origins for CORS",
    )
    cors_origin_regex: Optional[str] = Field(
        default=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
        description="Optional regex to match allowed origins",
    )

    # =========================================================================
    # OPENAI/LLM CONFIGURATION
    # =========================================================================
    openai_api_key: Optional[str] = Field(default=None, description="LLM API key")
    openai_model: str = Field(default="gpt-4o-mini", description="LLM model name")
    openai_base_url: str = Field(default="https://api.openai.com/v1", description="LLM base URL")
    openai_verify_ssl: bool = Field(default=True, description="Verify SSL for LLM requests")
    openai_timeout: float = Field(default=60.0, description="Timeout (s) for LLM requests")
    openai_max_retries: int = Field(default=3, description="Retry count for LLM requests")

    # =========================================================================
    # OCR CONFIGURATION
    # =========================================================================
    ocr_lang: str = Field(default="eng", description="Language code for Tesseract OCR")
    ocr_psm: int = Field(default=3, description="Page Segmentation Mode for Tesseract")

    # =========================================================================
    # FILE STORAGE CONFIGURATION (CANONICAL)
    # =========================================================================
    # IMPORTANT: These defaults are ABSOLUTE paths inside containers
    # and are supplied by a host bind-mount of ./files -> /app/files.
    files_root: str = Field(default="/app/files", description="Root directory for file storage")
    upload_dir: str = Field(default="/app/files/uploaded_files", description="User uploads")
    processed_dir: str = Field(default="/app/files/processed_files", description="Processed markdown output")
    batch_dir: str = Field(default="/app/files/batch_files", description="Operator-provided test/bulk inputs")
    max_file_size: int = Field(default=50 * 1024 * 1024, description="Max upload size in bytes")

    # =========================================================================
    # EXTRACTION SERVICE (optional external microservice)
    # =========================================================================
    # If provided, backend will POST files to this service for text/markdown extraction.
    # Example: http://localhost:8010
    extraction_service_url: Optional[str] = Field(default=None, description="Base URL for extraction service")
    extraction_service_timeout: float = Field(default=60.0, description="Timeout (s) for extraction requests")
    extraction_service_api_key: Optional[str] = Field(default=None, description="Bearer token for extraction service")
    extraction_service_verify_ssl: bool = Field(default=True, description="Verify SSL for extraction service calls")

    # =========================================================================
    # EXTRACTION PRIORITY (default | docling | none)
    # =========================================================================
    extraction_priority: str = Field(
        default="default",
        description="Which extractor to prioritize: default | docling | none",
        validation_alias=AliasChoices("EXTRACTION_PRIORITY", "CONTENT_EXTRACTOR"),
    )

    # Docling-specific configuration
    docling_service_url: Optional[str] = Field(default=None, description="Base URL for Docling service")
    docling_timeout: float = Field(default=60.0, description="Timeout (s) for Docling requests")
    docling_verify_ssl: bool = Field(default=True, description="Verify SSL for Docling service calls")

    # =========================================================================
    # QUALITY ASSESSMENT DEFAULTS
    # =========================================================================
    default_conversion_threshold: int = Field(default=70, description="0–100")
    default_clarity_threshold: int = Field(default=7, description="1–10")
    default_completeness_threshold: int = Field(default=7, description="1–10")
    default_relevance_threshold: int = Field(default=7, description="1–10")
    default_markdown_threshold: int = Field(default=7, description="1–10")

    # =========================================================================
    # DATABASE CONFIGURATION
    # =========================================================================
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/curatore.db",
        description="Database URL for SQLAlchemy (SQLite or PostgreSQL)",
    )
    db_pool_size: int = Field(default=20, description="Database connection pool size (PostgreSQL)")
    db_max_overflow: int = Field(default=40, description="Max overflow connections (PostgreSQL)")
    db_pool_recycle: int = Field(default=3600, description="Connection recycle time in seconds")

    # =========================================================================
    # AUTHENTICATION & SECURITY
    # =========================================================================
    jwt_secret_key: str = Field(
        default="your-secret-key-change-in-production",
        description="JWT secret key (use openssl rand -hex 32)",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    jwt_access_token_expire_minutes: int = Field(
        default=60, description="JWT access token expiration in minutes"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=30, description="JWT refresh token expiration in days"
    )
    bcrypt_rounds: int = Field(default=12, description="Bcrypt hashing work factor")
    api_key_prefix: str = Field(default="cur_", description="API key prefix")

    # =========================================================================
    # MULTI-TENANCY & ORGANIZATIONS
    # =========================================================================
    enable_auth: bool = Field(
        default=False, description="Enable authentication (set to false for backward compatibility)"
    )
    default_org_id: Optional[str] = Field(
        default=None, description="Default organization ID for unauthenticated requests"
    )
    auto_test_connections: bool = Field(
        default=True, description="Automatically test connections on create/update"
    )

    # =========================================================================
    # INITIAL SEEDING (for first-time setup)
    # =========================================================================
    admin_email: str = Field(default="admin@example.com", description="Initial admin email")
    admin_username: str = Field(default="admin", description="Initial admin username")
    admin_password: str = Field(default="changeme", description="Initial admin password")
    admin_full_name: str = Field(default="Admin User", description="Initial admin full name")
    default_org_name: str = Field(
        default="Default Organization", description="Default organization name"
    )
    default_org_slug: str = Field(default="default", description="Default organization slug")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"

    # -------- Path helpers (preferred by services) --------
    @property
    def files_root_path(self) -> Path:
        return Path(self.files_root)

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)

    @property
    def processed_path(self) -> Path:
        return Path(self.processed_dir)

    @property
    def batch_path(self) -> Path:
        return Path(self.batch_dir)


# Global settings instance (imported elsewhere)
settings = Settings()
