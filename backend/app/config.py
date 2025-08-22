# backend/app/config.py
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # API Settings
    api_title: str = "Curatore API"
    api_version: str = "2.0.0"
    debug: bool = Field(default=False, env="DEBUG")
    
    # CORS Settings
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        env="CORS_ORIGINS"
    )
    
    # OpenAI/LLM Configuration
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", env="OPENAI_MODEL")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", 
        env="OPENAI_BASE_URL"
    )
    openai_verify_ssl: bool = Field(default=True, env="OPENAI_VERIFY_SSL")
    openai_timeout: float = Field(default=60.0, env="OPENAI_TIMEOUT")
    openai_max_retries: int = Field(default=3, env="OPENAI_MAX_RETRIES")
    
    # OCR Configuration
    ocr_lang: str = Field(default="eng", env="OCR_LANG")
    ocr_psm: int = Field(default=3, env="OCR_PSM")
    
    # File Storage
    upload_dir: str = Field(default="uploads", env="UPLOAD_DIR")
    processed_dir: str = Field(default="processed", env="PROCESSED_DIR")
    max_file_size: int = Field(default=50 * 1024 * 1024, env="MAX_FILE_SIZE")  # 50MB
    
    # Quality Thresholds
    default_conversion_threshold: int = Field(default=70, env="DEFAULT_CONVERSION_THRESHOLD")
    default_clarity_threshold: int = Field(default=7, env="DEFAULT_CLARITY_THRESHOLD")
    default_completeness_threshold: int = Field(default=7, env="DEFAULT_COMPLETENESS_THRESHOLD")
    default_relevance_threshold: int = Field(default=7, env="DEFAULT_RELEVANCE_THRESHOLD")
    default_markdown_threshold: int = Field(default=7, env="DEFAULT_MARKDOWN_THRESHOLD")

    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()