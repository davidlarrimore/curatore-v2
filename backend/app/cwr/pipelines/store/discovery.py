# backend/app/pipelines/discovery.py
"""
Pipeline Discovery Service - Register pipelines in database.

On application startup, discovers pipeline definitions from:
1. YAML files in definitions/
2. Python-defined pipelines

Registers them in the database so they can be:
- Listed via API
- Have triggers configured
- Track execution history

Also cleans up stale pipelines where the source YAML file no longer exists.
"""

import logging
import os
from typing import Dict, List, Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..runtime.definitions import PipelineDefinition
from .loader import pipeline_loader

logger = logging.getLogger("curatore.pipelines.discovery")


class PipelineDiscoveryService:
    """
    Discovers and registers pipelines in the database.
    """

    async def discover_and_register(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, any]:
        """
        Discover all pipelines and register/update them in the database.
        Also cleans up stale YAML-based pipelines whose source files no longer exist.

        Args:
            session: Database session
            organization_id: Organization to register pipelines for

        Returns:
            Dict with registration and cleanup statistics
        """
        from app.core.database.procedures import Pipeline, PipelineTrigger

        results = {
            "registered": 0,
            "updated": 0,
            "unchanged": 0,
            "removed": 0,
            "errors": [],
        }

        # Discover all pipeline definitions
        definitions = pipeline_loader.discover_all()
        logger.info(f"Discovered {len(definitions)} pipeline definitions")

        # Track which slugs we've seen from YAML files
        discovered_slugs = set(definitions.keys())

        for slug, definition in definitions.items():
            try:
                # Check if pipeline already exists
                existing_query = select(Pipeline).where(
                    Pipeline.organization_id == organization_id,
                    Pipeline.slug == slug,
                )
                result = await session.execute(existing_query)
                existing = result.scalar_one_or_none()

                # Convert definition to storable format
                definition_dict = definition.to_dict()
                stages_list = definition_dict.get("stages", [])

                if existing:
                    # Update if definition changed
                    if (existing.definition != definition_dict or
                        existing.stages != stages_list or
                        existing.source_path != definition.source_path):
                        existing.name = definition.name
                        existing.description = definition.description
                        existing.definition = definition_dict
                        existing.stages = stages_list
                        existing.version = existing.version + 1
                        existing.source_type = definition.source_type
                        existing.source_path = definition.source_path
                        existing.is_system = definition.is_system
                        existing.updated_at = datetime.utcnow()
                        results["updated"] += 1
                        logger.info(f"Updated pipeline: {slug}")
                    else:
                        results["unchanged"] += 1
                else:
                    # Create new pipeline
                    pipeline = Pipeline(
                        organization_id=organization_id,
                        name=definition.name,
                        slug=slug,
                        description=definition.description,
                        definition=definition_dict,
                        stages=stages_list,
                        version=1,
                        is_active=True,
                        is_system=definition.is_system,
                        source_type=definition.source_type,
                        source_path=definition.source_path,
                    )
                    session.add(pipeline)
                    await session.flush()

                    # Create triggers
                    for trigger_def in definition.triggers:
                        trigger = PipelineTrigger(
                            pipeline_id=pipeline.id,
                            organization_id=organization_id,
                            trigger_type=trigger_def.type,
                            cron_expression=trigger_def.cron_expression,
                            event_name=trigger_def.event_name,
                            event_filter=trigger_def.event_filter,
                            is_active=True,
                        )
                        session.add(trigger)

                    results["registered"] += 1
                    logger.info(f"Created pipeline: {slug}")

            except Exception as e:
                logger.error(f"Failed to register pipeline {slug}: {e}")
                results["errors"].append(f"{slug}: {e}")

        # Clean up stale YAML-based pipelines whose source files no longer exist
        stale_query = select(Pipeline).where(
            Pipeline.organization_id == organization_id,
            Pipeline.source_type == "yaml",
        )
        result = await session.execute(stale_query)
        yaml_pipelines = result.scalars().all()

        for pipe in yaml_pipelines:
            # Check if this pipeline's YAML file still exists
            if pipe.slug not in discovered_slugs:
                # YAML file was removed - check if source_path confirms this
                if pipe.source_path and not os.path.exists(pipe.source_path):
                    logger.info(f"Removing stale pipeline: {pipe.slug} (source file deleted: {pipe.source_path})")
                    await session.delete(pipe)
                    results["removed"] += 1
                elif not pipe.source_path:
                    # No source path recorded, but slug not in discovered definitions
                    logger.info(f"Removing stale pipeline: {pipe.slug} (no longer in definitions)")
                    await session.delete(pipe)
                    results["removed"] += 1

        await session.commit()
        return results

    async def sync_triggers(
        self,
        session: AsyncSession,
        organization_id: UUID,
        pipeline_slug: str,
    ) -> Dict[str, any]:
        """
        Sync triggers for a specific pipeline from its definition.

        Args:
            session: Database session
            organization_id: Organization context
            pipeline_slug: Pipeline to sync triggers for

        Returns:
            Summary of trigger changes
        """
        from app.core.database.procedures import Pipeline, PipelineTrigger

        definition = pipeline_loader.get(pipeline_slug)
        if not definition:
            return {"error": "Pipeline definition not found"}

        # Get pipeline from DB
        pipe_query = select(Pipeline).where(
            Pipeline.organization_id == organization_id,
            Pipeline.slug == pipeline_slug,
        )
        result = await session.execute(pipe_query)
        pipeline = result.scalar_one_or_none()

        if not pipeline:
            return {"error": "Pipeline not found in database"}

        # Get existing triggers
        triggers_query = select(PipelineTrigger).where(
            PipelineTrigger.pipeline_id == pipeline.id,
        )
        result = await session.execute(triggers_query)
        existing_triggers = result.scalars().all()

        # Map existing by type+config for comparison
        existing_map = {}
        for t in existing_triggers:
            key = f"{t.trigger_type}:{t.cron_expression or t.event_name or 'webhook'}"
            existing_map[key] = t

        # Process definition triggers
        created = 0
        unchanged = 0
        for trigger_def in definition.triggers:
            key = f"{trigger_def.type}:{trigger_def.cron_expression or trigger_def.event_name or 'webhook'}"

            if key in existing_map:
                # Already exists
                unchanged += 1
                del existing_map[key]
            else:
                # Create new
                trigger = PipelineTrigger(
                    pipeline_id=pipeline.id,
                    organization_id=organization_id,
                    trigger_type=trigger_def.type,
                    cron_expression=trigger_def.cron_expression,
                    event_name=trigger_def.event_name,
                    event_filter=trigger_def.event_filter,
                    is_active=True,
                )
                session.add(trigger)
                created += 1

        # Remaining in map are orphaned - deactivate them
        deactivated = 0
        for trigger in existing_map.values():
            trigger.is_active = False
            deactivated += 1

        await session.commit()

        return {
            "created": created,
            "unchanged": unchanged,
            "deactivated": deactivated,
        }


# Global service instance
pipeline_discovery_service = PipelineDiscoveryService()
