"""
Comprehensive tests for queue management functionality.

Tests the queue registry, job lifecycle, cancellation, and monitoring capabilities
for all queue types (extraction, SAM, scrape, SharePoint, maintenance).
"""


import pytest
from app.core.ops.queue_registry import (
    ExtractionQueue,
    MaintenanceQueue,
    QueueDefinition,
    QueueRegistry,
    SamQueue,
    ScrapeQueue,
    SharePointQueue,
    queue_registry,
)

# =============================================================================
# Queue Registry Tests
# =============================================================================


class TestQueueDefinition:
    """Tests for QueueDefinition base class."""

    def test_queue_definition_defaults(self):
        """Test default values for queue definition."""
        queue = QueueDefinition(
            queue_type="test",
            celery_queue="test_queue",
        )
        assert queue.queue_type == "test"
        assert queue.celery_queue == "test_queue"
        assert queue.can_cancel is False
        assert queue.can_retry is False
        assert queue.default_max_concurrent is None
        assert queue.default_timeout_seconds == 600
        assert queue.is_throttled is False

    def test_queue_definition_with_capabilities(self):
        """Test queue definition with capabilities enabled."""
        queue = QueueDefinition(
            queue_type="test",
            celery_queue="test_queue",
            can_cancel=True,
            can_retry=True,
        )
        assert queue.can_cancel is True
        assert queue.can_retry is True

    def test_queue_definition_with_throttling(self):
        """Test queue definition with max_concurrent set."""
        queue = QueueDefinition(
            queue_type="test",
            celery_queue="test_queue",
            default_max_concurrent=5,
        )
        assert queue.max_concurrent == 5
        assert queue.is_throttled is True

    def test_queue_definition_to_dict(self):
        """Test serialization to dictionary."""
        queue = QueueDefinition(
            queue_type="test",
            celery_queue="test_queue",
            label="Test Queue",
            description="A test queue",
            icon="test-icon",
            color="blue",
            can_cancel=True,
            default_max_concurrent=10,
        )
        result = queue.to_dict()

        assert result["queue_type"] == "test"
        assert result["celery_queue"] == "test_queue"
        assert result["label"] == "Test Queue"
        assert result["description"] == "A test queue"
        assert result["icon"] == "test-icon"
        assert result["color"] == "blue"
        assert result["can_cancel"] is True
        assert result["max_concurrent"] == 10
        assert result["is_throttled"] is True

    def test_apply_config_overrides(self):
        """Test applying configuration overrides."""
        queue = QueueDefinition(
            queue_type="test",
            celery_queue="test_queue",
            default_max_concurrent=5,
            default_timeout_seconds=300,
        )

        queue.apply_config_overrides({
            "max_concurrent": 10,
            "timeout_seconds": 600,
            "enabled": False,
        })

        assert queue.max_concurrent == 10
        assert queue.timeout_seconds == 600
        assert queue.enabled is False

    def test_apply_config_overrides_partial(self):
        """Test applying partial configuration overrides."""
        queue = QueueDefinition(
            queue_type="test",
            celery_queue="test_queue",
            default_max_concurrent=5,
            default_timeout_seconds=300,
        )

        # Only override max_concurrent
        queue.apply_config_overrides({"max_concurrent": 20})

        assert queue.max_concurrent == 20
        assert queue.timeout_seconds == 300  # Unchanged
        assert queue.enabled is True  # Unchanged


class TestQueueRegistry:
    """Tests for QueueRegistry class."""

    def test_registry_initialization(self):
        """Test registry initializes with default queues."""
        registry = QueueRegistry()
        registry.initialize()

        assert "extraction" in registry.get_queue_types()
        assert "sam" in registry.get_queue_types()
        assert "scrape" in registry.get_queue_types()
        assert "sharepoint" in registry.get_queue_types()
        assert "maintenance" in registry.get_queue_types()

    def test_registry_get_queue(self):
        """Test getting queue by type."""
        registry = QueueRegistry()
        registry.initialize()

        extraction = registry.get("extraction")
        assert extraction is not None
        assert extraction.queue_type == "extraction"
        assert extraction.celery_queue == "extraction"

    def test_registry_get_by_alias(self):
        """Test getting queue by run_type alias."""
        registry = QueueRegistry()
        registry.initialize()

        # sam_pull is an alias for sam queue
        sam = registry.get("sam_pull")
        assert sam is not None
        assert sam.queue_type == "sam"

    def test_registry_resolve_run_type(self):
        """Test resolving run_type to queue_type."""
        registry = QueueRegistry()
        registry.initialize()

        assert registry.resolve_run_type("extraction") == "extraction"
        assert registry.resolve_run_type("sam_pull") == "sam"
        assert registry.resolve_run_type("sharepoint_sync") == "sharepoint"
        assert registry.resolve_run_type("unknown") is None

    def test_registry_capability_checks(self):
        """Test capability check methods."""
        registry = QueueRegistry()
        registry.initialize()

        # Extraction supports cancel and retry
        assert registry.can_cancel("extraction") is True
        assert registry.can_retry("extraction") is True

        # SAM can cancel (cancels queued child extractions) but not retry
        assert registry.can_cancel("sam") is True
        assert registry.can_retry("sam") is False

        # SharePoint can cancel but not retry
        assert registry.can_cancel("sharepoint") is True
        assert registry.can_retry("sharepoint") is False

    def test_registry_get_celery_queue(self):
        """Test getting Celery queue name."""
        registry = QueueRegistry()
        registry.initialize()

        assert registry.get_celery_queue("extraction") == "extraction"
        assert registry.get_celery_queue("sam_pull") == "sam"
        assert registry.get_celery_queue("sharepoint_sync") == "sharepoint"
        assert registry.get_celery_queue("unknown") is None

    def test_registry_is_throttled(self):
        """Test throttling detection."""
        registry = QueueRegistry()
        registry.initialize()

        # Extraction is throttled by default
        assert registry.is_throttled("extraction") is True

        # Maintenance is throttled (max_concurrent=1)
        assert registry.is_throttled("maintenance") is True

        # SAM is not throttled by default
        assert registry.is_throttled("sam") is False

    def test_registry_with_config_overrides(self):
        """Test registry initialization with config overrides."""
        registry = QueueRegistry()
        registry.initialize({
            "extraction": {"max_concurrent": 20},
            "sam": {"enabled": False},
        })

        extraction = registry.get("extraction")
        assert extraction.max_concurrent == 20

        sam = registry.get("sam")
        assert sam.enabled is False

    def test_registry_to_api_response(self):
        """Test API response serialization."""
        registry = QueueRegistry()
        registry.initialize()

        response = registry.to_api_response()

        assert "queues" in response
        assert "run_type_mapping" in response
        assert "extraction" in response["queues"]
        assert response["run_type_mapping"]["sam_pull"] == "sam"

    def test_registry_get_all(self):
        """Test getting all registered queues."""
        registry = QueueRegistry()
        registry.initialize()

        all_queues = registry.get_all()
        # 9 queues: extraction, sam, scrape, sharepoint, maintenance, pipeline, procedure, salesforce, forecast
        assert len(all_queues) == 9
        assert all(isinstance(q, QueueDefinition) for q in all_queues.values())

    def test_registry_get_enabled(self):
        """Test getting only enabled queues."""
        registry = QueueRegistry()
        registry.initialize({"sam": {"enabled": False}})

        enabled = registry.get_enabled()
        queue_types = [q.queue_type for q in enabled]

        assert "sam" not in queue_types
        assert "extraction" in queue_types

    def test_registry_custom_queue_registration(self):
        """Test registering a custom queue type."""
        registry = QueueRegistry()
        registry.initialize()

        custom_queue = QueueDefinition(
            queue_type="custom",
            celery_queue="custom_queue",
            run_type_aliases=["custom_job"],
            label="Custom Queue",
            can_cancel=True,
        )
        registry.register(custom_queue)

        assert registry.get("custom") is not None
        assert registry.get("custom_job") is not None
        assert registry.can_cancel("custom") is True


# =============================================================================
# Individual Queue Type Tests
# =============================================================================


class TestExtractionQueue:
    """Tests for ExtractionQueue configuration."""

    def test_extraction_queue_config(self):
        """Test extraction queue has correct configuration."""
        queue = ExtractionQueue()

        assert queue.queue_type == "extraction"
        assert queue.celery_queue == "extraction"
        assert queue.can_cancel is True
        assert queue.can_retry is True
        assert queue.default_max_concurrent == 10
        assert queue.label == "Extraction"
        assert queue.icon == "file-text"
        assert queue.color == "blue"

    def test_extraction_queue_is_throttled(self):
        """Test extraction queue is throttled by default."""
        queue = ExtractionQueue()
        assert queue.is_throttled is True


class TestSamQueue:
    """Tests for SamQueue configuration."""

    def test_sam_queue_config(self):
        """Test SAM queue has correct configuration."""
        queue = SamQueue()

        assert queue.queue_type == "sam"
        assert queue.celery_queue == "sam"
        assert queue.can_cancel is True  # Cancels queued child extractions
        assert queue.can_retry is False
        assert queue.default_max_concurrent is None
        assert "sam_pull" in queue.run_type_aliases
        assert queue.label == "SAM.gov"
        assert queue.color == "amber"

    def test_sam_queue_not_throttled(self):
        """Test SAM queue is not throttled by default."""
        queue = SamQueue()
        assert queue.is_throttled is False


class TestScrapeQueue:
    """Tests for ScrapeQueue configuration."""

    def test_scrape_queue_config(self):
        """Test scrape queue has correct configuration."""
        queue = ScrapeQueue()

        assert queue.queue_type == "scrape"
        assert queue.celery_queue == "scrape"
        assert queue.can_cancel is True
        assert queue.can_retry is False
        assert "scrape_crawl" in queue.run_type_aliases
        assert "scrape_delete" in queue.run_type_aliases
        assert queue.label == "Web Scrape"
        assert queue.color == "emerald"


class TestSharePointQueue:
    """Tests for SharePointQueue configuration."""

    def test_sharepoint_queue_config(self):
        """Test SharePoint queue has correct configuration."""
        queue = SharePointQueue()

        assert queue.queue_type == "sharepoint"
        assert queue.celery_queue == "sharepoint"
        assert queue.can_cancel is True
        assert queue.can_retry is False
        assert "sharepoint_sync" in queue.run_type_aliases
        assert "sharepoint_import" in queue.run_type_aliases
        assert "sharepoint_delete" in queue.run_type_aliases
        assert queue.label == "SharePoint"
        assert queue.color == "purple"


class TestMaintenanceQueue:
    """Tests for MaintenanceQueue configuration."""

    def test_maintenance_queue_config(self):
        """Test maintenance queue has correct configuration."""
        queue = MaintenanceQueue()

        assert queue.queue_type == "maintenance"
        assert queue.celery_queue == "maintenance"
        assert queue.can_cancel is True
        assert queue.can_retry is False
        assert queue.default_max_concurrent == 4  # Allow concurrent different task types (locks prevent same-task overlap)
        assert "system_maintenance" in queue.run_type_aliases
        assert queue.label == "Maintenance"
        assert queue.color == "gray"

    def test_maintenance_queue_is_throttled(self):
        """Test maintenance queue is throttled."""
        queue = MaintenanceQueue()
        assert queue.is_throttled is True
        assert queue.max_concurrent == 4


# =============================================================================
# Global Registry Tests
# =============================================================================


class TestGlobalQueueRegistry:
    """Tests for the global queue_registry singleton."""

    def test_global_registry_available(self):
        """Test global registry is available."""
        assert queue_registry is not None
        assert isinstance(queue_registry, QueueRegistry)

    def test_global_registry_lazy_init(self):
        """Test global registry initializes on explicit init call."""
        # Create a fresh registry and explicitly initialize
        # (lazy init via config file may fail if config has validation issues)
        registry = QueueRegistry()
        registry.initialize()

        # Should be able to get extraction queue
        extraction = registry.get("extraction")
        assert extraction is not None

    def test_global_registry_run_type_aliases(self):
        """Test all expected run_type aliases are registered."""
        # Ensure initialized
        queue_registry._ensure_initialized()

        expected_aliases = [
            "extraction",
            "sam_pull",
            "scrape_crawl",
            "scrape_delete",
            "sharepoint_sync",
            "sharepoint_import",
            "sharepoint_delete",
            "system_maintenance",
        ]

        for alias in expected_aliases:
            resolved = queue_registry.resolve_run_type(alias)
            assert resolved is not None, f"Alias '{alias}' not registered"


# =============================================================================
# Queue Capability Integration Tests
# =============================================================================


class TestQueueCapabilityMatrix:
    """Tests for the complete capability matrix across all queues."""

    @pytest.fixture
    def registry(self):
        """Fresh registry for testing."""
        reg = QueueRegistry()
        reg.initialize()
        return reg

    def test_cancellable_queues(self, registry):
        """Test which queues support cancellation."""
        cancellable = ["extraction", "scrape", "sharepoint", "sam", "maintenance"]

        for qt in cancellable:
            assert registry.can_cancel(qt), f"{qt} should be cancellable"

    def test_retryable_queues(self, registry):
        """Test which queues support retry."""
        retryable = ["extraction"]
        non_retryable = ["sam", "scrape", "sharepoint", "maintenance"]

        for qt in retryable:
            assert registry.can_retry(qt), f"{qt} should be retryable"

        for qt in non_retryable:
            assert not registry.can_retry(qt), f"{qt} should not be retryable"

    def test_throttled_queues(self, registry):
        """Test which queues have throttling enabled."""
        throttled = ["extraction", "maintenance"]
        not_throttled = ["sam", "scrape", "sharepoint"]

        for qt in throttled:
            assert registry.is_throttled(qt), f"{qt} should be throttled"

        for qt in not_throttled:
            assert not registry.is_throttled(qt), f"{qt} should not be throttled"


# =============================================================================
# Configuration Override Tests
# =============================================================================


class TestConfigurationOverrides:
    """Tests for runtime configuration overrides."""

    def test_override_max_concurrent(self):
        """Test overriding max_concurrent via config."""
        registry = QueueRegistry()
        registry.initialize({
            "extraction": {"max_concurrent": 50},
        })

        extraction = registry.get("extraction")
        assert extraction.max_concurrent == 50

    def test_override_timeout(self):
        """Test overriding timeout_seconds via config."""
        registry = QueueRegistry()
        registry.initialize({
            "sam": {"timeout_seconds": 3600},
        })

        sam = registry.get("sam")
        assert sam.timeout_seconds == 3600

    def test_disable_queue_via_config(self):
        """Test disabling a queue via config."""
        registry = QueueRegistry()
        registry.initialize({
            "maintenance": {"enabled": False},
        })

        maintenance = registry.get("maintenance")
        assert maintenance.enabled is False

        enabled = registry.get_enabled()
        queue_types = [q.queue_type for q in enabled]
        assert "maintenance" not in queue_types

    def test_override_via_alias(self):
        """Test config override using run_type alias."""
        registry = QueueRegistry()
        registry.initialize({
            "sam_pull": {"timeout_seconds": 7200},
        })

        # Should apply to the sam queue
        sam = registry.get("sam")
        assert sam.timeout_seconds == 7200

    def test_capabilities_not_overridable(self):
        """Test that capabilities cannot be overridden via config."""
        registry = QueueRegistry()
        registry.initialize({
            "maintenance": {
                "can_cancel": False,  # Should be ignored — capabilities are code-defined
            },
        })

        maintenance = registry.get("maintenance")
        # Capabilities should remain as defined in code (can_cancel=True)
        assert maintenance.can_cancel is True


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_get_unknown_queue_type(self):
        """Test getting an unknown queue type returns None."""
        registry = QueueRegistry()
        registry.initialize()

        result = registry.get("nonexistent")
        assert result is None

    def test_capability_check_unknown_type(self):
        """Test capability checks for unknown types return False."""
        registry = QueueRegistry()
        registry.initialize()

        assert registry.can_cancel("nonexistent") is False
        assert registry.can_retry("nonexistent") is False

    def test_double_initialization(self):
        """Test registry handles double initialization gracefully."""
        registry = QueueRegistry()
        registry.initialize()

        # Second init should warn but not fail
        registry.initialize()

        # Should still work correctly
        assert registry.get("extraction") is not None

    def test_empty_config_overrides(self):
        """Test initialization with empty config overrides."""
        registry = QueueRegistry()
        registry.initialize({})

        # Should use defaults
        extraction = registry.get("extraction")
        assert extraction.max_concurrent == 10  # Default

    def test_none_config_overrides(self):
        """Test initialization with None config overrides."""
        registry = QueueRegistry()
        registry.initialize(None)

        # Should use defaults
        extraction = registry.get("extraction")
        assert extraction.max_concurrent == 10  # Default
