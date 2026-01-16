"""
Pydantic models for YAML configuration validation.

This module defines the schema for config.yml, providing type-safe configuration
with validation and sensible defaults.

Usage:
    from app.models.config_models import AppConfig
    config = AppConfig.from_yaml("config.yml")
"""

from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field, validator, ConfigDict
import os


class LLMConfig(BaseModel):
    """
    LLM service configuration.

    Supports OpenAI, Ollama, OpenWebUI, LM Studio, and compatible endpoints.
    """
    model_config = ConfigDict(extra='forbid')

    provider: Literal["openai", "ollama", "openwebui", "lmstudio"] = Field(
        description="LLM provider name"
    )
    api_key: str = Field(
        description="API key or authentication token"
    )
    base_url: str = Field(
        description="API endpoint URL"
    )
    model: str = Field(
        description="Model identifier (e.g., gpt-4o-mini, llama2)"
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
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Generation temperature"
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates"
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Provider-specific options"
    )


class ExtractionServiceConfig(BaseModel):
    """Configuration for a single extraction service."""
    model_config = ConfigDict(extra='forbid')

    name: str = Field(
        description="Service identifier"
    )
    url: str = Field(
        description="Service endpoint URL"
    )
    timeout: int = Field(
        default=300,
        ge=1,
        le=3600,
        description="Request timeout in seconds"
    )
    enabled: bool = Field(
        default=True,
        description="Enable/disable this service"
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key for authentication"
    )


class ExtractionConfig(BaseModel):
    """
    Document extraction service configuration.

    Supports multiple extraction engines with priority-based routing.
    """
    model_config = ConfigDict(extra='forbid')

    priority: Literal["default", "docling", "auto", "none"] = Field(
        description="Extraction strategy (default, docling, auto, none)"
    )
    services: List[ExtractionServiceConfig] = Field(
        description="List of extraction service configurations"
    )

    @validator('services')
    def validate_services(cls, v):
        """Ensure at least one service is configured."""
        if not v:
            raise ValueError("At least one extraction service must be configured")
        return v


class SharePointConfig(BaseModel):
    """
    Microsoft SharePoint / Graph API configuration.

    Uses Azure AD app-only authentication (client credentials flow).
    """
    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(
        default=True,
        description="Enable SharePoint integration"
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

    Supports console (dev), SMTP, SendGrid, and AWS SES backends.
    """
    model_config = ConfigDict(extra='forbid')

    backend: Literal["console", "smtp", "sendgrid", "ses"] = Field(
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


class DeduplicationConfig(BaseModel):
    """File deduplication configuration."""
    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(
        default=True,
        description="Enable file deduplication"
    )
    strategy: Literal["symlink", "copy", "reference"] = Field(
        default="symlink",
        description="Deduplication strategy"
    )
    hash_algorithm: str = Field(
        default="sha256",
        description="Hash algorithm (md5, sha1, sha256, sha512)"
    )
    min_file_size: int = Field(
        default=1024,
        ge=0,
        description="Minimum file size in bytes to deduplicate"
    )


class RetentionConfig(BaseModel):
    """File retention configuration."""
    model_config = ConfigDict(extra='forbid')

    uploaded_days: int = Field(
        default=7,
        ge=0,
        description="Days to retain uploaded files"
    )
    processed_days: int = Field(
        default=30,
        ge=0,
        description="Days to retain processed files"
    )
    batch_days: int = Field(
        default=14,
        ge=0,
        description="Days to retain batch files"
    )
    temp_hours: int = Field(
        default=24,
        ge=0,
        description="Hours to retain temporary files"
    )


class CleanupConfig(BaseModel):
    """Automatic cleanup configuration."""
    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(
        default=True,
        description="Enable automatic cleanup"
    )
    schedule_cron: str = Field(
        default="0 2 * * *",
        description="Cleanup schedule in cron format"
    )
    batch_size: int = Field(
        default=1000,
        ge=1,
        description="Files to process per cleanup batch"
    )
    dry_run: bool = Field(
        default=False,
        description="Run in dry-run mode (preview only)"
    )


class StorageConfig(BaseModel):
    """Storage management configuration."""
    model_config = ConfigDict(extra='forbid')

    hierarchical: bool = Field(
        default=True,
        description="Use hierarchical organization-based file structure"
    )
    deduplication: DeduplicationConfig = Field(
        default_factory=DeduplicationConfig,
        description="File deduplication settings"
    )
    retention: RetentionConfig = Field(
        default_factory=RetentionConfig,
        description="File retention policies"
    )
    cleanup: CleanupConfig = Field(
        default_factory=CleanupConfig,
        description="Automatic cleanup settings"
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
        default="processing",
        description="Default queue name for processing tasks"
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
    sharepoint: Optional[SharePointConfig] = Field(
        default=None,
        description="SharePoint / Microsoft Graph configuration"
    )
    email: Optional[EmailConfig] = Field(
        default=None,
        description="Email service configuration"
    )
    storage: StorageConfig = Field(
        default_factory=StorageConfig,
        description="Storage management configuration"
    )
    queue: QueueConfig = Field(
        default_factory=QueueConfig,
        description="Queue configuration"
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
            if obj.startswith("${") and obj.endswith("}"):
                var_name = obj[2:-1]
                value = os.getenv(var_name)
                if value is None:
                    raise ValueError(f"Environment variable not set: {var_name}")
                return value
            return obj
        else:
            return obj
