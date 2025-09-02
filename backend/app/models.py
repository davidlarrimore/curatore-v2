# ============================================================================
# Curatore v2 - Pydantic Data Models and Schemas
# ============================================================================
"""
Pydantic data models and schemas for the Curatore v2 API.

This module defines all data structures used throughout the application,
including:
- Request and response models for API endpoints
- Configuration models for processing options
- Data transfer objects for services
- Validation schemas with proper type hints

Key Features:
- Automatic validation and serialization
- Type safety with Python type hints
- JSON Schema generation for OpenAPI docs
- Custom validators for business logic
- Consistent error handling

Architecture:
- Uses Pydantic BaseModel for all models
- Separates request/response models from internal models
- Includes comprehensive documentation for all fields
- Supports optional fields with sensible defaults

Author: Curatore Team
Version: 2.0.0
"""

from datetime import datetime
from pathlib import Path
from enum import Enum
from typing import Dict, List, Optional, Union, Any

from pydantic import BaseModel, Field, validator


# ============================================================================
# ENUMERATION TYPES
# ============================================================================

class ProcessingStatus(str, Enum):
    """
    Enumeration for document processing status.
    
    Values:
        PENDING: Processing has been queued but not started
        PROCESSING: Document is currently being processed
        COMPLETED: Processing completed successfully
        FAILED: Processing failed with errors
        CANCELLED: Processing was cancelled by user
    """
    PENDING = "pending"
    PROCESSING = "processing" 
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadType(str, Enum):
    """
    Enumeration for bulk download types.
    
    Values:
        INDIVIDUAL: Download individual processed files
        COMBINED: Download combined markdown with adjusted hierarchy
        RAG_READY: Download only files that meet quality thresholds
        SUMMARY: Download processing summary report
    """
    INDIVIDUAL = "individual"
    COMBINED = "combined"
    RAG_READY = "rag_ready"
    SUMMARY = "summary"


# ============================================================================
# CONFIGURATION MODELS
# ============================================================================

class OCRSettings(BaseModel):
    """
    Configuration model for OCR (Optical Character Recognition) settings.
    
    Used when processing image files (PNG, JPG, etc.) to extract text content.
    
    Attributes:
        language: OCR language code (default: 'eng')
        psm: Page Segmentation Mode for Tesseract (1-13)
        confidence_threshold: Minimum confidence score (0.0-1.0)
        
    Example:
        ocr = OCRSettings(
            language='eng',
            psm=3,
            confidence_threshold=0.8
        )
    """
    language: str = Field(
        default="eng",
        description="OCR language code (e.g., 'eng', 'fra', 'deu')"
    )
    psm: int = Field(
        default=3,
        ge=1,
        le=13,
        description="Page Segmentation Mode for Tesseract OCR"
    )
    confidence_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score for OCR results"
    )


class QualityThresholds(BaseModel):
    """
    Configuration model for document quality assessment thresholds.
    
    Defines minimum acceptable scores for various quality metrics.
    Documents must meet all thresholds to be considered "RAG ready".
    
    Attributes:
        conversion_quality: Minimum conversion score (0-100%)
        clarity_score: Minimum clarity score (1-10)
        completeness_score: Minimum completeness score (1-10)
        relevance_score: Minimum relevance score (1-10)
        markdown_quality: Minimum markdown formatting score (1-10)
        
    Example:
        thresholds = QualityThresholds(
            conversion_quality=75,
            clarity_score=7,
            completeness_score=8,
            relevance_score=6,
            markdown_quality=7
        )
    """
    conversion_quality: int = Field(
        default=70,
        ge=0,
        le=100,
        description="Minimum conversion quality percentage"
    )
    clarity_score: int = Field(
        default=7,
        ge=1,
        le=10,
        description="Minimum clarity score (1-10 scale)"
    )
    completeness_score: int = Field(
        default=7,
        ge=1,
        le=10,
        description="Minimum completeness score (1-10 scale)"
    )
    relevance_score: int = Field(
        default=7,
        ge=1,
        le=10,
        description="Minimum relevance score (1-10 scale)"
    )
    markdown_quality: int = Field(
        default=7,
        ge=1,
        le=10,
        description="Minimum markdown quality score (1-10 scale)"
    )


class ProcessingOptions(BaseModel):
    """
    Configuration model for document processing options.
    
    Contains all settings that control how documents are processed,
    including quality thresholds, OCR settings, and optimization flags.
    
    Attributes:
        auto_improve: Enable automatic content improvement
        vector_optimize: Optimize content for vector databases
        quality_thresholds: Quality assessment thresholds
        ocr_settings: OCR configuration for image processing
        
    Example:
        options = ProcessingOptions(
            auto_improve=True,
            vector_optimize=True,
            quality_thresholds=QualityThresholds(),
            ocr_settings=OCRSettings()
        )
    """
    auto_improve: bool = Field(
        default=True,
        description="Enable automatic content improvement using LLM"
    )
    vector_optimize: bool = Field(
        default=True,
        description="Optimize content structure for vector databases"
    )
    quality_thresholds: Optional[QualityThresholds] = Field(
        default_factory=QualityThresholds,
        description="Quality assessment thresholds"
    )
    ocr_settings: Optional[OCRSettings] = Field(
        default_factory=OCRSettings,
        description="OCR configuration for image processing"
    )


# ============================================================================
# PROCESSING RESULT MODELS
# ============================================================================

class ConversionResult(BaseModel):
    """
    Result model for document conversion operations.
    
    Contains information about the conversion process including
    success status, quality scores, and feedback messages.
    
    Attributes:
        success: Whether conversion completed successfully
        markdown_content: Converted markdown content (optional)
        conversion_score: Quality score for conversion (0-100)
        conversion_feedback: Human-readable conversion feedback (optional)
        conversion_note: Additional notes about the conversion process (optional)
        content_coverage: Fraction of source content captured (0.0-1.0)
        structure_preservation: Fraction of structure preserved (0.0-1.0)
        readability_score: Readability score normalized to 0.0-1.0
        total_characters: Total characters in original/extracted source
        extracted_characters: Characters extracted into markdown
        processing_time: Time spent in conversion step (sec)
        conversion_notes: List of conversion notes/messages
        
    Example:
        result = ConversionResult(
            success=True,
            conversion_score=85,
            conversion_feedback="Successfully converted PDF to markdown",
            conversion_note="Good text extraction quality"
        )
    """
    success: bool = Field(
        default=True,
        description="Whether the conversion completed successfully"
    )
    markdown_content: Optional[str] = Field(
        default=None,
        description="Converted markdown content"
    )
    conversion_score: int = Field(
        ge=0,
        le=100,
        description="Conversion quality score (0-100)"
    )
    conversion_feedback: Optional[str] = Field(
        default=None,
        description="Human-readable feedback about conversion quality"
    )
    conversion_note: Optional[str] = Field(
        default=None,
        description="Additional notes about the conversion process"
    )
    # Extended metrics used by services and tests
    content_coverage: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction of source content captured (0.0-1.0)"
    )
    structure_preservation: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction of structure preserved (0.0-1.0)"
    )
    readability_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Readability score normalized to 0.0-1.0"
    )
    total_characters: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total characters in original/extracted source"
    )
    extracted_characters: Optional[int] = Field(
        default=None,
        ge=0,
        description="Characters extracted into markdown"
    )
    processing_time: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Time spent in conversion step (seconds)"
    )
    conversion_notes: Optional[List[str]] = Field(
        default=None,
        description="List of conversion notes/messages"
    )


class LLMEvaluation(BaseModel):
    """
    Result model for LLM-based document evaluation.
    
    Contains detailed scores and feedback from language model evaluation
    of document quality across multiple dimensions.
    
    Attributes:
        clarity_score: Document clarity score (1-10)
        clarity_feedback: Feedback on document clarity
        completeness_score: Content completeness score (1-10)
        completeness_feedback: Feedback on content completeness
        relevance_score: Content relevance score (1-10)
        relevance_feedback: Feedback on content relevance
        markdown_score: Markdown quality score (1-10)
        markdown_feedback: Feedback on markdown formatting
        overall_feedback: Overall evaluation summary
        pass_recommendation: Recommendation (Pass/Fail)
        
    Example:
        evaluation = LLMEvaluation(
            clarity_score=8,
            clarity_feedback="Well-structured and easy to follow",
            completeness_score=7,
            completeness_feedback="Most key points covered",
            overall_feedback="Good quality document suitable for RAG"
        )
    """
    clarity_score: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Document clarity and readability score"
    )
    clarity_feedback: Optional[str] = Field(
        default=None,
        description="Detailed feedback on document clarity"
    )
    completeness_score: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Content completeness score"
    )
    completeness_feedback: Optional[str] = Field(
        default=None,
        description="Detailed feedback on content completeness"
    )
    relevance_score: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Content relevance score"
    )
    relevance_feedback: Optional[str] = Field(
        default=None,
        description="Detailed feedback on content relevance"
    )
    markdown_score: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Markdown formatting quality score"
    )
    markdown_feedback: Optional[str] = Field(
        default=None,
        description="Detailed feedback on markdown quality"
    )
    overall_feedback: Optional[str] = Field(
        default=None,
        description="Overall evaluation summary"
    )
    pass_recommendation: Optional[str] = Field(
        default=None,
        description="Overall recommendation (Pass/Fail)"
    )
    processing_time: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Time spent in LLM evaluation (seconds)"
    )
    token_usage: Optional[Dict[str, int]] = Field(
        default=None,
        description="Token usage statistics (e.g., {'prompt': 100, 'completion': 50})"
    )

    @validator('pass_recommendation')
    def validate_pass_recommendation(cls, v):
        """Validate that pass_recommendation is either Pass or Fail."""
        if v is not None and v.lower() not in ['pass', 'fail']:
            raise ValueError("pass_recommendation must be 'Pass' or 'Fail'")
        return v.title() if v else v  # Normalize to 'Pass' or 'Fail'


class ProcessingResult(BaseModel):
    """
    Complete result model for document processing operations.
    
    Combines conversion results, LLM evaluation, and metadata for
    a comprehensive processing outcome.
    
    Attributes:
        document_id: Unique identifier for the processed document
        filename: Original filename of the processed document
        status: Current processing status
        conversion_result: Results from document conversion
        llm_evaluation: Results from LLM quality evaluation (optional)
        is_rag_ready: Whether document meets quality thresholds
        processing_time: Total processing time in seconds
        processed_at: Timestamp of processing completion
        file_size: Size of processed markdown file in bytes
        summary: Brief document summary (optional)
        original_path: Local filesystem path to the original file (optional)
        markdown_path: Local filesystem path to the processed markdown (optional)
        vector_optimized: Whether vector optimization was applied
        processing_metadata: Arbitrary processing metadata map
        
    Example:
        result = ProcessingResult(
            document_id="doc_123",
            filename="report.pdf",
            status=ProcessingStatus.COMPLETED,
            is_rag_ready=True
        )
    """
    document_id: str = Field(
        description="Unique identifier for the processed document"
    )
    filename: str = Field(
        description="Original filename of the processed document"
    )
    status: ProcessingStatus = Field(
        default=ProcessingStatus.COMPLETED,
        description="Current processing status"
    )
    conversion_result: ConversionResult = Field(
        description="Results from document conversion process"
    )
    llm_evaluation: Optional[LLMEvaluation] = Field(
        default=None,
        description="Results from LLM quality evaluation"
    )
    is_rag_ready: bool = Field(
        description="Whether document meets RAG quality thresholds"
    )
    processing_time: float = Field(
        default=0.0,
        ge=0,
        description="Total processing time in seconds"
    )
    processed_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp of processing completion"
    )
    file_size: int = Field(
        default=0,
        ge=0,
        description="Size of processed markdown file in bytes"
    )
    summary: Optional[str] = Field(
        default=None,
        description="Brief document summary generated by LLM"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if processing failed"
    )
    # Paths and metadata used by services and routers
    original_path: Optional[Path] = Field(
        default=None,
        description="Filesystem path to original file"
    )
    markdown_path: Optional[Path] = Field(
        default=None,
        description="Filesystem path to processed markdown file"
    )
    vector_optimized: bool = Field(
        default=False,
        description="Whether vector optimization was applied"
    )
    processing_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Arbitrary processing metadata"
    )


# ============================================================================
# REQUEST MODELS
# ============================================================================

class FileUploadResponse(BaseModel):
    """
    Response model for file upload operations.
    
    Returned when a file is successfully uploaded to the system.
    
    Attributes:
        document_id: Unique identifier assigned to the uploaded file
        filename: Original filename of the uploaded file
        file_size: Size of uploaded file in bytes
        upload_time: Timestamp of upload completion
        message: Success message or additional information
        
    Example:
        response = FileUploadResponse(
            document_id="doc_123",
            filename="report.pdf",
            file_size=1048576,
            message="File uploaded successfully"
        )
    """
    document_id: str = Field(
        description="Unique identifier assigned to uploaded file"
    )
    filename: str = Field(
        description="Original filename of uploaded file"
    )
    file_size: int = Field(
        ge=0,
        description="Size of uploaded file in bytes"
    )
    upload_time: datetime = Field(
        description="Timestamp of upload completion"
    )
    message: str = Field(
        description="Success message or additional information"
    )


class DocumentEditRequest(BaseModel):
    """
    Request model for document content editing operations.
    
    Used when users want to edit processed document content with
    optional LLM-based improvements.
    
    Attributes:
        content: Updated markdown content
        improvement_prompt: Custom prompt for LLM improvement (optional)
        apply_vector_optimization: Whether to apply vector DB optimization
        
    Example:
        request = DocumentEditRequest(
            content="# Updated Title\\n\\nNew content...",
            improvement_prompt="Make it more concise",
            apply_vector_optimization=True
        )
    """
    content: str = Field(
        min_length=1,
        description="Updated markdown content"
    )
    improvement_prompt: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Custom prompt for LLM improvement"
    )
    apply_vector_optimization: bool = Field(
        default=False,
        description="Whether to apply vector database optimization"
    )


class BatchProcessingRequest(BaseModel):
    """
    Request model for batch processing operations.
    
    Used to process multiple documents simultaneously with
    consistent processing options.
    
    Attributes:
        document_ids: List of document IDs to process
        options: Processing options to apply to all documents
        
    Example:
        request = BatchProcessingRequest(
            document_ids=["doc1", "doc2", "doc3"],
            options=ProcessingOptions(auto_improve=True)
        )
    """
    document_ids: List[str] = Field(
        min_items=1,
        description="List of document IDs to process in batch"
    )
    options: Optional[ProcessingOptions] = Field(
        default_factory=ProcessingOptions,
        description="Processing options to apply to all documents"
    )


class BatchProcessingResult(BaseModel):
    """
    Result model for batch processing operations.
    
    Contains results from processing multiple documents simultaneously.
    
    Attributes:
        batch_id: Unique identifier for the batch operation
        results: List of individual processing results
        total_files: Total number of files processed
        successful_files: Number of successfully processed files
        failed_files: Number of files that failed processing
        processing_time: Total time for batch processing
        started_at: Timestamp when batch processing started
        completed_at: Timestamp when batch processing completed
        
    Example:
        batch_result = BatchProcessingResult(
            batch_id="batch_123",
            results=[result1, result2],
            total_files=2,
            successful_files=2,
            failed_files=0
        )
    """
    batch_id: str = Field(
        description="Unique identifier for batch operation"
    )
    results: List[ProcessingResult] = Field(
        description="List of individual processing results"
    )
    total_files: int = Field(
        ge=0,
        description="Total number of files in batch"
    )
    successful_files: int = Field(
        ge=0,
        description="Number of successfully processed files"
    )
    failed_files: int = Field(
        ge=0,
        description="Number of files that failed processing"
    )
    processing_time: float = Field(
        ge=0,
        description="Total batch processing time in seconds"
    )
    started_at: datetime = Field(
        description="Timestamp when batch processing started"
    )
    completed_at: datetime = Field(
        description="Timestamp when batch processing completed"
    )
    
    @validator('successful_files', 'failed_files')
    def validate_file_counts(cls, v, values):
        """Validate that file counts are consistent."""
        if 'total_files' in values and 'successful_files' in values:
            total = values['total_files']
            successful = values.get('successful_files', 0)
            if v + successful > total:
                raise ValueError("successful_files + failed_files cannot exceed total_files")
        return v


class BulkDownloadRequest(BaseModel):
    """
    Request model for bulk document download operations.
    
    Used to create ZIP archives of processed documents with various
    export options and filtering criteria.
    
    Attributes:
        document_ids: List of document IDs to include in download
        download_type: Type of archive to create
        include_summary: Whether to include processing summary
        include_combined: Whether to include combined markdown
        custom_filename: Custom filename for the archive
        
    Example:
        request = BulkDownloadRequest(
            document_ids=["doc1", "doc2", "doc3"],
            download_type=DownloadType.COMBINED,
            include_summary=True,
            custom_filename="my_documents.zip"
        )
    """
    document_ids: List[str] = Field(
        min_items=1,
        description="List of document IDs to include in download"
    )
    download_type: DownloadType = Field(
        default=DownloadType.INDIVIDUAL,
        description="Type of archive to create"
    )
    include_summary: bool = Field(
        default=True,
        description="Whether to include processing summary report"
    )
    include_combined: bool = Field(
        default=False,
        description="Whether to include combined markdown document"
    )
    custom_filename: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Custom filename for the archive"
    )


# ============================================================================
# FILE METADATA MODELS
# ============================================================================

class FileInfo(BaseModel):
    """
    Model representing file metadata information.
    
    Used for listing files with complete metadata including document IDs,
    file sizes, timestamps, and paths.
    
    Attributes:
        document_id: Unique identifier for the file (UUID for uploaded, filename for batch)
        filename: Original filename of the file
        original_filename: Original filename (same as filename for most cases)
        file_size: Size of the file in bytes
        upload_time: Timestamp when file was uploaded/created (Unix timestamp)
        file_path: Relative path to the file
        
    Example:
        file_info = FileInfo(
            document_id="550e8400-e29b-41d4-a716-446655440000",
            filename="report.pdf",
            original_filename="report.pdf",
            file_size=1048576,
            upload_time=1640995200,
            file_path="uploaded_files/550e8400-e29b-41d4-a716-446655440000_report.pdf"
        )
    """
    document_id: str = Field(
        description="Unique identifier for the file"
    )
    filename: str = Field(
        description="Original filename of the file"
    )
    original_filename: str = Field(
        description="Original filename (same as filename for most cases)"
    )
    file_size: int = Field(
        ge=0,
        description="Size of the file in bytes"
    )
    upload_time: int = Field(
        description="Timestamp when file was uploaded/created (Unix timestamp)"
    )
    file_path: str = Field(
        description="Relative path to the file"
    )


class FileListResponse(BaseModel):
    """
    Response model for file listing operations.
    
    Returns a list of FileInfo objects with metadata and count.
    
    Attributes:
        files: List of FileInfo objects with complete metadata
        count: Total number of files returned
        
    Example:
        response = FileListResponse(
            files=[file1, file2, file3],
            count=3
        )
    """
    files: List[FileInfo] = Field(
        description="List of FileInfo objects with complete metadata"
    )
    count: int = Field(
        ge=0,
        description="Total number of files returned"
    )


# ============================================================================
# ARCHIVE AND DOWNLOAD MODELS
# ============================================================================

class ZipArchiveInfo(BaseModel):
    """
    Information model for ZIP archive downloads.
    
    Provides metadata about generated ZIP archives including
    file counts, size information, and download details.
    
    Attributes:
        filename: Name of the generated ZIP file
        file_count: Number of files in the archive
        total_size: Total size of the archive in bytes
        created_at: Timestamp when archive was created
        download_url: URL for downloading the archive
        
    Example:
        archive = ZipArchiveInfo(
            filename="processed_documents.zip",
            file_count=5,
            total_size=2048576,
            created_at=datetime.now(),
            download_url="/download/temp_archive.zip"
        )
    """
    filename: str = Field(
        description="Name of the generated ZIP file"
    )
    file_count: int = Field(
        ge=0,
        description="Number of files included in the archive"
    )
    total_size: int = Field(
        ge=0,
        description="Total size of the archive in bytes"
    )
    created_at: datetime = Field(
        description="Timestamp when archive was created"
    )
    download_url: str = Field(
        description="Temporary URL for downloading the archive"
    )


# ============================================================================
# SYSTEM HEALTH AND STATUS MODELS
# ============================================================================

class LLMConnectionStatus(BaseModel):
    """
    Status model for LLM (Language Model) service connectivity.
    
    Provides information about the connection to external LLM services
    including health status, configuration, and error details.
    
    Attributes:
        connected: Whether connection to LLM service is active
        endpoint: LLM service endpoint URL
        model: Model identifier being used
        error: Error message if connection failed (optional)
        response_time: Average response time in seconds (optional)
        ssl_verify: Whether SSL verification is enabled
        timeout: Request timeout in seconds
        
    Example:
        status = LLMConnectionStatus(
            connected=True,
            endpoint="https://api.openai.com/v1",
            model="gpt-3.5-turbo",
            response_time=1.2,
            ssl_verify=True,
            timeout=30
        )
    """
    connected: bool = Field(
        description="Whether LLM service connection is active"
    )
    endpoint: str = Field(
        description="LLM service endpoint URL"
    )
    model: str = Field(
        description="LLM model identifier"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if connection failed"
    )
    response: Optional[str] = Field(
        default=None,
        description="Last successful response from LLM service"
    )
    ssl_verify: bool = Field(
        default=True,
        description="Whether SSL certificate verification is enabled"
    )
    timeout: int = Field(
        default=30,
        ge=1,
        description="Request timeout in seconds"
    )


class HealthStatus(BaseModel):
    """
    Comprehensive system health status model.
    
    Provides comprehensive information about the health and status
    of all system components.
    
    Attributes:
        status: Overall system status
        timestamp: Current timestamp
        version: API version
        llm_connected: Whether LLM service is available
        storage_available: Whether storage is accessible
        uptime: System uptime in seconds (optional)
        active_processes: Number of active processing operations
        
    Example:
        health = HealthStatus(
            status="healthy",
            version="2.0.0",
            llm_connected=True,
            storage_available=True
        )
    """
    status: str = Field(
        description="Overall system status (healthy/degraded/unhealthy)"
    )
    timestamp: datetime = Field(
        description="Current timestamp"
    )
    version: str = Field(
        description="Current API version"
    )
    llm_connected: bool = Field(
        description="Whether LLM service is available"
    )
    storage_available: bool = Field(
        description="Whether storage systems are accessible"
    )
    uptime: Optional[float] = Field(
        default=None,
        ge=0,
        description="System uptime in seconds"
    )
    active_processes: int = Field(
        default=0,
        ge=0,
        description="Number of active processing operations"
    )


# ============================================================================
# ERROR MODELS
# ============================================================================

class ErrorResponse(BaseModel):
    """
    Standard error response model for API errors.
    
    Provides consistent error information across all API endpoints
    with proper error categorization and debugging information.
    
    Attributes:
        error: Error category or type
        detail: Detailed error message
        timestamp: When the error occurred
        request_id: Unique identifier for the request (optional)
        
    Example:
        error = ErrorResponse(
            error="Validation Error",
            detail="File size exceeds maximum limit",
            timestamp=datetime.now()
        )
    """
    error: str = Field(
        description="Error category or type"
    )
    detail: Optional[str] = Field(
        default=None,
        description="Detailed error message"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when error occurred"
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Unique identifier for the request"
    )


# ============================================================================
# UTILITY MODELS
# ============================================================================

class SupportedFormatsResponse(BaseModel):
    """
    Response model for supported file formats information.
    
    Provides information about file formats supported by the system
    including extensions, size limits, and processing capabilities.
    
    Attributes:
        supported_extensions: List of supported file extensions
        max_file_size: Maximum file size in bytes
        description: Description of supported formats
        ocr_extensions: File extensions that require OCR processing
        
    Example:
        formats = SupportedFormatsResponse(
            supported_extensions=[".pdf", ".docx", ".png"],
            max_file_size=52428800,
            description="Supported file formats for processing"
        )
    """
    supported_extensions: List[str] = Field(
        description="List of supported file extensions"
    )
    max_file_size: int = Field(
        ge=0,
        description="Maximum file size in bytes"
    )
    description: str = Field(
        default="Supported file formats for document processing",
        description="Description of supported formats and capabilities"
    )
    ocr_extensions: List[str] = Field(
        default=[".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"],
        description="File extensions requiring OCR processing"
    )


class SystemResetResponse(BaseModel):
    """
    Response model for system reset operations.
    
    Provides information about what was cleared during a system reset
    including file counts and storage statistics.
    
    Attributes:
        success: Whether the reset operation succeeded
        message: Success or failure message
        timestamp: When the reset was performed
        files_cleared: Dictionary of cleared file counts by category
        storage_cleared: Whether in-memory storage was cleared
        
    Example:
        reset_response = SystemResetResponse(
            success=True,
            message="System reset successfully",
            files_cleared={"uploaded": 5, "processed": 3}
        )
    """
    success: bool = Field(
        description="Whether reset operation succeeded"
    )
    message: str = Field(
        description="Success or failure message"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when reset was performed"
    )
    files_cleared: Dict[str, int] = Field(
        default_factory=dict,
        description="Dictionary of cleared file counts by category"
    )
    storage_cleared: bool = Field(
        default=False,
        description="Whether in-memory storage was cleared"
    )


# ============================================================================
# VALIDATION UTILITIES
# ============================================================================

def validate_document_id(document_id: str) -> bool:
    """
    Validate document ID format.
    
    Args:
        document_id: Document ID to validate
        
    Returns:
        bool: Whether the document ID is valid
        
    Note:
        Document IDs should be alphanumeric with optional hyphens and underscores.
    """
    if not document_id or not isinstance(document_id, str):
        return False
    
    # Allow alphanumeric characters, hyphens, and underscores
    return all(c.isalnum() or c in '-_' for c in document_id) and len(document_id) <= 100


def validate_filename(filename: str) -> bool:
    """
    Validate filename format and safety.
    
    Args:
        filename: Filename to validate
        
    Returns:
        bool: Whether the filename is valid and safe
        
    Note:
        Checks for path traversal attempts and invalid characters.
    """
    if not filename or not isinstance(filename, str):
        return False
    
    # Check for path traversal attempts
    if '..' in filename or '/' in filename or '\\' in filename:
        return False
    
    # Check filename length
    if len(filename) > 255:
        return False
    
    # Check for valid characters (basic validation)
    invalid_chars = '<>:"|?*'
    return not any(char in filename for char in invalid_chars)
