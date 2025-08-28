# backend/app/models.py
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class QualityThresholds(BaseModel):
    """Quality thresholds for document evaluation."""
    conversion: int = Field(ge=0, le=100, default=70)
    clarity: int = Field(ge=1, le=10, default=7)
    completeness: int = Field(ge=1, le=10, default=7)
    relevance: int = Field(ge=1, le=10, default=7)
    markdown: int = Field(ge=1, le=10, default=7)


class OCRSettings(BaseModel):
    """OCR configuration settings."""
    language: str = Field(default="eng", description="OCR language code")
    psm: int = Field(ge=0, le=13, default=3, description="Page segmentation mode")


class ProcessingOptions(BaseModel):
    """Options for document processing."""
    auto_optimize: bool = Field(default=True, description="Enable vector DB optimization")
    ocr_settings: OCRSettings = Field(default_factory=OCRSettings)
    quality_thresholds: QualityThresholds = Field(default_factory=QualityThresholds)


class LLMEvaluation(BaseModel):
    """LLM evaluation results."""
    clarity_score: Optional[int] = Field(None, ge=1, le=10)
    clarity_feedback: Optional[str] = None
    completeness_score: Optional[int] = Field(None, ge=1, le=10)
    completeness_feedback: Optional[str] = None
    relevance_score: Optional[int] = Field(None, ge=1, le=10)
    relevance_feedback: Optional[str] = None
    markdown_score: Optional[int] = Field(None, ge=1, le=10)
    markdown_feedback: Optional[str] = None
    overall_feedback: Optional[str] = None
    pass_recommendation: Optional[str] = None


class ConversionResult(BaseModel):
    """Document conversion result."""
    success: bool
    markdown_content: Optional[str] = None
    conversion_score: int = Field(ge=0, le=100)
    conversion_feedback: str
    conversion_note: str = ""


class DocumentInfo(BaseModel):
    """Basic document information."""
    filename: str
    file_size: int
    file_type: str
    upload_time: datetime


class ProcessingResult(BaseModel):
    """Complete processing result for a document."""
    document_id: str
    filename: str
    status: ProcessingStatus
    success: bool
    message: Optional[str] = None
    
    # File paths
    original_path: Optional[str] = None
    markdown_path: Optional[str] = None
    
    # Processing results
    conversion_result: Optional[ConversionResult] = None
    llm_evaluation: Optional[LLMEvaluation] = None
    document_summary: Optional[str] = None
    
    # Quality assessment
    conversion_score: int = Field(default=0, ge=0, le=100)
    pass_all_thresholds: bool = False
    vector_optimized: bool = False
    
    # Metadata
    processing_time: Optional[float] = None
    processed_at: Optional[datetime] = None
    thresholds_used: Optional[QualityThresholds] = None


class BatchProcessingRequest(BaseModel):
    """Request for batch processing."""
    document_ids: List[str]
    options: ProcessingOptions = Field(default_factory=ProcessingOptions)


class BatchProcessingResult(BaseModel):
    """Result of batch processing."""
    batch_id: str
    total_files: int
    successful: int
    failed: int
    rag_ready: int
    results: List[ProcessingResult]
    processing_time: float
    started_at: datetime
    completed_at: Optional[datetime] = None


class BulkDownloadRequest(BaseModel):
    """Request model for bulk download operations."""
    document_ids: List[str]
    download_type: str = Field(default="individual", description="Type of download: individual, combined, rag_ready")
    zip_name: Optional[str] = Field(None, description="Custom name for the ZIP file")
    include_summary: bool = Field(default=True, description="Include processing summary in archive")


class ZipArchiveInfo(BaseModel):
    """Information about a created ZIP archive."""
    filename: str
    file_count: int
    total_size: int
    created_at: datetime
    download_type: str
    includes_summary: bool


class LLMConnectionStatus(BaseModel):
    """LLM connection test result."""
    connected: bool
    endpoint: str
    model: str
    error: Optional[str] = None
    response: Optional[str] = None
    ssl_verify: bool
    timeout: float


class DocumentEditRequest(BaseModel):
    """Request to edit document content."""
    content: str
    improvement_prompt: Optional[str] = None
    apply_vector_optimization: bool = False


class HealthStatus(BaseModel):
    """API health status."""
    status: str
    timestamp: datetime
    version: str
    llm_connected: bool
    storage_available: bool


class FileUploadResponse(BaseModel):
    """Response for file upload."""
    document_id: str
    filename: str
    file_size: int
    upload_time: datetime
    message: str


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class SupportedFormatsResponse(BaseModel):
    """Response for supported file formats."""
    supported_extensions: List[str]
    max_file_size: int
    description: str = "Supported file formats for document processing"


class SystemResetResponse(BaseModel):
    """Response for system reset operation."""
    success: bool
    message: str
    timestamp: datetime
    files_cleared: Dict[str, int] = Field(default_factory=dict)
    storage_cleared: bool = False