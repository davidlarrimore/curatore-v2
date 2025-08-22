# backend/app/config.py
import os
from typing import Optional, List
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # API Settings
    api_title: str = "Curatore API"
    api_version: str = "2.0.0"
    debug: bool = Field(default=False, env="DEBUG")
    
    # CORS Settings
    cors_origins: List[str] = Field(
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
    batch_dir: str = Field(default="files/batch_files", env="BATCH_DIR")    
    upload_dir: str = Field(default="files/uploaded_files", env="UPLOAD_DIR")
    processed_dir: str = Field(default="files/processed_files", env="PROCESSED_DIR")
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
        
        # Handle JSON parsing for CORS_ORIGINS
        @classmethod
        def parse_env_var(cls, field_name: str, raw_val: str) -> any:
            if field_name == 'cors_origins':
                try:
                    import json
                    return json.loads(raw_val)
                except:
                    # If JSON parsing fails, treat as comma-separated string
                    return [url.strip() for url in raw_val.split(',')]
            return cls.json_loads(raw_val)


# Create settings instance with error handling
try:
    settings = Settings()
except Exception as e:
    # Fallback to basic settings if env parsing fails
    print(f"Warning: Error loading settings: {e}")
    print("Using default configuration...")
    
    class FallbackSettings:
        api_title = "Curatore API"
        api_version = "2.0.0"
        debug = False
        cors_origins = ["http://localhost:3000"]
        openai_api_key = os.getenv("OPENAI_API_KEY")
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        openai_verify_ssl = os.getenv("OPENAI_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
        openai_timeout = float(os.getenv("OPENAI_TIMEOUT", "60"))
        openai_max_retries = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
        ocr_lang = os.getenv("OCR_LANG", "eng")
        ocr_psm = int(os.getenv("OCR_PSM", "3"))
        batch_dir = os.getenv("BATCH_DIR", "files/batch_files")
        upload_dir = os.getenv("UPLOAD_DIR", "files/uploaded_files")
        processed_dir = os.getenv("PROCESSED_DIR", "files/processed_files")
        max_file_size = int(os.getenv("MAX_FILE_SIZE", "52428800"))
        default_conversion_threshold = int(os.getenv("DEFAULT_CONVERSION_THRESHOLD", "70"))
        default_clarity_threshold = int(os.getenv("DEFAULT_CLARITY_THRESHOLD", "7"))
        default_completeness_threshold = int(os.getenv("DEFAULT_COMPLETENESS_THRESHOLD", "7"))
        default_relevance_threshold = int(os.getenv("DEFAULT_RELEVANCE_THRESHOLD", "7"))
        default_markdown_threshold = int(os.getenv("DEFAULT_MARKDOWN_THRESHOLD", "7"))
    
    settings = FallbackSettings()