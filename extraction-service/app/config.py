from pydantic import BaseModel, Field
import os
from typing import List

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

    # OCR
    OCR_LANG: str = Field(default=os.getenv("OCR_LANG", "eng"))
    OCR_PSM: str = Field(default=os.getenv("OCR_PSM", "3"))

    # Behavior
    # If markitdown yields too little text, try OCR (or LibreOffice->PDF->pdfminer/OCR).
    # Make this tunable via env for tests and constrained environments.
    MIN_TEXT_CHARS_FOR_NO_OCR: int = Field(default=int(os.getenv("MIN_TEXT_CHARS_FOR_NO_OCR", "300")))

settings = Settings()
