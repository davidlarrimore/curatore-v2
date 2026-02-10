# backend/app/database/procedures.py
"""
SQLAlchemy ORM models for the Curatore Procedures Framework.

This module defines the data models for:
- Procedures: Schedulable, event-driven workflows
- Pipelines: Multi-stage document processing workflows
- Triggers: Cron, event, and webhook triggers for procedures/pipelines
- Pipeline execution state tracking

Models follow the same patterns as the main models.py:
- UUID primary keys with default=uuid.uuid4
- JSONB for queryable JSON fields
- Composite indexes for common queries
- cascade="all, delete-orphan" for relationships
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import relationship

from .base import Base


# UUID type that works with both SQLite and PostgreSQL
# Defined here to avoid circular imports from parent models
class UUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses PostgreSQL's UUID type when available, otherwise uses String(36).
    """
    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        import uuid as uuid_module
        if isinstance(value, uuid_module.UUID):
            return value
        return uuid_module.UUID(value)


class Procedure(Base):
    """
    Procedure model representing a schedulable, event-driven workflow.

    Procedures are sequences of function calls that can be triggered by:
    - Cron schedules (e.g., daily digest at 6 AM)
    - Events (e.g., sam_pull.completed)
    - Webhooks (external systems)
    - Manual execution via API

    Procedures are defined in YAML files or programmatically and are
    discovered/registered at application startup.

    Attributes:
        id: Unique procedure identifier
        organization_id: Organization that owns this procedure
        name: Human-readable procedure name
        slug: URL-friendly identifier (unique per org)
        description: Detailed description of what the procedure does
        definition: JSONB containing steps, parameters, outputs, etc.
        version: Incremented when definition changes
        is_active: Whether procedure can be triggered
        is_system: System procedures are managed by code, not editable
        source_type: 'yaml', 'python', or 'user' (created via UI)
        source_path: Path to source file for yaml/python procedures
        created_at: When procedure was created
        updated_at: When procedure was last modified
        created_by: User who created this procedure

    Relationships:
        organization: Organization that owns this procedure
        triggers: List of triggers for this procedure
        runs: Runs executed by this procedure

    Definition Structure:
        {
            "parameters": {...},       # Input parameters with defaults
            "steps": [...],            # List of function calls
            "outputs": {...},          # Output configuration
            "on_error": "fail|skip|continue"
        }
    """

    __tablename__ = "procedures"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Identity
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Definition (JSONB for queryability)
    definition = Column(JSONB, nullable=False, default=dict, server_default="{}")
    version = Column(Integer, nullable=False, default=1)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)
    is_system = Column(Boolean, nullable=False, default=False)

    # Source tracking
    source_type = Column(String(50), nullable=False, default="yaml")
    source_path = Column(String(500), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    organization = relationship("Organization")
    user = relationship("User")
    triggers = relationship(
        "ProcedureTrigger",
        back_populates="procedure",
        cascade="all, delete-orphan",
    )

    # Indexes
    __table_args__ = (
        Index("ix_procedures_org_slug", "organization_id", "slug", unique=True),
        Index("ix_procedures_org_active", "organization_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Procedure(id={self.id}, slug={self.slug}, version={self.version})>"


class ProcedureVersion(Base):
    """
    Version history for procedure definitions.

    Each time a procedure's definition is created or updated, a snapshot
    is saved here. This enables:
    - Viewing previous versions of a procedure
    - Comparing definitions between versions (diff)
    - Restoring a procedure to a previous version

    Restoring creates a new version (N+1) with the restored definition,
    preserving full history. History is never overwritten.

    Attributes:
        id: Unique version record identifier
        procedure_id: Procedure this version belongs to
        version: Version number (matches procedure.version at time of snapshot)
        definition: Full JSONB snapshot of the procedure definition
        change_summary: Optional description of what changed
        created_by: User who created this version
        created_at: When this version was created

    Relationships:
        procedure: Procedure this version belongs to
        user: User who created this version
    """

    __tablename__ = "procedure_versions"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    procedure_id = Column(
        UUID(), ForeignKey("procedures.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = Column(Integer, nullable=False)
    definition = Column(JSONB, nullable=False)
    change_summary = Column(Text, nullable=True)
    created_by = Column(UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization")
    procedure = relationship("Procedure", backref="versions")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("procedure_id", "version", name="uq_procedure_version"),
        Index("ix_procedure_versions_proc_version", "procedure_id", "version"),
        Index("ix_procedure_versions_org", "organization_id"),
    )

    def __repr__(self) -> str:
        return f"<ProcedureVersion(id={self.id}, procedure={self.procedure_id}, version={self.version})>"


class Pipeline(Base):
    """
    Pipeline model representing a multi-stage document processing workflow.

    Pipelines process collections of items through multiple stages, with
    per-item state tracking and checkpoint/resume capabilities. Each stage
    can filter, transform, or enrich items.

    Attributes:
        id: Unique pipeline identifier
        organization_id: Organization that owns this pipeline
        name: Human-readable pipeline name
        slug: URL-friendly identifier (unique per org)
        description: Detailed description
        definition: JSONB containing configuration, parameters
        stages: JSONB array of stage definitions
        version: Incremented when definition changes
        is_active: Whether pipeline can be triggered
        is_system: System pipelines are managed by code
        source_type: 'yaml', 'python', or 'user'
        source_path: Path to source file

    Relationships:
        organization: Organization that owns this pipeline
        triggers: List of triggers for this pipeline
        pipeline_runs: Execution records for this pipeline

    Stages Structure:
        [
            {
                "name": "gather",
                "type": "gather|filter|transform|enrich",
                "function": "search_assets",
                "config": {...},
                "on_error": "fail|skip|continue"
            },
            ...
        ]
    """

    __tablename__ = "pipelines"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Identity
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Definition
    definition = Column(JSONB, nullable=False, default=dict, server_default="{}")
    stages = Column(JSONB, nullable=False, default=list, server_default="[]")
    version = Column(Integer, nullable=False, default=1)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)
    is_system = Column(Boolean, nullable=False, default=False)

    # Source tracking
    source_type = Column(String(50), nullable=False, default="yaml")
    source_path = Column(String(500), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(UUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    organization = relationship("Organization")
    user = relationship("User")
    triggers = relationship(
        "PipelineTrigger",
        back_populates="pipeline",
        cascade="all, delete-orphan",
    )
    pipeline_runs = relationship(
        "PipelineRun",
        back_populates="pipeline",
        cascade="all, delete-orphan",
    )

    # Indexes
    __table_args__ = (
        Index("ix_pipelines_org_slug", "organization_id", "slug", unique=True),
        Index("ix_pipelines_org_active", "organization_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Pipeline(id={self.id}, slug={self.slug}, stages={len(self.stages or [])})>"


class ProcedureTrigger(Base):
    """
    Trigger configuration for a procedure.

    Triggers define when and how procedures are automatically executed:
    - Cron: Schedule-based execution (e.g., "0 6 * * 1-5" for weekdays at 6 AM)
    - Event: Triggered by system events (e.g., "sam_pull.completed")
    - Webhook: Triggered by external HTTP calls

    Attributes:
        id: Unique trigger identifier
        procedure_id: Procedure this trigger belongs to
        organization_id: Organization context
        trigger_type: 'cron', 'event', or 'webhook'
        cron_expression: Cron schedule (for cron triggers)
        event_name: Event to listen for (for event triggers)
        event_filter: JSONB filter for event payload matching
        webhook_secret: Secret for webhook validation
        trigger_params: Parameters to pass when triggered
        is_active: Whether trigger is active
        last_triggered_at: When trigger last fired
        next_trigger_at: Next scheduled execution (for cron)

    Relationships:
        procedure: Procedure this trigger belongs to
        organization: Organization context
    """

    __tablename__ = "procedure_triggers"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    procedure_id = Column(
        UUID(), ForeignKey("procedures.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Trigger configuration
    trigger_type = Column(String(50), nullable=False)  # cron, event, webhook
    cron_expression = Column(String(100), nullable=True)
    event_name = Column(String(255), nullable=True)
    event_filter = Column(JSONB, nullable=True)
    webhook_secret = Column(String(255), nullable=True)
    trigger_params = Column(JSONB, nullable=True)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)

    # Execution tracking
    last_triggered_at = Column(DateTime, nullable=True)
    next_trigger_at = Column(DateTime, nullable=True)
    trigger_count = Column(Integer, nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    procedure = relationship("Procedure", back_populates="triggers")
    organization = relationship("Organization")

    # Indexes
    __table_args__ = (
        Index("ix_procedure_triggers_event", "event_name"),
        Index("ix_procedure_triggers_next_cron", "next_trigger_at"),
    )

    def __repr__(self) -> str:
        return f"<ProcedureTrigger(id={self.id}, type={self.trigger_type}, procedure={self.procedure_id})>"


class PipelineTrigger(Base):
    """
    Trigger configuration for a pipeline.

    Same structure as ProcedureTrigger but for pipelines.
    """

    __tablename__ = "pipeline_triggers"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    pipeline_id = Column(
        UUID(), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Trigger configuration
    trigger_type = Column(String(50), nullable=False)
    cron_expression = Column(String(100), nullable=True)
    event_name = Column(String(255), nullable=True)
    event_filter = Column(JSONB, nullable=True)
    webhook_secret = Column(String(255), nullable=True)
    trigger_params = Column(JSONB, nullable=True)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)

    # Execution tracking
    last_triggered_at = Column(DateTime, nullable=True)
    next_trigger_at = Column(DateTime, nullable=True)
    trigger_count = Column(Integer, nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    pipeline = relationship("Pipeline", back_populates="triggers")
    organization = relationship("Organization")

    # Indexes
    __table_args__ = (
        Index("ix_pipeline_triggers_event", "event_name"),
        Index("ix_pipeline_triggers_next_cron", "next_trigger_at"),
    )

    def __repr__(self) -> str:
        return f"<PipelineTrigger(id={self.id}, type={self.trigger_type}, pipeline={self.pipeline_id})>"


class PipelineRun(Base):
    """
    Links a pipeline execution to a Run with stage tracking.

    PipelineRun extends the base Run model with pipeline-specific state:
    - Current stage tracking
    - Per-stage results
    - Item counts and progress
    - Checkpoint data for resumability

    Attributes:
        id: Unique pipeline run identifier
        pipeline_id: Pipeline being executed
        run_id: Associated Run record (for status, logs, etc.)
        organization_id: Organization context
        current_stage: Index of current stage being executed
        total_stages: Total number of stages
        stage_results: JSONB with results from each stage
        total_items: Number of items being processed
        processed_items: Items successfully processed
        failed_items: Items that failed processing
        checkpoint_data: Data for resume capability

    Relationships:
        pipeline: Pipeline being executed
        run: Associated Run record
        organization: Organization context
        item_states: Per-item state tracking
    """

    __tablename__ = "pipeline_runs"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    pipeline_id = Column(
        UUID(), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id = Column(
        UUID(), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Stage tracking
    current_stage = Column(Integer, nullable=False, default=0)
    total_stages = Column(Integer, nullable=False, default=0)
    stage_results = Column(JSONB, nullable=False, default=dict, server_default="{}")

    # Item tracking
    total_items = Column(Integer, nullable=True)
    processed_items = Column(Integer, nullable=True, default=0)
    failed_items = Column(Integer, nullable=True, default=0)

    # Resumability
    checkpoint_data = Column(JSONB, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    pipeline = relationship("Pipeline", back_populates="pipeline_runs")
    run = relationship("Run")
    organization = relationship("Organization")
    item_states = relationship(
        "PipelineItemState",
        back_populates="pipeline_run",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<PipelineRun(id={self.id}, pipeline={self.pipeline_id}, stage={self.current_stage}/{self.total_stages})>"


class PipelineItemState(Base):
    """
    Per-item state tracking for pipeline execution.

    Tracks the progress of individual items (assets, solicitations, etc.)
    through pipeline stages. Enables:
    - Per-item error handling (item fails, others continue)
    - Resume from checkpoint (skip already-processed items)
    - Stage-specific data accumulation

    Attributes:
        id: Unique item state identifier
        pipeline_run_id: Pipeline run this item belongs to
        item_type: Type of item (e.g., 'asset', 'solicitation')
        item_id: ID of the item being processed
        stage_status: JSONB mapping stage name -> status
        stage_data: JSONB with accumulated data from each stage
        status: Overall item status (pending, processing, completed, failed)
        error_message: Error message if item failed

    Relationships:
        pipeline_run: Pipeline run this item belongs to

    Stage Status Values:
        pending, processing, completed, failed, skipped
    """

    __tablename__ = "pipeline_item_states"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    pipeline_run_id = Column(
        UUID(), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Item identification
    item_type = Column(String(50), nullable=False)
    item_id = Column(UUID(), nullable=False)

    # Stage tracking
    stage_status = Column(JSONB, nullable=False, default=dict, server_default="{}")
    stage_data = Column(JSONB, nullable=False, default=dict, server_default="{}")

    # Overall status
    status = Column(String(50), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    pipeline_run = relationship("PipelineRun", back_populates="item_states")

    # Indexes
    __table_args__ = (
        Index("ix_pipeline_item_states_item", "item_type", "item_id"),
        Index("ix_pipeline_item_states_run_status", "pipeline_run_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<PipelineItemState(id={self.id}, type={self.item_type}, item={self.item_id}, status={self.status})>"


class FunctionExecution(Base):
    """
    Audit log for function executions (optional).

    Records function calls for auditing, debugging, and analytics.
    Not required for basic operation but useful for understanding
    procedure/pipeline behavior.

    Attributes:
        id: Unique execution identifier
        organization_id: Organization context
        function_name: Name of function that was executed
        execution_context: 'procedure', 'pipeline', or 'direct' (API call)
        run_id: Associated run if applicable
        input_params: JSONB of input parameters
        output_summary: JSONB summary of output
        status: 'success', 'failed', 'timeout'
        error_message: Error message if failed
        started_at: Execution start time
        completed_at: Execution end time
        duration_ms: Execution duration in milliseconds

    Relationships:
        organization: Organization context
        run: Associated run if applicable
    """

    __tablename__ = "function_executions"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Function identification
    function_name = Column(String(255), nullable=False, index=True)
    execution_context = Column(String(50), nullable=False)  # procedure, pipeline, direct

    # Run association
    run_id = Column(UUID(), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True)

    # Execution details
    input_params = Column(JSONB, nullable=True)
    output_summary = Column(JSONB, nullable=True)

    # Status
    status = Column(String(50), nullable=False, index=True)  # success, failed, timeout
    error_message = Column(Text, nullable=True)

    # Timing
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    organization = relationship("Organization")
    run = relationship("Run")

    # Indexes
    __table_args__ = (
        Index("ix_function_executions_org_created", "organization_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<FunctionExecution(id={self.id}, function={self.function_name}, status={self.status})>"
