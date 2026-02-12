"""
Configuration for the Extraction Service.

This service handles Office documents, text files, and emails via MarkItDown.
PDFs and images are handled by fast_pdf (PyMuPDF) and Docling respectively.
"""

import os
from typing import List

from pydantic import BaseModel, Field


class Settings(BaseModel):
    # API
    API_TITLE: str = Field(default="Curatore Extraction Service")
    API_VERSION: str = Field(default="1.0.0")
    DEBUG: bool = Field(default=os.getenv("DEBUG", "false").lower() == "true")

    # CORS
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: List[str] = Field(default_factory=lambda: ["*"])
    CORS_HEADERS: List[str] = Field(default_factory=lambda: ["*"])

    # File Upload Limits
    MAX_FILE_SIZE: int = Field(default=int(os.getenv("MAX_FILE_SIZE", "52428800")))  # 50MB

    # Upload Directory
    UPLOAD_DIR: str = Field(default=os.getenv("UPLOAD_DIR", "/tmp/extraction_uploads"))


settings = Settings()
