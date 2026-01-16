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
    # HIERARCHICAL STORAGE CONFIGURATION
    # =========================================================================
    use_hierarchical_storage: bool = Field(
        default=True, description="Use new hierarchical organization-based file structure"
    )
    temp_dir: str = Field(
        default="/app/files/temp", description="Temporary processing files"
    )
    dedupe_dir: str = Field(
        default="/app/files/dedupe", description="Content-addressable storage for deduplication"
    )

    # =========================================================================
    # FILE RETENTION CONFIGURATION
    # =========================================================================
    file_retention_uploaded_days: int = Field(
        default=7, description="Days to retain uploaded files"
    )
    file_retention_processed_days: int = Field(
        default=30, description="Days to retain processed files"
    )
    file_retention_batch_days: int = Field(
        default=14, description="Days to retain batch files"
    )
    file_retention_temp_hours: int = Field(
        default=24, description="Hours to retain temp files"
    )

    # =========================================================================
    # FILE CLEANUP CONFIGURATION
    # =========================================================================
    file_cleanup_enabled: bool = Field(
        default=True, description="Enable automatic file cleanup"
    )
    file_cleanup_schedule_cron: str = Field(
        default="0 2 * * *", description="Cleanup schedule (daily at 2 AM)"
    )
    file_cleanup_batch_size: int = Field(
        default=1000, description="Files to process per cleanup batch"
    )
    file_cleanup_dry_run: bool = Field(
        default=False, description="Dry run mode for testing cleanup"
    )

    # =========================================================================
    # FILE DEDUPLICATION CONFIGURATION
    # =========================================================================
    file_deduplication_enabled: bool = Field(
        default=True, description="Enable duplicate file detection and storage optimization"
    )
    file_deduplication_strategy: str = Field(
        default="symlink", description="Deduplication strategy: symlink | copy | reference"
    )
    dedupe_hash_algorithm: str = Field(
        default="sha256", description="Hash algorithm for deduplication"
    )
    dedupe_min_file_size: int = Field(
        default=1024, description="Minimum file size (bytes) to deduplicate"
    )

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
    # EMAIL CONFIGURATION
    # =========================================================================
    email_backend: str = Field(
        default="console",
        description="Email backend: console (dev), smtp, sendgrid, ses",
    )
    email_from_address: str = Field(
        default="noreply@curatore.app", description="From email address"
    )
    email_from_name: str = Field(default="Curatore", description="From name")
    frontend_base_url: str = Field(
        default="http://localhost:3000", description="Frontend URL for email links"
    )

    # SMTP Configuration
    smtp_host: Optional[str] = Field(default=None, description="SMTP server host")
    smtp_port: int = Field(default=587, description="SMTP server port")
    smtp_username: Optional[str] = Field(default=None, description="SMTP username")
    smtp_password: Optional[str] = Field(default=None, description="SMTP password")
    smtp_use_tls: bool = Field(default=True, description="Use TLS for SMTP")

    # SendGrid Configuration
    sendgrid_api_key: Optional[str] = Field(
        default=None, description="SendGrid API key"
    )

    # AWS SES Configuration
    aws_region: str = Field(default="us-east-1", description="AWS region for SES")
    aws_access_key_id: Optional[str] = Field(
        default=None, description="AWS access key ID"
    )
    aws_secret_access_key: Optional[str] = Field(
        default=None, description="AWS secret access key"
    )

    # Token Expiration
    email_verification_token_expire_hours: int = Field(
        default=24, description="Email verification token expiration in hours"
    )
    password_reset_token_expire_hours: int = Field(
        default=1, description="Password reset token expiration in hours"
    )
    email_verification_grace_period_days: int = Field(
        default=7, description="Days before enforcing email verification"
    )

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
    # JOB MANAGEMENT CONFIGURATION
    # =========================================================================
    default_job_concurrency_limit: int = Field(
        default=3, description="Default concurrent jobs per organization"
    )
    default_job_retention_days: int = Field(
        default=30, description="Default job retention in days before auto-cleanup"
    )
    job_cleanup_enabled: bool = Field(
        default=True, description="Enable automatic job cleanup"
    )
    job_cleanup_schedule_cron: str = Field(
        default="0 3 * * *", description="Job cleanup schedule (daily at 3 AM)"
    )
    job_cancellation_timeout: int = Field(
        default=30, description="Timeout (s) for job cancellation verification"
    )
    job_status_poll_interval: int = Field(
        default=2, description="Frontend polling interval (s) for job status updates"
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

    @property
    def temp_path(self) -> Path:
        return Path(self.temp_dir)

    @property
    def dedupe_path(self) -> Path:
        return Path(self.dedupe_dir)


# Global settings instance (imported elsewhere)
settings = Settings()
