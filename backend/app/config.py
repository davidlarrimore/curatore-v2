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
- Object storage (MinIO/S3) configuration
- Quality assessment thresholds

Environment Variables:
    See .env.example for a complete list of available settings.

Usage:
    from app.config import settings
    use_object_storage = settings.use_object_storage  # Always True (required)
"""

from pathlib import Path
from typing import List, Optional

from pydantic import Field
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
    # FILE UPLOAD LIMITS
    # =========================================================================
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

    # Docling-specific configuration
    docling_service_url: Optional[str] = Field(default=None, description="Base URL for Docling service")
    docling_timeout: float = Field(default=60.0, description="Timeout (s) for Docling requests")
    docling_verify_ssl: bool = Field(default=True, description="Verify SSL for Docling service calls")

    # Tika-specific configuration
    tika_service_url: Optional[str] = Field(default=None, description="Base URL for Apache Tika service")
    tika_timeout: float = Field(default=300.0, description="Timeout (s) for Tika requests")
    tika_verify_ssl: bool = Field(default=True, description="Verify SSL for Tika service calls")
    tika_accept_format: str = Field(default="markdown", description="Tika output format: markdown, html, text")
    tika_extract_metadata: bool = Field(default=True, description="Extract document metadata via Tika /meta endpoint")
    tika_ocr_language: str = Field(default="eng", description="OCR language for Tika (Tesseract language code)")

    # Playwright rendering service (for JavaScript-rendered web scraping)
    playwright_service_url: Optional[str] = Field(default=None, description="Base URL for Playwright rendering service")
    playwright_timeout: float = Field(default=60.0, description="Timeout (s) for Playwright requests")

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

    # =========================================================================
    # OBJECT STORAGE CONFIGURATION (MinIO / S3)
    # =========================================================================
    # When USE_OBJECT_STORAGE=true, the backend connects directly to MinIO/S3
    # for object storage operations (no separate microservice needed).
    use_object_storage: bool = Field(
        default=True, description="Use MinIO/S3 for object storage (REQUIRED - no filesystem fallback)"
    )

    # MinIO Connection Settings
    minio_endpoint: str = Field(
        default="minio:9000", description="MinIO server endpoint (host:port) for internal operations"
    )
    minio_public_endpoint: str = Field(
        default="", description="Public endpoint for presigned URLs (must be reachable from clients)"
    )
    minio_presigned_endpoint: str = Field(
        default="", description="Endpoint used to generate presigned URLs (must be reachable from backend)"
    )
    minio_access_key: str = Field(
        default="minioadmin", description="MinIO access key"
    )
    minio_secret_key: str = Field(
        default="minioadmin", description="MinIO secret key"
    )
    minio_secure: bool = Field(
        default=False, description="Use HTTPS for MinIO connections"
    )
    minio_public_secure: bool = Field(
        default=False, description="Use HTTPS for presigned URLs"
    )

    # Bucket Configuration
    minio_bucket_uploads: str = Field(
        default="curatore-uploads", description="Bucket for uploaded files"
    )
    minio_bucket_processed: str = Field(
        default="curatore-processed", description="Bucket for processed files"
    )
    minio_bucket_temp: str = Field(
        default="curatore-temp", description="Bucket for temporary files"
    )

    # Bucket Display Names (for UI)
    minio_bucket_uploads_display_name: str = Field(
        default="Default Storage", description="Display name for uploads bucket"
    )
    minio_bucket_processed_display_name: str = Field(
        default="Processed Files", description="Display name for processed bucket"
    )
    minio_bucket_temp_display_name: str = Field(
        default="Temporary Files", description="Display name for temp bucket"
    )

    # Presigned URL Configuration
    minio_presigned_expiry: int = Field(
        default=3600, description="Presigned URL expiry in seconds (1 hour)"
    )

    # Object Storage Retention Configuration
    file_retention_uploaded_days: int = Field(
        default=30, description="Retention period for uploaded files in object storage (days)"
    )
    file_retention_processed_days: int = Field(
        default=90, description="Retention period for processed files in object storage (days)"
    )
    file_retention_temp_days: int = Field(
        default=7, description="Retention period for temporary files in object storage (days)"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"



# Global settings instance (imported elsewhere)
settings = Settings()
