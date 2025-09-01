# ============================================================================
# backend/app/config.py
# ============================================================================
from __future__ import annotations

from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ----------------------------- API --------------------------------------
    api_title: str = "Curatore API"
    api_version: str = "2.0.0"
    debug: bool = Field(default=False, env="DEBUG")

    # ---------------------------- CORS --------------------------------------
    # Allowlist + regex (main.py may use regex)
    cors_origins: List[str] = Field(default=["http://localhost:3000"], env="CORS_ORIGINS")
    cors_origin_regex: Optional[str] = Field(
        # NOTE: single backslash in env becomes a single backslash in regex.
        # Keep \d (not \\d) in .env; both http and https allowed for dev.
        default=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        env="CORS_ORIGIN_REGEX",
    )

    # ---------------------------- FILES / STORAGE ---------------------------
    files_root: str = Field(default="backend_files", env="FILES_ROOT")
    upload_dir: str = Field(default="backend_files/uploads", env="UPLOAD_DIR")
    processed_dir: str = Field(default="backend_files/processed", env="PROCESSED_DIR")
    batch_dir: str = Field(default="backend_files/batch_files", env="BATCH_DIR")
    max_file_size: int = Field(default=50 * 1024 * 1024, env="MAX_FILE_SIZE")  # 50MB

    # ----------------------------- OCR (UI expects these) -------------------
    # Even though extraction is external now, some endpoints/UI read these.
    ocr_lang: str = Field(default="eng", env="OCR_LANG")
    ocr_psm: int = Field(default=3, env="OCR_PSM")

    # -------------------------- LLM / OpenAI --------------------------------
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", env="OPENAI_MODEL")
    openai_base_url: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    openai_verify_ssl: bool = Field(default=True, env="OPENAI_VERIFY_SSL")
    openai_timeout: float = Field(default=60.0, env="OPENAI_TIMEOUT")
    openai_max_retries: int = Field(default=3, env="OPENAI_MAX_RETRIES")

    # ----------------------- Extraction Service ------------------------------
    extractor_base_url: Optional[str] = Field(default="http://extraction:8000", env="EXTRACTOR_BASE_URL")
    extractor_extract_path: str = Field(default="/v1/extract", env="EXTRACTOR_EXTRACT_PATH")
    extractor_timeout: float = Field(default=120.0, env="EXTRACTOR_TIMEOUT")
    extractor_max_retries: int = Field(default=2, env="EXTRACTOR_MAX_RETRIES")
    extractor_api_key: Optional[str] = Field(default=None, env="EXTRACTOR_API_KEY")
    extractor_verify_ssl: bool = Field(default=True, env="EXTRACTOR_VERIFY_SSL")

    # ----------------------- Quality Thresholds ------------------------------
    default_conversion_threshold: int = Field(default=70, env="DEFAULT_CONVERSION_THRESHOLD")
    default_clarity_threshold: int = Field(default=7, env="DEFAULT_CLARITY_THRESHOLD")
    default_completeness_threshold: int = Field(default=7, env="DEFAULT_COMPLETENESS_THRESHOLD")
    default_relevance_threshold: int = Field(default=7, env="DEFAULT_RELEVANCE_THRESHOLD")
    default_markdown_threshold: int = Field(default=7, env="DEFAULT_MARKDOWN_THRESHOLD")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
