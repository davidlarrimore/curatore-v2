"""
Pydantic models for YAML configuration validation.

This module defines the schema for config.yml, providing type-safe configuration
with validation and sensible defaults.

Usage:
    from app.core.models.config_models import AppConfig
    config = AppConfig.from_yaml("config.yml")
"""

import os
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, validator


class LLMTaskTypeConfig(BaseModel):
    """
    Configuration for a specific LLM task type.

    Task types allow different models to be used for different purposes:
    - embedding: Vector representations for semantic search
    - quick: Fast, simple decisions (classify, decide, route)
    - standard: Balanced quality/cost (summarize, extract, generate)
    - quality: High-stakes outputs (evaluate, final reports)
    - bulk: High-volume batch processing (map phase of chunked processing)
    - reasoning: Complex multi-step analysis (procedure generation)

    Uses the parent LLM connection settings (api_key, base_url, provider).
    """
    model_config = ConfigDict(extra='forbid')

    model: str = Field(
        description="Model identifier (e.g., claude-4-5-haiku, claude-4-5-sonnet)"
    )
    temperature: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Generation temperature (inherits from parent if not set)"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        ge=1,
        le=128000,
        description="Maximum tokens to generate"
    )
    timeout: Optional[int] = Field(
        default=None,
        ge=1,
        le=600,
        description="Request timeout in seconds (overrides parent)"
    )
    dimensions: Optional[int] = Field(
        default=None,
        ge=1,
        le=4096,
        description="Embedding output dimensions (only applies to embedding task type). "
                    "If not set, uses model's native dimensions from EMBEDDING_DIMENSIONS lookup."
    )


class LLMConfig(BaseModel):
    """
    LLM service configuration with task-type-based model routing.

    Supports OpenAI, Ollama, OpenWebUI, LM Studio, and compatible endpoints.

    Task Type Routing:
    Each task type can use a different model optimized for its specific needs:
    - embedding: Vector representations for semantic search
    - quick: Fast, simple decisions (classify, decide, route)
    - standard: Balanced quality/cost (summarize, extract, generate)
    - quality: High-stakes outputs (evaluate, final reports)
    - bulk: High-volume batch processing (map phase of chunked processing)
    - reasoning: Complex multi-step analysis (procedure generation)

    Resolution Priority:
    1. Procedure YAML override (model param in step)
    2. Organization settings (database)
    3. Task type config (below)
    4. Default model (fallback)
    """
    model_config = ConfigDict(extra='forbid')

    provider: Literal["openai", "ollama", "openwebui", "lmstudio"] = Field(
        description="LLM provider name"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key or authentication token"
    )
    base_url: str = Field(
        description="API endpoint URL"
    )
    default_model: str = Field(
        description="Default model identifier used when task type not configured"
    )
    timeout: int = Field(
        default=60,
        ge=1,
        le=600,
        description="Request timeout in seconds"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts"
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates"
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Provider-specific options"
    )
    task_types: Optional[Dict[str, LLMTaskTypeConfig]] = Field(
        default=None,
        description="Task-type-specific model configuration (embedding, quick, standard, quality, bulk, reasoning)"
    )


class OCRConfig(BaseModel):
    """
    OCR configuration (Tesseract-specific for document-service).

    These settings are specific to the document-service implementation
    that uses Tesseract OCR for image-based PDFs and scanned documents.
    """
    model_config = ConfigDict(extra='forbid')

    language: str = Field(
        default="eng",
        description="Tesseract OCR language code (e.g., eng, spa, fra, or 'eng+spa')"
    )
    psm: int = Field(
        default=3,
        ge=0,
        le=13,
        description="Page Segmentation Mode (0-13, 3=auto recommended)"
    )


class ExtractionEngineConfig(BaseModel):
    """Configuration for a single extraction engine."""
    model_config = ConfigDict(extra='forbid')

    name: str = Field(
        description="Engine identifier (unique name for this engine instance)"
    )
    display_name: str = Field(
        description="Human-readable name shown in UI"
    )
    description: str = Field(
        description="Description of this engine and its use cases"
    )
    engine_type: Literal["document-service", "extraction-service", "docling", "tika"] = Field(
        description="Engine type identifier (determines extraction logic)"
    )
    service_url: str = Field(
        description="Base URL for the document service"
    )
    timeout: int = Field(
        default=300,
        ge=1,
        le=3600,
        description="Request timeout in seconds"
    )
    enabled: bool = Field(
        default=True,
        description="Enable/disable this engine"
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key for authentication"
    )
    docling_ocr_enabled: Optional[bool] = Field(
        default=None,
        description="Enable OCR for Docling engines (maps to enable_ocr)"
    )
    ocr: Optional[OCRConfig] = Field(
        default=None,
        description="OCR settings (specific to document-service implementation)"
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Engine-specific options (e.g., Docling conversion settings)"
    )


class ExtractionConfig(BaseModel):
    """Document extraction engine configuration."""
    model_config = ConfigDict(extra='forbid')

    default_engine: str = Field(
        default="docling-external",
        description="Default engine to use when none specified"
    )
    engines: List[ExtractionEngineConfig] = Field(
        description="List of available extraction engines"
    )

    @validator('engines')
    def validate_engines(cls, v):
        """Ensure at least one enabled engine is configured."""
        if not v:
            raise ValueError("At least one extraction engine must be configured")

        enabled_engines = [e for e in v if e.enabled]
        if not enabled_engines:
            raise ValueError("At least one extraction engine must be enabled")

        # Ensure engine names are unique
        names = [e.name for e in v]
        if len(names) != len(set(names)):
            raise ValueError("Extraction engine names must be unique")

        return v

    @validator('default_engine')
    def validate_default_engine(cls, v, values):
        """Ensure default_engine matches an enabled engine."""
        if 'engines' in values:
            engine_names = [e.name for e in values['engines'] if e.enabled]
            if v not in engine_names:
                raise ValueError(
                    f"default_engine '{v}' must match an enabled engine name"
                )
        return v


class MicrosoftGraphConfig(BaseModel):
    """
    Microsoft Graph API configuration.

    Uses Azure AD app-only authentication (client credentials flow).
    Supports SharePoint, OneDrive, and other Microsoft 365 services.
    """
    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(
        default=True,
        description="Enable Microsoft Graph integration"
    )
    tenant_id: str = Field(
        description="Azure AD tenant ID (GUID)"
    )
    client_id: str = Field(
        description="App registration client ID"
    )
    client_secret: str = Field(
        description="App registration client secret"
    )
    graph_scope: str = Field(
        default="https://graph.microsoft.com/.default",
        description="OAuth scope for Microsoft Graph"
    )
    graph_base_url: str = Field(
        default="https://graph.microsoft.com/v1.0",
        description="Microsoft Graph API base URL"
    )
    timeout: int = Field(
        default=60,
        ge=1,
        le=300,
        description="Request timeout in seconds"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts"
    )
    enable_email: bool = Field(
        default=False,
        description="Enable email sending via Microsoft Graph API. Requires Mail.Send permission."
    )
    email_sender_user_id: Optional[str] = Field(
        default=None,
        description="User ID or UPN for sending emails (e.g., noreply@domain.com). Required when enable_email is True."
    )


class SMTPConfig(BaseModel):
    """SMTP server configuration for email delivery."""
    model_config = ConfigDict(extra='forbid')

    host: str = Field(
        description="SMTP server hostname"
    )
    port: int = Field(
        default=587,
        ge=1,
        le=65535,
        description="SMTP server port"
    )
    username: Optional[str] = Field(
        default=None,
        description="SMTP authentication username"
    )
    password: Optional[str] = Field(
        default=None,
        description="SMTP authentication password"
    )
    use_tls: bool = Field(
        default=True,
        description="Use TLS encryption"
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Connection timeout in seconds"
    )


class SendGridConfig(BaseModel):
    """SendGrid API configuration."""
    model_config = ConfigDict(extra='forbid')

    api_key: str = Field(
        description="SendGrid API key"
    )


class AWSConfig(BaseModel):
    """AWS SES configuration."""
    model_config = ConfigDict(extra='forbid')

    region: str = Field(
        default="us-east-1",
        description="AWS region"
    )
    access_key_id: Optional[str] = Field(
        default=None,
        description="AWS access key ID (optional, uses IAM role if not provided)"
    )
    secret_access_key: Optional[str] = Field(
        default=None,
        description="AWS secret access key (optional, uses IAM role if not provided)"
    )


class EmailConfig(BaseModel):
    """
    Email service configuration.

    Supports console (dev), SMTP, SendGrid, AWS SES, and Microsoft Graph backends.
    """
    model_config = ConfigDict(extra='forbid')

    backend: Literal["console", "smtp", "sendgrid", "ses", "microsoft_graph"] = Field(
        description="Email backend to use"
    )
    from_address: str = Field(
        description="From email address"
    )
    from_name: str = Field(
        description="From display name"
    )
    smtp: Optional[SMTPConfig] = Field(
        default=None,
        description="SMTP configuration (required if backend=smtp)"
    )
    sendgrid: Optional[SendGridConfig] = Field(
        default=None,
        description="SendGrid configuration (required if backend=sendgrid)"
    )
    aws_ses: Optional[AWSConfig] = Field(
        default=None,
        description="AWS SES configuration (required if backend=ses)"
    )

    @validator('smtp')
    def validate_smtp(cls, v, values):
        """Ensure SMTP config is provided when backend is smtp."""
        if values.get('backend') == 'smtp' and v is None:
            raise ValueError("SMTP configuration required when backend=smtp")
        return v

    @validator('sendgrid')
    def validate_sendgrid(cls, v, values):
        """Ensure SendGrid config is provided when backend is sendgrid."""
        if values.get('backend') == 'sendgrid' and v is None:
            raise ValueError("SendGrid configuration required when backend=sendgrid")
        return v

    @validator('aws_ses')
    def validate_aws_ses(cls, v, values):
        """Ensure AWS SES config is provided when backend is ses."""
        if values.get('backend') == 'ses' and v is None:
            raise ValueError("AWS SES configuration required when backend=ses")
        return v


class QueueTypeOverride(BaseModel):
    """
    Runtime parameter overrides for a specific queue type.

    These override the defaults defined in queue_registry.py.
    """
    model_config = ConfigDict(extra='forbid')

    max_concurrent: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum concurrent jobs for this queue (null = unlimited)"
    )
    timeout_seconds: Optional[int] = Field(
        default=None,
        ge=1,
        description="Job timeout in seconds"
    )
    submission_interval: Optional[int] = Field(
        default=None,
        ge=1,
        description="Seconds between queue processing checks"
    )
    duplicate_cooldown: Optional[int] = Field(
        default=None,
        ge=1,
        description="Seconds before allowing duplicate job"
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="Enable/disable this queue type"
    )


class QueueConfig(BaseModel):
    """Celery queue configuration."""
    model_config = ConfigDict(extra='forbid')

    broker_url: str = Field(
        default="redis://redis:6379/0",
        description="Redis URL for task queue broker"
    )
    result_backend: str = Field(
        default="redis://redis:6379/1",
        description="Redis URL for storing task results"
    )
    default_queue: str = Field(
        default="extraction",
        description="Default queue name for tasks"
    )
    worker_concurrency: int = Field(
        default=4,
        ge=1,
        description="Worker concurrency level"
    )
    task_timeout: int = Field(
        default=3600,
        ge=1,
        description="Task timeout in seconds"
    )
    extraction_max_concurrent: int = Field(
        default=10,
        ge=1,
        description="Maximum concurrent extractions submitted to Celery at once"
    )


class PlaywrightConfig(BaseModel):
    """
    Playwright rendering service configuration.

    Browser-based rendering for JavaScript-heavy web scraping.
    """
    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(
        default=True,
        description="Enable Playwright rendering service"
    )
    service_url: str = Field(
        description="Playwright service URL (e.g., http://playwright:8011)"
    )
    timeout: int = Field(
        default=60,
        ge=1,
        le=600,
        description="Request timeout in seconds"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts"
    )
    browser_pool_size: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Number of browser instances to maintain"
    )
    default_viewport_width: int = Field(
        default=1920,
        ge=320,
        le=3840,
        description="Default browser viewport width"
    )
    default_viewport_height: int = Field(
        default=1080,
        ge=240,
        le=2160,
        description="Default browser viewport height"
    )
    default_timeout_ms: int = Field(
        default=60000,
        ge=1000,
        le=300000,
        description="Default page load timeout in milliseconds"
    )
    default_wait_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Default wait for selector timeout in milliseconds"
    )
    document_extensions: List[str] = Field(
        default=[".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"],
        description="File extensions to identify as downloadable documents"
    )


class SamConfig(BaseModel):
    """
    SAM.gov Opportunities API configuration.

    Enables integration with SAM.gov for federal contract opportunity
    data ingestion and analysis.
    """
    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(
        default=True,
        description="Enable SAM.gov integration"
    )
    api_key: str = Field(
        description="SAM.gov API key from api.sam.gov"
    )
    # Note: base_url is intentionally not configurable - SAM.gov API has a fixed endpoint
    # that is hardcoded in sam_pull_service.py
    timeout: int = Field(
        default=60,
        ge=1,
        le=600,
        description="Request timeout in seconds"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts"
    )
    rate_limit_delay: float = Field(
        default=0.5,
        ge=0,
        le=10,
        description="Delay between requests in seconds for rate limiting"
    )
    max_pages_per_pull: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum pages to fetch per pull operation"
    )
    page_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of results per page"
    )


class SearchConfig(BaseModel):
    """
    Search configuration for PostgreSQL + pgvector hybrid search.

    Provides full-text search combined with semantic vector search across all
    indexed content (uploads, SharePoint, web scrapes, SAM.gov). Documents are
    automatically indexed after extraction.

    Note: The embedding model is configured in llm.models.embedding, not here.
    """
    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(
        default=True,
        description="Enable full-text and semantic search"
    )
    default_mode: str = Field(
        default="hybrid",
        description="Default search mode: keyword, semantic, or hybrid"
    )
    semantic_weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight for semantic scores in hybrid search (0=keyword only, 1=semantic only)"
    )
    batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Batch size for bulk indexing operations"
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Request timeout in seconds"
    )
    max_content_length: int = Field(
        default=100000,
        ge=1000,
        le=1000000,
        description="Maximum content length to index (characters, longer content is truncated)"
    )
    chunk_size: int = Field(
        default=1500,
        ge=500,
        le=5000,
        description="Maximum characters per chunk for indexing"
    )
    chunk_overlap: int = Field(
        default=200,
        ge=0,
        le=500,
        description="Character overlap between consecutive chunks"
    )


class MinIOConfig(BaseModel):
    """
    MinIO/S3 object storage configuration.

    Backend connects directly to MinIO or S3 for object storage operations.
    All file operations are now proxied through the backend API, eliminating
    the need for presigned URLs and environment-specific endpoint configuration.
    """
    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(
        default=False,
        description="Enable object storage (MinIO/S3)"
    )
    endpoint: str = Field(
        default="minio:9000",
        description="MinIO/S3 server endpoint for backend connections (host:port)"
    )
    presigned_endpoint: Optional[str] = Field(
        default=None,
        description="DEPRECATED: No longer needed with proxy architecture. Endpoint used to generate presigned URLs."
    )
    public_endpoint: Optional[str] = Field(
        default=None,
        description="DEPRECATED: No longer needed with proxy architecture. Public endpoint for presigned URLs."
    )
    access_key: str = Field(
        description="MinIO access key / AWS Access Key ID"
    )
    secret_key: str = Field(
        description="MinIO secret key / AWS Secret Access Key"
    )
    secure: bool = Field(
        default=False,
        description="Use HTTPS for internal MinIO/S3 connections"
    )
    public_secure: Optional[bool] = Field(
        default=None,
        description="DEPRECATED: No longer needed with proxy architecture. Use HTTPS for presigned URLs."
    )
    bucket_uploads: str = Field(
        default="curatore-uploads",
        description="Bucket for uploaded files"
    )
    bucket_processed: str = Field(
        default="curatore-processed",
        description="Bucket for processed files"
    )
    bucket_temp: str = Field(
        default="curatore-temp",
        description="Bucket for temporary files"
    )
    presigned_expiry: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="DEPRECATED: No longer needed with proxy architecture. Presigned URL expiry in seconds."
    )


class AppConfig(BaseModel):
    """
    Root application configuration.

    This is the top-level configuration object that contains all service configs.
    """
    model_config = ConfigDict(extra='forbid')

    version: str = Field(
        default="2.0",
        description="Configuration file version"
    )
    llm: Optional[LLMConfig] = Field(
        default=None,
        description="LLM service configuration"
    )
    extraction: Optional[ExtractionConfig] = Field(
        default=None,
        description="Extraction service configuration"
    )
    playwright: Optional[PlaywrightConfig] = Field(
        default=None,
        description="Playwright rendering service configuration"
    )
    microsoft_graph: Optional[MicrosoftGraphConfig] = Field(
        default=None,
        description="Microsoft Graph API configuration"
    )
    email: Optional[EmailConfig] = Field(
        default=None,
        description="Email service configuration"
    )
    queue: QueueConfig = Field(
        default_factory=QueueConfig,
        description="Queue configuration"
    )
    queues: Optional[Dict[str, QueueTypeOverride]] = Field(
        default=None,
        description="Per-queue-type parameter overrides (extraction, enhancement, sam, etc.)"
    )
    minio: Optional[MinIOConfig] = Field(
        default=None,
        description="MinIO/S3 object storage configuration"
    )
    search: Optional[SearchConfig] = Field(
        default=None,
        description="PostgreSQL + pgvector search configuration"
    )
    sam: Optional[SamConfig] = Field(
        default=None,
        description="SAM.gov Opportunities API configuration"
    )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "AppConfig":
        """
        Load and parse configuration from YAML file.

        Args:
            yaml_path: Path to config.yml file

        Returns:
            Validated AppConfig instance

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If YAML is invalid or validation fails
        """
        import yaml

        if not os.path.exists(yaml_path):
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

        with open(yaml_path, 'r') as f:
            raw_config = yaml.safe_load(f)

        # Resolve environment variable references
        resolved_config = cls._resolve_env_vars(raw_config)

        # Validate and return
        return cls(**resolved_config)

    @classmethod
    def _resolve_env_vars(cls, obj: Any) -> Any:
        """
        Recursively resolve ${ENV_VAR} references in configuration.

        Args:
            obj: Configuration object (dict, list, str, etc.)

        Returns:
            Configuration with environment variables resolved
        """
        if isinstance(obj, dict):
            return {k: cls._resolve_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [cls._resolve_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            # Replace ${VAR_NAME} with environment variable value
            # Supports ${VAR_NAME} or ${VAR_NAME:-default} syntax
            if obj.startswith("${") and obj.endswith("}"):
                inner = obj[2:-1]
                # Check for default value syntax: ${VAR_NAME:-default}
                if ":-" in inner:
                    var_name, default_value = inner.split(":-", 1)
                    return os.getenv(var_name, default_value)
                else:
                    var_name = inner
                    value = os.getenv(var_name)
                    # Return None instead of raising for optional env vars
                    # This allows partial configs to still load
                    return value
            return obj
        else:
            return obj
