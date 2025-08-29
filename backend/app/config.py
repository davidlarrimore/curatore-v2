# ============================================================================
# Curatore v2 - Application Configuration
# ============================================================================
"""
Application configuration module using Pydantic Settings.

This module defines all configuration parameters for the Curatore v2 application,
including:
- API settings (title, version, debug mode)
- CORS configuration for cross-origin requests
- OpenAI/LLM API configuration with flexible endpoint support
- OCR settings for image processing
- File storage paths and limits
- Quality assessment thresholds

Environment Variables:
    The configuration automatically loads from environment variables.
    See .env.example for a complete list of available settings.

Usage:
    from app.config import settings
    
    # Access configuration values
    api_key = settings.openai_api_key
    max_size = settings.max_file_size

Architecture:
    - Uses Pydantic Settings for automatic environment variable loading
    - Type validation and conversion
    - Default values for development environment
    - Flexible configuration for different deployment scenarios

Author: Curatore Team
Version: 2.0.0
"""

import os
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings with automatic environment variable loading.
    
    This class defines all configuration parameters for the application.
    Values are automatically loaded from environment variables, with
    sensible defaults for development.
    
    Attributes:
        API Settings:
            api_title: Application title for API documentation
            api_version: Current API version
            debug: Debug mode flag (enables detailed error messages)
            
        CORS Settings:
            cors_origins: List of allowed origins for cross-origin requests
            
        OpenAI/LLM Configuration:
            openai_api_key: API key for OpenAI or compatible services
            openai_model: Model name to use for LLM operations
            openai_base_url: Base URL for the LLM API endpoint
            openai_verify_ssl: Whether to verify SSL certificates
            openai_timeout: Request timeout in seconds
            openai_max_retries: Maximum number of retry attempts
            
        OCR Configuration:
            ocr_lang: Language code for OCR processing
            ocr_psm: Page Segmentation Mode for Tesseract
            
        File Storage:
            files_root: Root directory for all file storage
            upload_dir: Directory for uploaded files
            processed_dir: Directory for processed markdown files
            batch_dir: Directory for batch processing files
            max_file_size: Maximum file size in bytes
            
        Quality Thresholds:
            default_*_threshold: Default quality thresholds for assessment
    """
    
    # ========================================================================
    # API SETTINGS
    # ========================================================================
    
    api_title: str = "Curatore API"
    """Application title displayed in API documentation."""
    
    api_version: str = "2.0.0"
    """Current API version for versioning and compatibility."""
    
    debug: bool = Field(default=False, description="Enable debug mode with detailed error messages")
    """Debug mode flag. When enabled, provides detailed error information."""
    
    # ========================================================================
    # CORS SETTINGS
    # ========================================================================
    
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="List of allowed origins for CORS"
    )
    """
    List of allowed origins for Cross-Origin Resource Sharing (CORS).
    
    Default includes localhost:3000 for frontend development.
    In production, update this to include your frontend domain.
    
    Environment Variable: CORS_ORIGINS (comma-separated list)
    Example: "https://app.example.com,https://admin.example.com"
    """

    cors_origin_regex: Optional[str] = Field(
        default=r"^http://(localhost|127\.0\.0\.1)(:\\d+)?$",
        description="Optional regex to match allowed origins"
    )
    """
    Optional regex pattern to match allowed origins for development.
    This complements cors_origins. If both are set, either match allows the request.
    """
    
    # ========================================================================
    # OPENAI/LLM CONFIGURATION
    # ========================================================================
    
    openai_api_key: Optional[str] = Field(
        default=None,
        description="API key for OpenAI or compatible LLM service"
    )
    """
    API key for OpenAI or compatible LLM service.
    
    Required for LLM-based document evaluation and improvement features.
    If not provided, LLM features will be disabled but document conversion
    will still work.
    
    Environment Variable: OPENAI_API_KEY
    """
    
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="Model name for LLM operations"
    )
    """
    Model name to use for LLM operations.
    
    Supported values depend on your LLM provider:
    - OpenAI: gpt-4o-mini, gpt-4, gpt-3.5-turbo
    - Local (Ollama): llama3.1:8b, mistral:7b, etc.
    - Other providers: Consult provider documentation
    
    Environment Variable: OPENAI_MODEL
    """
    
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for the LLM API endpoint"
    )
    """
    Base URL for the LLM API endpoint.
    
    This allows using different LLM providers or local installations:
    - OpenAI: https://api.openai.com/v1
    - Local Ollama: http://localhost:11434/v1
    - LM Studio: http://localhost:1234/v1
    - OpenWebUI: http://localhost:3000/v1
    
    Environment Variable: OPENAI_BASE_URL
    """
    
    openai_verify_ssl: bool = Field(
        default=True,
        description="Whether to verify SSL certificates for LLM requests"
    )
    """
    Whether to verify SSL certificates for LLM API requests.
    
    Set to False for local development with self-signed certificates
    or when using HTTP endpoints. Keep True in production for security.
    
    Environment Variable: OPENAI_VERIFY_SSL
    """
    
    openai_timeout: float = Field(
        default=60.0,
        description="Request timeout in seconds for LLM operations"
    )
    """
    Request timeout in seconds for LLM API calls.
    
    Longer timeouts may be needed for complex document analysis.
    Shorter timeouts can help prevent hanging requests.
    
    Environment Variable: OPENAI_TIMEOUT
    """
    
    openai_max_retries: int = Field(
        default=3,
        description="Maximum number of retry attempts for failed LLM requests"
    )
    """
    Maximum number of retry attempts for failed LLM requests.
    
    The client will automatically retry failed requests up to this limit
    with exponential backoff. Useful for handling temporary network issues.
    
    Environment Variable: OPENAI_MAX_RETRIES
    """
    
    # ========================================================================
    # OCR CONFIGURATION
    # ========================================================================
    
    ocr_lang: str = Field(
        default="eng",
        description="Language code for OCR processing (ISO 639-3)"
    )
    """
    Language code for OCR processing using Tesseract.
    
    Common values:
    - eng: English
    - spa: Spanish
    - fra: French
    - deu: German
    - chi_sim: Chinese Simplified
    
    Multiple languages: "eng+spa+fra"
    
    Environment Variable: OCR_LANG
    """
    
    ocr_psm: int = Field(
        default=3,
        description="Page Segmentation Mode for Tesseract OCR"
    )
    """
    Page Segmentation Mode (PSM) for Tesseract OCR.
    
    Common values:
    - 1: Automatic page segmentation with OSD
    - 3: Fully automatic page segmentation, but no OSD (default)
    - 6: Uniform block of text
    - 8: Single word
    - 13: Raw line. Treat the image as a single text line
    
    Environment Variable: OCR_PSM
    """
    
    # ========================================================================
    # FILE STORAGE CONFIGURATION
    # ========================================================================
    
    files_root: str = Field(
        default="/app/files",
        description="Root directory for all file storage"
    )
    """
    Root directory for all file storage operations.
    
    This should match the Docker volume mount point. All other file
    directories are subdirectories of this root path.
    
    Environment Variable: FILES_ROOT
    """
    
    upload_dir: str = Field(
        default="/app/files/uploaded_files",
        description="Directory for storing uploaded files"
    )
    """
    Directory for storing uploaded files before processing.
    
    Files are temporarily stored here during the upload and processing
    workflow. Should be a subdirectory of files_root.
    
    Environment Variable: UPLOAD_DIR
    """
    
    processed_dir: str = Field(
        default="/app/files/processed_files",
        description="Directory for storing processed markdown files"
    )
    """
    Directory for storing processed markdown files.
    
    This is where the final converted and optimized markdown files
    are stored. Should be a subdirectory of files_root.
    
    Environment Variable: PROCESSED_DIR
    """
    
    batch_dir: str = Field(
        default="/app/files/batch_files",
        description="Directory for batch processing files"
    )
    """
    Directory for files intended for batch processing.
    
    Users can place files directly in this directory for bulk processing
    operations. Should be a subdirectory of files_root.
    
    Environment Variable: BATCH_DIR
    """
    
    max_file_size: int = Field(
        default=50 * 1024 * 1024,  # 50MB
        description="Maximum file size in bytes for uploads"
    )
    """
    Maximum file size in bytes for file uploads.
    
    Default is 50MB (52,428,800 bytes). Larger files will be rejected
    during upload to prevent resource exhaustion.
    
    Environment Variable: MAX_FILE_SIZE
    """
    
    # ========================================================================
    # QUALITY ASSESSMENT THRESHOLDS
    # ========================================================================
    
    default_conversion_threshold: int = Field(
        default=70,
        description="Default threshold for conversion quality (0-100)"
    )
    """
    Default threshold for conversion quality assessment (0-100).
    
    Documents with conversion scores below this threshold will be
    flagged as needing improvement. Based on content coverage,
    structure preservation, and readability metrics.
    
    Environment Variable: DEFAULT_CONVERSION_THRESHOLD
    """
    
    default_clarity_threshold: int = Field(
        default=7,
        description="Default threshold for LLM clarity evaluation (1-10)"
    )
    """
    Default threshold for LLM clarity evaluation (1-10).
    
    Documents with clarity scores below this threshold will be
    flagged as needing improvement. Assesses document structure,
    readability, and logical flow.
    
    Environment Variable: DEFAULT_CLARITY_THRESHOLD
    """
    
    default_completeness_threshold: int = Field(
        default=7,
        description="Default threshold for LLM completeness evaluation (1-10)"
    )
    """
    Default threshold for LLM completeness evaluation (1-10).
    
    Documents with completeness scores below this threshold will be
    flagged as needing improvement. Assesses information preservation
    and missing content detection.
    
    Environment Variable: DEFAULT_COMPLETENESS_THRESHOLD
    """
    
    default_relevance_threshold: int = Field(
        default=7,
        description="Default threshold for LLM relevance evaluation (1-10)"
    )
    """
    Default threshold for LLM relevance evaluation (1-10).
    
    Documents with relevance scores below this threshold will be
    flagged as needing improvement. Assesses content focus and
    identification of unnecessary information.
    
    Environment Variable: DEFAULT_RELEVANCE_THRESHOLD
    """
    
    default_markdown_threshold: int = Field(
        default=7,
        description="Default threshold for markdown quality evaluation (1-10)"
    )
    """
    Default threshold for markdown quality evaluation (1-10).
    
    Documents with markdown scores below this threshold will be
    flagged as needing improvement. Assesses formatting consistency
    and structure quality.
    
    Environment Variable: DEFAULT_MARKDOWN_THRESHOLD
    """
    
    # ========================================================================
    # PYDANTIC CONFIGURATION
    # ========================================================================
    
    class Config:
        """Pydantic configuration for the Settings class."""
        
        env_file = ".env"
        """Load environment variables from .env file if present."""
        
        env_file_encoding = "utf-8"
        """Use UTF-8 encoding for .env file."""
        
        case_sensitive = False
        """Environment variable names are case-insensitive."""
        
        extra = "ignore"
        """Ignore extra environment variables not defined in the model."""


# ============================================================================
# GLOBAL SETTINGS INSTANCE
# ============================================================================

# Create global settings instance
# This is imported by other modules to access configuration
settings = Settings()

# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

def validate_configuration() -> None:
    """
    Validate the current configuration for common issues.
    
    This function performs runtime validation of the configuration
    to catch common setup problems early.
    
    Raises:
        ValueError: If critical configuration issues are found
        
    Note:
        This function is called during application startup to ensure
        the configuration is valid before processing begins.
    """
    issues = []
    
    # Validate file storage paths
    if not settings.files_root:
        issues.append("files_root cannot be empty")
    
    if not settings.upload_dir.startswith(settings.files_root):
        issues.append("upload_dir must be a subdirectory of files_root")
    
    if not settings.processed_dir.startswith(settings.files_root):
        issues.append("processed_dir must be a subdirectory of files_root")
    
    if not settings.batch_dir.startswith(settings.files_root):
        issues.append("batch_dir must be a subdirectory of files_root")
    
    # Validate file size limits
    if settings.max_file_size <= 0:
        issues.append("max_file_size must be positive")
    
    # Validate quality thresholds
    if not (0 <= settings.default_conversion_threshold <= 100):
        issues.append("default_conversion_threshold must be between 0 and 100")
    
    for threshold_name in ["clarity", "completeness", "relevance", "markdown"]:
        threshold_value = getattr(settings, f"default_{threshold_name}_threshold")
        if not (1 <= threshold_value <= 10):
            issues.append(f"default_{threshold_name}_threshold must be between 1 and 10")
    
    # Validate LLM settings (warnings, not errors)
    warnings = []
    if not settings.openai_api_key:
        warnings.append("openai_api_key not set - LLM features will be disabled")
    
    if settings.openai_timeout <= 0:
        warnings.append("openai_timeout should be positive")
    
    if settings.openai_max_retries < 0:
        warnings.append("openai_max_retries should be non-negative")
    
    # Report issues
    if issues:
        raise ValueError(f"Configuration validation failed:\n" + "\n".join(f"  - {issue}" for issue in issues))
    
    if warnings:
        print("⚠️  Configuration warnings:")
        for warning in warnings:
            print(f"  - {warning}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_configuration_summary() -> dict:
    """
    Get a summary of the current configuration.
    
    Returns:
        dict: Configuration summary with sensitive values masked
        
    Note:
        This function is useful for debugging and logging configuration
        without exposing sensitive values like API keys.
    """
    return {
        "api": {
            "title": settings.api_title,
            "version": settings.api_version,
            "debug": settings.debug
        },
        "cors": {
            "origins": settings.cors_origins
        },
        "llm": {
            "model": settings.openai_model,
            "base_url": settings.openai_base_url,
            "api_key_configured": bool(settings.openai_api_key),
            "verify_ssl": settings.openai_verify_ssl,
            "timeout": settings.openai_timeout,
            "max_retries": settings.openai_max_retries
        },
        "ocr": {
            "language": settings.ocr_lang,
            "psm": settings.ocr_psm
        },
        "storage": {
            "files_root": settings.files_root,
            "upload_dir": settings.upload_dir,
            "processed_dir": settings.processed_dir,
            "batch_dir": settings.batch_dir,
            "max_file_size_mb": round(settings.max_file_size / (1024 * 1024), 1)
        },
        "quality_thresholds": {
            "conversion": settings.default_conversion_threshold,
            "clarity": settings.default_clarity_threshold,
            "completeness": settings.default_completeness_threshold,
            "relevance": settings.default_relevance_threshold,
            "markdown": settings.default_markdown_threshold
        }
    }
