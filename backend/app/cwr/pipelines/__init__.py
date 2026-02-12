# backend/app/cwr/pipelines/__init__.py
"""
Curatore Pipelines Framework

Pipelines process collections of items through multiple stages:
gather, filter, transform, enrich, and output.

Usage:
    from app.cwr.pipelines import pipeline_executor

    result = await pipeline_executor.execute(
        session=session,
        pipeline_slug="sharepoint_proposals",
        organization_id=org_id,
        params={"site_id": "..."},
    )
"""

from .runtime.definitions import (
    BasePipeline,
    OnErrorPolicy,
    ParameterDefinition,
    PipelineDefinition,
    StageDefinition,
    StageType,
    TriggerDefinition,
)
from .runtime.executor import PipelineExecutor, pipeline_executor
from .store.discovery import PipelineDiscoveryService, pipeline_discovery_service
from .store.loader import PipelineLoader, pipeline_loader

__all__ = [
    "BasePipeline",
    "PipelineDefinition",
    "StageDefinition",
    "StageType",
    "OnErrorPolicy",
    "ParameterDefinition",
    "TriggerDefinition",
    "PipelineExecutor",
    "pipeline_executor",
    "PipelineLoader",
    "pipeline_loader",
    "PipelineDiscoveryService",
    "pipeline_discovery_service",
]
