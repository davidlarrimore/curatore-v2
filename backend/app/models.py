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
        language: ISO 639-3 language code(s) for OCR recognition
        psm: Page Segmentation Mode for Tesseract OCR engine
        
    Example:
        ocr_settings = OCRSettings(language="eng+spa", psm=6)
    """
    language: str = Field(
        default="eng",
        description="Language code(s) for OCR. Multiple languages: 'eng+spa'"
    )
    psm: int = Field(
        default=3,
        ge=0,
        le=13,
        description="Page Segmentation Mode (0-13). 3=auto, 6=uniform block"
    )
    
    @validator('language')
    def validate_language(cls, v):
        """Validate language code format."""
        if not v or not isinstance(v, str):
            raise ValueError("Language must be a non-empty string")
        # Basic validation for language code format
        if not all(c.isalpha() or c == '+' for c in v):
            raise ValueError("Language code must contain only letters and '+' separator")
        return v.lower()


class QualityThresholds(BaseModel):
    """
    Configuration model for quality assessment thresholds.
    
    Defines minimum scores required for documents to be considered
    "RAG Ready" and suitable for production use.
    
    Attributes:
        conversion_quality: Minimum conversion score (0-100)
        clarity_score: Minimum LLM clarity evaluation (1-10)
        completeness_score: Minimum LLM completeness evaluation (1-10)
        relevance_score: Minimum LLM relevance evaluation (1-10)
        markdown_quality: Minimum markdown formatting score (1-10)
        
    Example:
        thresholds = QualityThresholds(
            conversion_quality=80,
            clarity_score=8,
            completeness_score=7
        )
    """
    conversion_quality: int = Field(
        default=70,
        ge=0,
        le=100,
        description="Minimum conversion quality score (0-100)"
    )
    clarity_score: int = Field(
        default=7,
        ge=1,
        le=10,
        description="Minimum clarity evaluation score (1-10)"
    )
    completeness_score: int = Field(
        default=7,
        ge=1,
        le=10,
        description="Minimum completeness evaluation score (1-10)"
    )
    relevance_score: int = Field(
        default=7,
        ge=1,
        le=10,
        description="Minimum relevance evaluation score (1-10)"
    )
    markdown_quality: int = Field(
        default=7,
        ge=1,
        le=10,
        description="Minimum markdown quality score (1-10)"
    )


class ProcessingOptions(BaseModel):
    """
    Configuration model for document processing options.
    
    Allows customization of the document processing pipeline including
    quality thresholds, OCR settings, and optimization preferences.
    
    Attributes:
        auto_improve: Whether to automatically improve documents with LLM
        vector_optimize: Whether to optimize for vector database storage
        ocr_settings: OCR configuration for image processing
        quality_thresholds: Quality assessment thresholds
        custom_prompt: Custom improvement prompt for LLM enhancement
        
    Example:
        options = ProcessingOptions(
            auto_improve=True,
            vector_optimize=True,
            custom_prompt="Focus on technical accuracy"
        )
    """
    auto_improve: bool = Field(
        default=True,
        description="Automatically improve documents using LLM"
    )
    vector_optimize: bool = Field(
        default=True,
        description="Optimize document structure for vector databases"
    )
    ocr_settings: Optional[OCRSettings] = Field(
        default=None,
        description="OCR configuration for image processing"
    )
    quality_thresholds: Optional[QualityThresholds] = Field(
        default=None,
        description="Custom quality thresholds for assessment"
    )
    custom_prompt: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Custom improvement prompt for LLM enhancement"
    )


# ============================================================================
# PROCESSING RESULT MODELS
# ============================================================================

class ConversionResult(BaseModel):
    """
    Result model for document conversion operations.
    
    Contains the converted markdown content and quality metrics
    from the document conversion process.
    
    Attributes:
        markdown_content: The converted markdown text
        conversion_score: Quality score for the conversion (0-100)
        conversion_feedback: Detailed feedback on conversion quality
        word_count: Number of words in the converted content
        char_count: Number of characters in the converted content
        
    Example:
        result = ConversionResult(
            markdown_content="# Document Title\\n\\nContent...",
            conversion_score=85,
            conversion_feedback="Good structure preservation"
        )
    """
    markdown_content: str = Field(
        description="Converted markdown content"
    )
    conversion_score: int = Field(
        ge=0,
        le=100,
        description="Conversion quality score (0-100)"
    )
    conversion_feedback: str = Field(
        description="Detailed feedback on conversion quality"
    )
    word_count: int = Field(
        ge=0,
        description="Number of words in converted content"
    )
    char_count: int = Field(
        ge=0,
        description="Number of characters in converted content"
    )
    processing_time: float = Field(
        ge=0,
        description="Time taken for conversion in seconds"
    )


class LLMEvaluation(BaseModel):
    """
    Result model for LLM-based document evaluation.
    
    Contains scores and feedback from LLM analysis of document quality,
    including assessments of clarity, completeness, relevance, and formatting.
    
    Attributes:
        clarity_score: Document clarity and readability (1-10)
        clarity_feedback: Detailed feedback on clarity
        completeness_score: Information completeness (1-10)
        completeness_feedback: Detailed feedback on completeness
        relevance_score: Content relevance and focus (1-10)
        relevance_feedback: Detailed feedback on relevance
        markdown_score: Markdown formatting quality (1-10)
        markdown_feedback: Detailed feedback on formatting
        overall_feedback: General improvement suggestions
        pass_recommendation: Whether document passes quality standards
        evaluation_time: Time taken for evaluation in seconds
        
    Example:
        evaluation = LLMEvaluation(
            clarity_score=8,
            clarity_feedback="Well-structured with clear headings",
            completeness_score=7,
            pass_recommendation="Pass"
        )
    """
    clarity_score: int = Field(
        ge=1,
        le=10,
        description="Document clarity and readability score (1-10)"
    )
    clarity_feedback: str = Field(
        description="Detailed feedback on document clarity"
    )
    completeness_score: int = Field(
        ge=1,
        le=10,
        description="Information completeness score (1-10)"
    )
    completeness_feedback: str = Field(
        description="Detailed feedback on information completeness"
    )
    relevance_score: int = Field(
        ge=1,
        le=10,
        description="Content relevance and focus score (1-10)"
    )
    relevance_feedback: str = Field(
        description="Detailed feedback on content relevance"
    )
    markdown_score: int = Field(
        ge=1,
        le=10,
        description="Markdown formatting quality score (1-10)"
    )
    markdown_feedback: str = Field(
        description="Detailed feedback on markdown formatting"
    )
    overall_feedback: str = Field(
        description="General improvement suggestions and summary"
    )
    pass_recommendation: str = Field(
        description="Whether document passes quality standards (Pass/Fail)"
    )
    evaluation_time: float = Field(
        default=0.0,
        ge=0,
        description="Time taken for LLM evaluation in seconds"
    )
    
    @validator('pass_recommendation')
    def validate_pass_recommendation(cls, v):
        """Validate pass recommendation format."""
        if v.lower() not in ['pass', 'fail']:
            raise ValueError("pass_recommendation must be 'Pass' or 'Fail'")
        return v.title()  # Normalize to 'Pass' or 'Fail'


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
        ge=0,
        description="Total processing time in seconds"
    )
    processed_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp of processing completion"
    )
    file_size: int = Field(
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
        file_paths: List of file paths to process
        processing_options: Configuration for batch processing
        parallel_processing: Whether to process files in parallel
        
    Example:
        request = BatchProcessingRequest(
            file_paths=["doc1.pdf", "doc2.docx"],
            parallel_processing=True
        )
    """
    file_paths: List[str] = Field(
        min_items=1,
        description="List of file paths to process"
    )
    processing_options: Optional[ProcessingOptions] = Field(
        default=None,
        description="Configuration for batch processing"
    )
    parallel_processing: bool = Field(
        default=True,
        description="Whether to process files in parallel"
    )


class BulkDownloadRequest(BaseModel):
    """
    Request model for bulk download operations.
    
    Used to download multiple documents as ZIP archives with
    various formatting and filtering options.
    
    Attributes:
        document_ids: List of document IDs to include in download
        download_type: Type of bulk download to create
        include_summary: Whether to include processing summary
        include_combined: Whether to include combined markdown file
        custom_filename: Custom filename for the ZIP archive
        
    Example:
        request = BulkDownloadRequest(
            document_ids=["doc1", "doc2", "doc3"],
            download_type=DownloadType.RAG_READY,
            include_summary=True
        )
    """
    document_ids: List[str] = Field(
        min_items=1,
        description="List of document IDs to include"
    )
    download_type: DownloadType = Field(
        default=DownloadType.INDIVIDUAL,
        description="Type of bulk download to create"
    )
    include_summary: bool = Field(
        default=True,
        description="Whether to include processing summary"
    )
    include_combined: bool = Field(
        default=False,
        description="Whether to include combined markdown file"
    )
    custom_filename: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Custom filename for ZIP archive"
    )


# ============================================================================
# RESPONSE MODELS
# ============================================================================

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


class ZipArchiveInfo(BaseModel):
    """
    Information model for ZIP archive downloads.
    
    Provides metadata about generated ZIP archives including
    file counts, size information, and download details.
    
    Attributes:
        filename: Name of the generated ZIP file
        file_count: Number of files included in the archive
        total_size: Total size of the ZIP archive in bytes
        created_at: Timestamp when archive was created
        expires_at: Timestamp when archive expires (optional)
        download_url: URL for downloading the archive (optional)
        
    Example:
        archive_info = ZipArchiveInfo(
            filename="curatore_export_20240827_143022.zip",
            file_count=5,
            total_size=2048576
        )
    """
    filename: str = Field(
        description="Name of the generated ZIP file"
    )
    file_count: int = Field(
        ge=0,
        description="Number of files included in archive"
    )
    total_size: int = Field(
        ge=0,
        description="Total size of ZIP archive in bytes"
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when archive was created"
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when archive expires"
    )
    download_url: Optional[str] = Field(
        default=None,
        description="URL for downloading the archive"
    )


# ============================================================================
# SYSTEM MODELS
# ============================================================================

class LLMConnectionStatus(BaseModel):
    """
    Status model for LLM service connection.
    
    Provides information about the current state of the LLM service
    connection including connectivity, configuration, and performance.
    
    Attributes:
        connected: Whether LLM service is available
        endpoint: LLM API endpoint being used
        model: Model name being used for operations
        ssl_verify: Whether SSL verification is enabled
        timeout: Request timeout in seconds
        error: Error message if connection failed (optional)
        response_time: Last response time in seconds (optional)
        
    Example:
        status = LLMConnectionStatus(
            connected=True,
            endpoint="https://api.openai.com/v1",
            model="gpt-4o-mini",
            ssl_verify=True,
            timeout=60.0
        )
    """
    connected: bool = Field(
        description="Whether LLM service is available"
    )
    endpoint: str = Field(
        description="LLM API endpoint being used"
    )
    model: str = Field(
        description="Model name being used for operations"
    )
    ssl_verify: bool = Field(
        description="Whether SSL verification is enabled"
    )
    timeout: float = Field(
        ge=0,
        description="Request timeout in seconds"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if connection failed"
    )
    response_time: Optional[float] = Field(
        default=None,
        ge=0,
        description="Last response time in seconds"
    )


class HealthStatus(BaseModel):
    """
    Overall system health status model.
    
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