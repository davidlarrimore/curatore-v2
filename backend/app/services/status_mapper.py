"""
Unified Status Mapper for Curatore v2.

Provides a single source of truth for extraction/processing status across
the application. Maps Run, Asset, and ExtractionResult statuses to a
canonical unified status.
"""

from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..database.models import Asset, Run, ExtractionResult


class UnifiedStatus(str, Enum):
    """Canonical extraction/processing status values."""
    QUEUED = "queued"           # Run.pending - waiting in queue
    SUBMITTED = "submitted"     # Run.submitted - sent to worker
    PROCESSING = "processing"   # Run.running - actively processing
    COMPLETED = "completed"     # Run.completed, Asset.ready
    FAILED = "failed"           # Run.failed, Asset.failed
    TIMED_OUT = "timed_out"     # Run.timed_out
    CANCELLED = "cancelled"     # Run.cancelled


# Mapping from Run status to UnifiedStatus
RUN_STATUS_MAP = {
    "pending": UnifiedStatus.QUEUED,
    "submitted": UnifiedStatus.SUBMITTED,
    "running": UnifiedStatus.PROCESSING,
    "completed": UnifiedStatus.COMPLETED,
    "failed": UnifiedStatus.FAILED,
    "timed_out": UnifiedStatus.TIMED_OUT,
    "cancelled": UnifiedStatus.CANCELLED,
}

# Mapping from Asset status to UnifiedStatus
ASSET_STATUS_MAP = {
    "pending": UnifiedStatus.QUEUED,
    "ready": UnifiedStatus.COMPLETED,
    "failed": UnifiedStatus.FAILED,
    "inactive": UnifiedStatus.COMPLETED,  # Inactive but extracted
    "deleted": UnifiedStatus.FAILED,  # Treat deleted as failed for UI
}


def get_unified_status(
    asset: Optional["Asset"] = None,
    run: Optional["Run"] = None,
    extraction_result: Optional["ExtractionResult"] = None,
) -> UnifiedStatus:
    """
    Get the unified status for an extraction.

    Priority:
    1. If a Run is provided and in-progress, use its status
    2. If an ExtractionResult exists, check its status
    3. Fall back to Asset status

    Args:
        asset: The Asset object (optional)
        run: The most recent extraction Run (optional)
        extraction_result: The ExtractionResult (optional)

    Returns:
        UnifiedStatus enum value
    """
    # If we have a run in progress, prioritize its status
    if run and run.status in ("pending", "submitted", "running"):
        return RUN_STATUS_MAP.get(run.status, UnifiedStatus.QUEUED)

    # If run completed/failed, use its status
    if run:
        return RUN_STATUS_MAP.get(run.status, UnifiedStatus.FAILED)

    # If we have an extraction result, check its status
    if extraction_result:
        if extraction_result.status == "completed":
            return UnifiedStatus.COMPLETED
        elif extraction_result.status == "failed":
            return UnifiedStatus.FAILED
        elif extraction_result.status == "pending":
            return UnifiedStatus.QUEUED

    # Fall back to asset status
    if asset:
        return ASSET_STATUS_MAP.get(asset.status, UnifiedStatus.QUEUED)

    # Default
    return UnifiedStatus.QUEUED


def get_status_display_info(status: UnifiedStatus) -> dict:
    """
    Get display information for a unified status.

    Returns dict with:
        - label: Human-readable label
        - color: Tailwind color theme (blue, indigo, emerald, red, amber, gray)
        - icon: Lucide icon name
    """
    display_map = {
        UnifiedStatus.QUEUED: {
            "label": "Queued",
            "color": "blue",
            "icon": "Clock",
        },
        UnifiedStatus.SUBMITTED: {
            "label": "Starting",
            "color": "blue",
            "icon": "Loader2",
        },
        UnifiedStatus.PROCESSING: {
            "label": "Processing",
            "color": "indigo",
            "icon": "Loader2",
        },
        UnifiedStatus.COMPLETED: {
            "label": "Ready",
            "color": "emerald",
            "icon": "CheckCircle",
        },
        UnifiedStatus.FAILED: {
            "label": "Failed",
            "color": "red",
            "icon": "XCircle",
        },
        UnifiedStatus.TIMED_OUT: {
            "label": "Timed Out",
            "color": "amber",
            "icon": "Clock",
        },
        UnifiedStatus.CANCELLED: {
            "label": "Cancelled",
            "color": "gray",
            "icon": "XCircle",
        },
    }
    return display_map.get(status, display_map[UnifiedStatus.QUEUED])


def is_active_status(status: UnifiedStatus) -> bool:
    """Check if status represents an active/in-progress extraction."""
    return status in (UnifiedStatus.QUEUED, UnifiedStatus.SUBMITTED, UnifiedStatus.PROCESSING)


def is_terminal_status(status: UnifiedStatus) -> bool:
    """Check if status represents a terminal/completed state."""
    return status in (UnifiedStatus.COMPLETED, UnifiedStatus.FAILED, UnifiedStatus.TIMED_OUT, UnifiedStatus.CANCELLED)
