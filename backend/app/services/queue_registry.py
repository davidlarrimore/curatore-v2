"""
Queue Registry Service for Curatore v2.

Provides a centralized, object-oriented registry of all job queue types.
This enables the unified Job Manager to handle all job types consistently
(extractions, SAM pulls, web scrapes, SharePoint syncs, maintenance tasks).

ARCHITECTURE:
- Queue types are defined PROGRAMMATICALLY in code (this file)
- config.yml only provides PARAMETER OVERRIDES (max_concurrent, timeout, etc.)
- Adding a new queue = adding a new QueueDefinition subclass or registration

ADDING A NEW QUEUE TYPE:
1. Create a new QueueDefinition (subclass or instance)
2. Register it with queue_registry.register()
3. Add Celery task routing in celery_app.py
4. Done! The Job Manager UI will automatically show the new queue type.

Example - Adding a Google Drive sync queue:

    class GoogleDriveSyncQueue(QueueDefinition):
        queue_type = "google_drive"
        celery_queue = "google_drive"
        label = "Google Drive"
        description = "Google Drive document synchronization"
        icon = "cloud"
        color = "blue"
        can_cancel = True

    queue_registry.register(GoogleDriveSyncQueue())
"""

import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Type

logger = logging.getLogger("curatore.services.queue_registry")


@dataclass
class QueueDefinition:
    """
    Base definition for a job queue type.

    Extend this class or create instances to define new queue types.
    All queue behavior and capabilities are defined here in code.

    Attributes:
        queue_type: Unique identifier for this queue (e.g., "extraction", "sam")
        celery_queue: Celery queue name for task routing
        run_type_aliases: Alternative run_type values that map to this queue

        # Capabilities - what actions are allowed
        can_cancel: Whether jobs can be cancelled
        can_boost: Whether job priority can be boosted
        can_retry: Whether failed jobs can be retried

        # Display metadata for UI
        label: Human-readable name
        description: Short description
        icon: Lucide icon name
        color: Tailwind color name

        # Default processing parameters (overridable via config.yml)
        default_max_concurrent: Default max concurrent (None = unlimited)
        default_timeout_seconds: Default timeout
        default_submission_interval: Seconds between queue processing
        default_duplicate_cooldown: Seconds before allowing duplicate
    """

    # Identity
    queue_type: str
    celery_queue: str
    run_type_aliases: List[str] = field(default_factory=list)

    # Capabilities (defined in code, not configurable)
    can_cancel: bool = False
    can_boost: bool = False
    can_retry: bool = False

    # Display metadata
    label: str = ""
    description: str = ""
    icon: str = "activity"
    color: str = "gray"

    # Default parameters (can be overridden via config.yml)
    default_max_concurrent: Optional[int] = None  # None = unlimited
    default_timeout_seconds: int = 600
    default_submission_interval: int = 5
    default_duplicate_cooldown: int = 30

    # Runtime state (set by registry after config overrides)
    enabled: bool = True
    _max_concurrent: Optional[int] = field(default=None, repr=False)
    _timeout_seconds: Optional[int] = field(default=None, repr=False)
    _submission_interval: Optional[int] = field(default=None, repr=False)
    _duplicate_cooldown: Optional[int] = field(default=None, repr=False)

    def __post_init__(self):
        """Initialize runtime values from defaults."""
        if self._max_concurrent is None:
            self._max_concurrent = self.default_max_concurrent
        if self._timeout_seconds is None:
            self._timeout_seconds = self.default_timeout_seconds
        if self._submission_interval is None:
            self._submission_interval = self.default_submission_interval
        if self._duplicate_cooldown is None:
            self._duplicate_cooldown = self.default_duplicate_cooldown

    @property
    def max_concurrent(self) -> Optional[int]:
        """Current max concurrent (may be overridden by config)."""
        return self._max_concurrent

    @property
    def timeout_seconds(self) -> int:
        """Current timeout in seconds (may be overridden by config)."""
        return self._timeout_seconds or self.default_timeout_seconds

    @property
    def submission_interval(self) -> int:
        """Current submission interval (may be overridden by config)."""
        return self._submission_interval or self.default_submission_interval

    @property
    def duplicate_cooldown(self) -> int:
        """Current duplicate cooldown (may be overridden by config)."""
        return self._duplicate_cooldown or self.default_duplicate_cooldown

    @property
    def is_throttled(self) -> bool:
        """Whether this queue has concurrency throttling enabled."""
        return self._max_concurrent is not None

    def apply_config_overrides(self, overrides: Dict[str, Any]):
        """
        Apply runtime configuration overrides from config.yml.

        Only specific parameters can be overridden:
        - max_concurrent
        - timeout_seconds
        - submission_interval
        - duplicate_cooldown
        - enabled
        """
        if "max_concurrent" in overrides:
            self._max_concurrent = overrides["max_concurrent"]
        if "timeout_seconds" in overrides:
            self._timeout_seconds = overrides["timeout_seconds"]
        if "submission_interval" in overrides:
            self._submission_interval = overrides["submission_interval"]
        if "duplicate_cooldown" in overrides:
            self._duplicate_cooldown = overrides["duplicate_cooldown"]
        if "enabled" in overrides:
            self.enabled = overrides["enabled"]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "queue_type": self.queue_type,
            "celery_queue": self.celery_queue,
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "can_cancel": self.can_cancel,
            "can_boost": self.can_boost,
            "can_retry": self.can_retry,
            "max_concurrent": self.max_concurrent,
            "timeout_seconds": self.timeout_seconds,
            "is_throttled": self.is_throttled,
            "enabled": self.enabled,
        }


# =============================================================================
# QUEUE TYPE DEFINITIONS
# =============================================================================
# Each queue type is defined as a class or instance here.
# This is the ONLY place where queue types should be defined.
# =============================================================================


class ExtractionQueue(QueueDefinition):
    """Document extraction queue - converts documents to Markdown."""

    def __init__(self):
        super().__init__(
            queue_type="extraction",
            celery_queue="extraction",
            run_type_aliases=[],
            can_cancel=True,
            can_boost=True,
            can_retry=True,
            label="Extraction",
            description="Document to Markdown conversion",
            icon="file-text",
            color="blue",
            default_max_concurrent=10,  # Throttled by default
            default_timeout_seconds=600,
            default_submission_interval=5,
            default_duplicate_cooldown=30,
        )


class SamQueue(QueueDefinition):
    """SAM.gov federal opportunities queue."""

    def __init__(self):
        super().__init__(
            queue_type="sam",
            celery_queue="sam",
            run_type_aliases=["sam_pull"],
            can_cancel=False,
            can_boost=False,
            can_retry=False,
            label="SAM.gov",
            description="Federal opportunity data pulls",
            icon="building-2",
            color="amber",
            default_max_concurrent=None,  # Unlimited by default
            default_timeout_seconds=1800,
        )


class ScrapeQueue(QueueDefinition):
    """Web scraping and crawling queue."""

    def __init__(self):
        super().__init__(
            queue_type="scrape",
            celery_queue="scrape",
            run_type_aliases=["scrape_crawl", "scrape_delete"],
            can_cancel=True,  # Enable cancellation via Celery revoke
            can_boost=False,
            can_retry=False,
            label="Web Scrape",
            description="Web scraping and crawling",
            icon="globe",
            color="emerald",
            default_max_concurrent=None,  # Unlimited by default
            default_timeout_seconds=3600,
        )


class SharePointQueue(QueueDefinition):
    """SharePoint document synchronization queue."""

    def __init__(self):
        super().__init__(
            queue_type="sharepoint",
            celery_queue="sharepoint",
            run_type_aliases=["sharepoint_sync", "sharepoint_import", "sharepoint_delete"],
            can_cancel=True,
            can_boost=False,
            can_retry=False,
            label="SharePoint",
            description="SharePoint document synchronization",
            icon="folder-sync",
            color="purple",
            default_max_concurrent=None,  # Unlimited by default
            default_timeout_seconds=1800,
        )


class EnhancementQueue(QueueDefinition):
    """Document enhancement queue - runs Docling for improved extraction."""

    def __init__(self):
        super().__init__(
            queue_type="enhancement",
            celery_queue="enhancement",
            run_type_aliases=["extraction_enhancement", "docling_enhancement"],
            can_cancel=True,
            can_boost=False,  # Enhancements are always low priority
            can_retry=True,
            label="Enhancement",
            description="Docling document enhancement (low priority)",
            icon="sparkles",
            color="violet",
            default_max_concurrent=3,  # Limit concurrent to not overwhelm Docling
            default_timeout_seconds=900,  # 15 minutes - Docling can be slow
            default_submission_interval=10,
            default_duplicate_cooldown=60,
        )


class MaintenanceQueue(QueueDefinition):
    """System maintenance and cleanup tasks queue."""

    def __init__(self):
        super().__init__(
            queue_type="maintenance",
            celery_queue="maintenance",
            run_type_aliases=["system_maintenance"],
            can_cancel=False,
            can_boost=False,
            can_retry=False,
            label="Maintenance",
            description="System maintenance and cleanup tasks",
            icon="wrench",
            color="gray",
            default_max_concurrent=1,  # Always serialize maintenance
            default_timeout_seconds=300,
        )


# =============================================================================
# QUEUE REGISTRY
# =============================================================================


class QueueRegistry:
    """
    Central registry of all job queue types.

    This provides a single source of truth for queue configuration,
    enabling the unified Job Manager to handle all job types consistently.

    Usage:
        # Get queue config
        config = queue_registry.get("extraction")

        # Check capabilities
        if queue_registry.can_cancel("extraction"):
            await cancel_job(run_id)

        # Register a new queue type
        queue_registry.register(MyNewQueue())
    """

    def __init__(self):
        self._queues: Dict[str, QueueDefinition] = {}
        self._run_type_map: Dict[str, str] = {}  # Maps run_type -> queue_type
        self._initialized = False

    def register(self, queue: QueueDefinition):
        """
        Register a queue type.

        Args:
            queue: QueueDefinition instance to register
        """
        self._queues[queue.queue_type] = queue

        # Map the primary queue_type
        self._run_type_map[queue.queue_type] = queue.queue_type

        # Map any aliases
        for alias in queue.run_type_aliases:
            self._run_type_map[alias] = queue.queue_type

        logger.debug(f"Registered queue: {queue.queue_type}")

    def _register_defaults(self):
        """Register all default queue types."""
        self.register(ExtractionQueue())
        self.register(EnhancementQueue())
        self.register(SamQueue())
        self.register(ScrapeQueue())
        self.register(SharePointQueue())
        self.register(MaintenanceQueue())

    def initialize(self, config_overrides: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        Initialize the registry with default queues and config overrides.

        Args:
            config_overrides: Dict mapping queue_type to parameter overrides.
                              Only parameters like max_concurrent, timeout_seconds
                              can be overridden - not capabilities or identity.
        """
        if self._initialized:
            logger.warning("Queue registry already initialized")
            return

        # Register all default queue types
        self._register_defaults()

        # Apply config.yml overrides
        if config_overrides:
            for queue_type, overrides in config_overrides.items():
                # Resolve alias to canonical queue type
                canonical = self._run_type_map.get(queue_type, queue_type)

                if canonical in self._queues:
                    self._queues[canonical].apply_config_overrides(overrides)
                    logger.debug(f"Applied config overrides to {canonical}: {overrides}")
                else:
                    logger.warning(f"Config override for unknown queue: {queue_type}")

        self._initialized = True
        logger.info(f"Queue registry initialized with {len(self._queues)} queue types")

    def _ensure_initialized(self):
        """Ensure registry is initialized with config overrides."""
        if not self._initialized:
            # Call the module-level initializer to load config overrides
            # This is needed because forked worker processes need to re-load config
            initialize_queue_registry()

    def get(self, queue_type: str) -> Optional[QueueDefinition]:
        """
        Get queue definition by type or alias.

        Args:
            queue_type: Queue type or run_type alias

        Returns:
            QueueDefinition or None
        """
        self._ensure_initialized()
        canonical = self._run_type_map.get(queue_type, queue_type)
        return self._queues.get(canonical)

    def get_all(self) -> Dict[str, QueueDefinition]:
        """Get all registered queue definitions."""
        self._ensure_initialized()
        return self._queues.copy()

    def get_enabled(self) -> List[QueueDefinition]:
        """Get all enabled queue definitions."""
        self._ensure_initialized()
        return [q for q in self._queues.values() if q.enabled]

    def get_queue_types(self) -> List[str]:
        """Get list of all queue type identifiers."""
        self._ensure_initialized()
        return list(self._queues.keys())

    def resolve_run_type(self, run_type: str) -> Optional[str]:
        """
        Resolve a run_type to its canonical queue_type.

        Args:
            run_type: Value from Run.run_type field

        Returns:
            Canonical queue_type or None if unknown
        """
        self._ensure_initialized()
        return self._run_type_map.get(run_type)

    def get_celery_queue(self, run_type: str) -> Optional[str]:
        """Get Celery queue name for a run type."""
        queue = self.get(run_type)
        return queue.celery_queue if queue else None

    # Capability checks
    def can_cancel(self, run_type: str) -> bool:
        """Check if jobs of this type can be cancelled."""
        queue = self.get(run_type)
        return queue.can_cancel if queue else False

    def can_boost(self, run_type: str) -> bool:
        """Check if jobs of this type can be priority boosted."""
        queue = self.get(run_type)
        return queue.can_boost if queue else False

    def can_retry(self, run_type: str) -> bool:
        """Check if failed jobs of this type can be retried."""
        queue = self.get(run_type)
        return queue.can_retry if queue else False

    # Parameter accessors
    def get_max_concurrent(self, run_type: str) -> Optional[int]:
        """Get max concurrent for a queue (None = unlimited)."""
        queue = self.get(run_type)
        return queue.max_concurrent if queue else None

    def is_throttled(self, run_type: str) -> bool:
        """Check if a queue has throttling enabled."""
        queue = self.get(run_type)
        return queue.is_throttled if queue else False

    def get_timeout_seconds(self, run_type: str) -> int:
        """Get timeout in seconds for a queue type."""
        queue = self.get(run_type)
        return queue.timeout_seconds if queue else 600

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert registry to API response format.

        Returns dict suitable for JSON serialization.
        """
        self._ensure_initialized()
        return {
            "queues": {k: v.to_dict() for k, v in self._queues.items()},
            "run_type_mapping": self._run_type_map.copy(),
        }


# Global singleton instance
queue_registry = QueueRegistry()


def initialize_queue_registry():
    """
    Initialize the queue registry with configuration from config.yml.

    Called during application startup. Loads parameter overrides
    from the 'queues' section in config.yml.

    Configuration is ONLY loaded from config.yml - environment variables
    are not supported for queue type settings.
    """
    try:
        from .config_loader import config_loader

        overrides: Dict[str, Dict[str, Any]] = {}

        # Load from config.yml
        app_config = config_loader.get_config()

        if app_config and app_config.queues:
            # Load per-queue-type overrides from queues section
            for queue_type, queue_override in app_config.queues.items():
                if queue_override:
                    # Convert QueueTypeOverride to dict, excluding None values
                    override_dict = {
                        k: v for k, v in queue_override.model_dump().items()
                        if v is not None
                    }
                    if override_dict:
                        overrides[queue_type] = override_dict

            logger.info(f"Loaded queue overrides from config.yml: {list(overrides.keys())}")
        else:
            logger.info("No queue overrides found in config.yml, using defaults")

        queue_registry.initialize(overrides)
        logger.info("Queue registry initialized successfully")

    except Exception as e:
        logger.warning(f"Failed to initialize queue registry from config: {e}")
        # Fall back to defaults
        queue_registry.initialize()
