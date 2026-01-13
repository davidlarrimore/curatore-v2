"""
Versioned models for API v1.

Provides a stable import surface and v1-specific request schemas that
map to internal domain models, allowing the frontend's v1 payload shape.
"""

from typing import Optional, List
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field
from pydantic import AliasChoices
from pydantic import model_validator
from pydantic import AliasChoices

# Shared domain models
from ...models import (
    FileUploadResponse,
    ConversionResult,
    LLMEvaluation,
    ProcessingStatus,
    DocumentEditRequest,
    ProcessingOptions,
    QualityThresholds,
    BulkDownloadRequest,
    ZipArchiveInfo,
    HealthStatus,
    LLMConnectionStatus,
)


class V1QualityThresholds(BaseModel):
    """Frontend v1-friendly thresholds payload shape."""
    conversion: int = Field(default=70, ge=0, le=100)
    clarity: int = Field(default=7, ge=1, le=10)
    completeness: int = Field(default=7, ge=1, le=10)
    relevance: int = Field(default=7, ge=1, le=10)
    markdown: int = Field(default=7, ge=1, le=10)

    def to_domain(self) -> QualityThresholds:
        return QualityThresholds(
            conversion_quality=self.conversion,
            clarity_score=self.clarity,
            completeness_score=self.completeness,
            relevance_score=self.relevance,
            markdown_quality=self.markdown,
        )


class V1ProcessingOptions(BaseModel):
    """
    Frontend v1-friendly processing options.

    Maps to internal ProcessingOptions. Only common fields are exposed.
    """

    auto_optimize: bool = Field(default=True, description="Optimize for vector DB")
    quality_thresholds: Optional[V1QualityThresholds] = None

    def to_domain(self) -> ProcessingOptions:
        return ProcessingOptions(
            auto_improve=self.auto_optimize,
            vector_optimize=self.auto_optimize,
            quality_thresholds=self.quality_thresholds.to_domain() if self.quality_thresholds else None,
        )


class V1BatchProcessingRequest(BaseModel):
    document_ids: List[str]
    options: Optional[V1ProcessingOptions] = None


class SharePointInventoryRequest(BaseModel):
    folder_url: str = Field(..., description="SharePoint folder URL or share link")
    recursive: bool = Field(default=False, description="Traverse subfolders")
    include_folders: bool = Field(default=False, description="Include folders in results")
    page_size: int = Field(default=200, ge=1, le=2000, description="Items per page")
    max_items: Optional[int] = Field(default=None, ge=1, description="Max items to return")


class SharePointInventoryItem(BaseModel):
    index: int
    name: str
    type: str
    folder: str
    extension: str
    size: Optional[int] = None
    created: Optional[str] = None
    modified: Optional[str] = None
    mime: Optional[str] = None
    id: str
    web_url: Optional[str] = None


class SharePointInventoryFolder(BaseModel):
    name: str
    id: str
    web_url: Optional[str] = None
    drive_id: str


class SharePointInventoryResponse(BaseModel):
    folder: SharePointInventoryFolder
    items: List[SharePointInventoryItem]


class SharePointDownloadRequest(BaseModel):
    folder_url: str = Field(..., description="SharePoint folder URL or share link")
    indices: Optional[List[int]] = Field(default=None, description="Indices from inventory")
    download_all: bool = Field(default=False, description="Download all files")
    recursive: bool = Field(default=False, description="Traverse subfolders")
    page_size: int = Field(default=200, ge=1, le=2000, description="Items per page")
    max_items: Optional[int] = Field(default=None, ge=1, description="Max items to scan")
    preserve_folders: bool = Field(default=True, description="Preserve subfolder structure")


class SharePointDownloadItem(BaseModel):
    index: int
    name: str
    folder: str
    path: str
    size: Optional[int] = None


class SharePointDownloadResponse(BaseModel):
    downloaded: List[SharePointDownloadItem]
    skipped: List[SharePointDownloadItem]
    batch_dir: str


__all__ = [
    # Re-exports
    "FileUploadResponse",
    "DocumentEditRequest",
    "BulkDownloadRequest",
    "ZipArchiveInfo",
    "HealthStatus",
    "LLMConnectionStatus",
    # V1 request wrappers
    "V1ProcessingOptions",
    "V1QualityThresholds",
    "V1BatchProcessingRequest",
    # V1 response models
    "V1ProcessingResult",
    "V1BatchProcessingResult",
    # Domain mapping helper types
    "ProcessingOptions",
    # SharePoint
    "SharePointInventoryRequest",
    "SharePointInventoryResponse",
    "SharePointDownloadRequest",
    "SharePointDownloadResponse",
]


class V1ProcessingResult(BaseModel):
    document_id: str
    filename: str
    status: ProcessingStatus
    success: bool
    message: Optional[str] = None
    original_path: Optional[str] = None
    markdown_path: Optional[str] = None
    conversion_result: ConversionResult
    llm_evaluation: Optional[LLMEvaluation] = None
    document_summary: Optional[str] = None
    conversion_score: int
    pass_all_thresholds: bool = Field(validation_alias=AliasChoices('pass_all_thresholds', 'is_rag_ready'))
    vector_optimized: bool
    processing_time: float
    processed_at: Optional[datetime] = None
    thresholds_used: Optional[QualityThresholds] = None

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def ensure_fields(cls, v):
        try:
            # When v is a domain ProcessingResult instance
            if hasattr(v, "conversion_result"):
                cr = getattr(v, "conversion_result", None)
                # Coerce Path fields to strings for v1 API shape
                original_path = getattr(v, "original_path", None)
                if isinstance(original_path, Path):
                    original_path = str(original_path)
                markdown_path = getattr(v, "markdown_path", None)
                if isinstance(markdown_path, Path):
                    markdown_path = str(markdown_path)
                return {
                    "document_id": getattr(v, "document_id", None),
                    "filename": getattr(v, "filename", None),
                    "status": getattr(v, "status", None),
                    "success": getattr(v, "success", True if getattr(v, "status", None) == ProcessingStatus.COMPLETED else False),
                    "message": getattr(v, "message", getattr(v, "error_message", None)),
                    "original_path": original_path,
                    "markdown_path": markdown_path,
                    "conversion_result": cr,
                    "llm_evaluation": getattr(v, "llm_evaluation", None),
                    "document_summary": getattr(v, "document_summary", None),
                    "conversion_score": getattr(cr, "conversion_score", None) if cr else None,
                    "pass_all_thresholds": getattr(v, "is_rag_ready", getattr(v, "pass_all_thresholds", None)),
                    "vector_optimized": getattr(v, "vector_optimized", False),
                    "processing_time": getattr(v, "processing_time", 0.0),
                    "processed_at": getattr(v, "processed_at", None),
                    "thresholds_used": getattr(v, "thresholds_used", None),
                }
        except Exception:
            return v
        return v


class V1BatchProcessingResult(BaseModel):
    batch_id: str
    total_files: int
    successful: int
    failed: int
    rag_ready: int
    results: List[V1ProcessingResult]
    processing_time: float
    started_at: datetime
    completed_at: datetime
