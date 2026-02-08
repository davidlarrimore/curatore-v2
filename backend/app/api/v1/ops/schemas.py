from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


# =========================================================================
# RUN / LOG MODELS
# =========================================================================


class RunLogEventResponse(BaseModel):
    """Run log event response model."""
    id: UUID = Field(..., description="Log event UUID")
    run_id: UUID = Field(..., description="Run UUID")
    level: str = Field(..., description="Log level (INFO, WARN, ERROR)")
    event_type: str = Field(..., description="Event type (start, progress, retry, error, summary)")
    message: str = Field(..., description="Human-readable message")
    context: Optional[Dict[str, Any]] = Field(None, description="Machine-readable context")
    created_at: datetime = Field(..., description="Event timestamp")

    class Config:
        from_attributes = True


class RunResponse(BaseModel):
    """Run response model."""
    id: UUID = Field(..., description="Run UUID")
    organization_id: UUID = Field(..., description="Organization UUID")
    run_type: str = Field(..., description="Run type (extraction, processing, experiment, system_maintenance, sync)")
    origin: str = Field(..., description="Run origin (user, system, scheduled)")
    status: str = Field(..., description="Run status (pending, running, completed, failed, cancelled)")
    input_asset_ids: List[str] = Field(default_factory=list, description="Input asset UUIDs")
    config: Dict[str, Any] = Field(default_factory=dict, description="Run configuration")
    progress: Optional[Dict[str, Any]] = Field(None, description="Progress tracking")
    results_summary: Optional[Dict[str, Any]] = Field(None, description="Results summary")
    error_message: Optional[str] = Field(None, description="Error message (if failed)")
    created_at: datetime = Field(..., description="Creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    last_activity_at: Optional[datetime] = Field(None, description="Last activity timestamp (for timeout tracking)")
    created_by: Optional[UUID] = Field(None, description="User UUID who created the run")

    # Queue info (for pending runs)
    queue_position: Optional[int] = Field(None, description="Position in queue (1-indexed, only for pending runs)")
    queue_priority: Optional[int] = Field(None, description="Queue priority (0=normal, 1=high)")

    class Config:
        from_attributes = True


class RunWithLogsResponse(BaseModel):
    """Run with log events."""
    run: RunResponse
    logs: List[RunLogEventResponse] = Field(default_factory=list)


class RunsListResponse(BaseModel):
    """Paginated runs list response."""
    items: List[RunResponse]
    total: int
    limit: int
    offset: int


# =========================================================================
# UNIFIED QUEUE MODELS
# =========================================================================


class ExtractionQueueInfo(BaseModel):
    """Extraction queue counts (database-backed, source of truth)."""
    pending: int = Field(..., description="Extractions waiting in queue")
    submitted: int = Field(..., description="Extractions submitted to worker")
    running: int = Field(..., description="Extractions currently processing")
    stale: int = Field(default=0, description="Extractions that appear stuck (no heartbeat)")
    max_concurrent: int = Field(..., description="Maximum concurrent extractions")


class CeleryQueuesInfo(BaseModel):
    """DEPRECATED: Celery queue counts are unreliable. Use ExtractionQueueInfo instead.

    These fields are kept for backwards compatibility but always return 0.
    The WorkersInfo.active field indicates whether workers are online.
    """
    processing_priority: int = Field(default=0, description="High priority queue length")
    extraction: int = Field(default=0, description="Extraction queue length")
    enhancement: int = Field(default=0, description="Enhancement queue length (Docling)")
    sam: int = Field(default=0, description="SAM.gov queue length")
    scrape: int = Field(default=0, description="Web scrape queue length")
    sharepoint: int = Field(default=0, description="SharePoint queue length")
    salesforce: int = Field(default=0, description="Salesforce queue length")
    pipeline: int = Field(default=0, description="Pipeline queue length")
    maintenance: int = Field(default=0, description="Maintenance queue length")


class ThroughputInfo(BaseModel):
    """Extraction throughput metrics."""
    per_minute: float = Field(..., description="Extractions completed per minute")
    avg_extraction_seconds: Optional[float] = Field(None, description="Average extraction time in seconds")


class Recent5mInfo(BaseModel):
    """Last 5 minutes statistics (all job types)."""
    completed: int = Field(default=0, description="Jobs completed in last 5 minutes")
    failed: int = Field(default=0, description="Jobs failed in last 5 minutes")
    timed_out: int = Field(default=0, description="Jobs timed out in last 5 minutes")


class Recent24hInfo(BaseModel):
    """Last 24 hours statistics."""
    completed: int = Field(..., description="Extractions completed in last 24h")
    failed: int = Field(..., description="Extractions failed in last 24h")
    timed_out: int = Field(..., description="Extractions timed out in last 24h")


class WorkersInfo(BaseModel):
    """Celery worker information."""
    active: int = Field(..., description="Number of active workers")
    tasks_running: int = Field(..., description="Total tasks currently running")
    tasks_reserved: int = Field(default=0, description="Tasks prefetched by workers, waiting to execute")


class UnifiedQueueStatsResponse(BaseModel):
    """
    Unified queue statistics response.

    Consolidates all queue information into a single response:
    - extraction_queue: Database-tracked queue counts
    - celery_queues: Redis queue lengths
    - throughput: Processing rate metrics
    - recent_5m: Last 5 minutes statistics (all job types)
    - recent_24h: Last 24 hours statistics
    - workers: Worker status
    """
    extraction_queue: ExtractionQueueInfo
    celery_queues: CeleryQueuesInfo
    throughput: ThroughputInfo
    recent_5m: Recent5mInfo
    recent_24h: Recent24hInfo
    workers: WorkersInfo

    class Config:
        json_schema_extra = {
            "example": {
                "extraction_queue": {
                    "pending": 5,
                    "submitted": 2,
                    "running": 3,
                    "max_concurrent": 10
                },
                "celery_queues": {
                    "processing_priority": 0,
                    "extraction": 5,
                    "sam": 0,
                    "scrape": 0,
                    "sharepoint": 0,
                    "maintenance": 2
                },
                "throughput": {
                    "per_minute": 2.4,
                    "avg_extraction_seconds": 45.2
                },
                "recent_24h": {
                    "completed": 142,
                    "failed": 3,
                    "timed_out": 1
                },
                "workers": {
                    "active": 2,
                    "tasks_running": 3
                }
            }
        }


class AssetQueueInfoResponse(BaseModel):
    """Queue information for a specific asset."""
    unified_status: str = Field(..., description="Unified status (queued, submitted, processing, completed, failed, timed_out, cancelled)")
    asset_id: str = Field(..., description="Asset UUID")
    run_id: Optional[str] = Field(None, description="Current extraction run UUID")
    in_queue: bool = Field(..., description="Whether extraction is queued/processing")
    queue_position: Optional[int] = Field(None, description="Position in queue (if pending)")
    total_pending: Optional[int] = Field(None, description="Total items in queue")
    estimated_wait_seconds: Optional[float] = Field(None, description="Estimated wait time")
    submitted_to_celery: Optional[bool] = Field(None, description="Whether task has been sent to Celery")
    timeout_at: Optional[str] = Field(None, description="Task timeout timestamp")
    celery_task_id: Optional[str] = Field(None, description="Celery task ID")
    extractor_version: Optional[str] = Field(None, description="Extraction service version")

    class Config:
        json_schema_extra = {
            "example": {
                "unified_status": "queued",
                "asset_id": "123e4567-e89b-12d3-a456-426614174000",
                "run_id": "456e4567-e89b-12d3-a456-426614174000",
                "in_queue": True,
                "queue_position": 3,
                "total_pending": 10,
                "estimated_wait_seconds": 135.0,
                "submitted_to_celery": False,
                "timeout_at": None,
                "celery_task_id": None,
                "extractor_version": "markitdown-1.0"
            }
        }


__all__ = [
    # Run / Log models
    "RunLogEventResponse",
    "RunResponse",
    "RunWithLogsResponse",
    "RunsListResponse",
    # Queue models
    "ExtractionQueueInfo",
    "CeleryQueuesInfo",
    "ThroughputInfo",
    "Recent5mInfo",
    "Recent24hInfo",
    "WorkersInfo",
    "UnifiedQueueStatsResponse",
    "AssetQueueInfoResponse",
]
