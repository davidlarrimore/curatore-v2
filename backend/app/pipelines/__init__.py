# backend/app/pipelines/__init__.py
"""
Curatore Pipelines Framework

Pipelines are multi-stage document processing workflows that:
- Process collections of items through multiple stages
- Track per-item state for checkpointing and resume
- Support gather, filter, transform, and enrich stages

Usage:
    from app.pipelines import pipeline_executor

    result = await pipeline_executor.execute(
        session=session,
        pipeline_slug="sharepoint_proposals",
        organization_id=org_id,
        params={"sync_config_id": "uuid"},
    )
"""

from .base import BasePipeline, PipelineDefinition, StageDefinition, StageType
from .executor import PipelineExecutor, pipeline_executor
from .loader import PipelineLoader, pipeline_loader
from .discovery import PipelineDiscoveryService, pipeline_discovery_service

__all__ = [
    "BasePipeline",
    "PipelineDefinition",
    "StageDefinition",
    "StageType",
    "PipelineExecutor",
    "pipeline_executor",
    "PipelineLoader",
    "pipeline_loader",
    "PipelineDiscoveryService",
    "pipeline_discovery_service",
]
