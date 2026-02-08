# backend/app/procedures/discovery.py
"""
Procedure Discovery Service - Register procedures in database.

On application startup, discovers procedure definitions from:
1. YAML files in definitions/
2. Python-defined procedures

Registers them in the database so they can be:
- Listed via API
- Have triggers configured
- Track execution history

Also cleans up stale procedures where the source YAML file no longer exists.
"""

import logging
import os
from typing import Dict, List, Optional
from uuid import UUID
from datetime import datetime

from croniter import croniter
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .definitions import ProcedureDefinition
from .loader import procedure_loader

logger = logging.getLogger("curatore.procedures.discovery")


def calculate_next_trigger_at(cron_expression: str, base_time: Optional[datetime] = None) -> Optional[datetime]:
    """
    Calculate the next trigger time for a cron expression.

    Args:
        cron_expression: A valid cron expression (5-field or 6-field)
        base_time: Base time to calculate from (defaults to now)

    Returns:
        The next trigger datetime, or None if invalid
    """
    if not cron_expression:
        return None
    try:
        base = base_time or datetime.utcnow()
        cron = croniter(cron_expression, base)
        return cron.get_next(datetime)
    except Exception as e:
        logger.warning(f"Failed to parse cron expression '{cron_expression}': {e}")
        return None


class ProcedureDiscoveryService:
    """
    Discovers and registers procedures in the database.
    """

    async def discover_and_register(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, any]:
        """
        Discover all procedures and register/update them in the database.
        Also cleans up stale YAML-based procedures whose source files no longer exist.

        Args:
            session: Database session
            organization_id: Organization to register procedures for

        Returns:
            Dict with registration and cleanup statistics
        """
        from app.core.database.procedures import Procedure, ProcedureTrigger

        results = {
            "registered": 0,
            "updated": 0,
            "unchanged": 0,
            "removed": 0,
            "errors": [],
        }

        # Discover all procedure definitions
        definitions = procedure_loader.discover_all()
        logger.info(f"Discovered {len(definitions)} procedure definitions")

        # Track which slugs we've seen from YAML files
        discovered_slugs = set(definitions.keys())

        for slug, definition in definitions.items():
            try:
                # Check if procedure already exists
                existing_query = select(Procedure).where(
                    Procedure.organization_id == organization_id,
                    Procedure.slug == slug,
                )
                result = await session.execute(existing_query)
                existing = result.scalar_one_or_none()

                if existing:
                    # Update if definition changed
                    definition_dict = definition.to_dict()
                    if existing.definition != definition_dict or existing.source_path != definition.source_path:
                        existing.name = definition.name
                        existing.description = definition.description
                        existing.definition = definition_dict
                        existing.version = existing.version + 1
                        existing.source_type = definition.source_type
                        existing.source_path = definition.source_path
                        existing.is_system = definition.is_system
                        existing.updated_at = datetime.utcnow()
                        results["updated"] += 1
                        logger.info(f"Updated procedure: {slug}")
                    else:
                        results["unchanged"] += 1
                else:
                    # Create new procedure
                    procedure = Procedure(
                        organization_id=organization_id,
                        name=definition.name,
                        slug=slug,
                        description=definition.description,
                        definition=definition.to_dict(),
                        version=1,
                        is_active=True,
                        is_system=definition.is_system,
                        source_type=definition.source_type,
                        source_path=definition.source_path,
                    )
                    session.add(procedure)
                    await session.flush()

                    # Create triggers
                    for trigger_def in definition.triggers:
                        # Calculate next trigger time for cron triggers
                        next_trigger_at = None
                        if trigger_def.type == "cron" and trigger_def.cron_expression:
                            next_trigger_at = calculate_next_trigger_at(trigger_def.cron_expression)

                        trigger = ProcedureTrigger(
                            procedure_id=procedure.id,
                            organization_id=organization_id,
                            trigger_type=trigger_def.type,
                            cron_expression=trigger_def.cron_expression,
                            event_name=trigger_def.event_name,
                            event_filter=trigger_def.event_filter,
                            is_active=True,
                            next_trigger_at=next_trigger_at,
                        )
                        session.add(trigger)

                    results["registered"] += 1
                    logger.info(f"Created procedure: {slug}")

            except Exception as e:
                logger.error(f"Failed to register procedure {slug}: {e}")
                results["errors"].append(f"{slug}: {e}")

        # Clean up stale YAML-based procedures whose source files no longer exist
        stale_query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.source_type == "yaml",
        )
        result = await session.execute(stale_query)
        yaml_procedures = result.scalars().all()

        for proc in yaml_procedures:
            # Check if this procedure's YAML file still exists
            if proc.slug not in discovered_slugs:
                # YAML file was removed - check if source_path confirms this
                if proc.source_path and not os.path.exists(proc.source_path):
                    logger.info(f"Removing stale procedure: {proc.slug} (source file deleted: {proc.source_path})")
                    await session.delete(proc)
                    results["removed"] += 1
                elif not proc.source_path:
                    # No source path recorded, but slug not in discovered definitions
                    logger.info(f"Removing stale procedure: {proc.slug} (no longer in definitions)")
                    await session.delete(proc)
                    results["removed"] += 1

        await session.commit()
        return results

    async def sync_triggers(
        self,
        session: AsyncSession,
        organization_id: UUID,
        procedure_slug: str,
    ) -> Dict[str, str]:
        """
        Sync triggers for a specific procedure from its definition.

        Args:
            session: Database session
            organization_id: Organization context
            procedure_slug: Procedure to sync triggers for

        Returns:
            Summary of trigger changes
        """
        from app.core.database.procedures import Procedure, ProcedureTrigger

        definition = procedure_loader.get(procedure_slug)
        if not definition:
            return {"error": "Procedure definition not found"}

        # Get procedure from DB
        proc_query = select(Procedure).where(
            Procedure.organization_id == organization_id,
            Procedure.slug == procedure_slug,
        )
        result = await session.execute(proc_query)
        procedure = result.scalar_one_or_none()

        if not procedure:
            return {"error": "Procedure not found in database"}

        # Get existing triggers
        triggers_query = select(ProcedureTrigger).where(
            ProcedureTrigger.procedure_id == procedure.id,
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
                # Already exists - update next_trigger_at if it's a cron trigger
                existing_trigger = existing_map[key]
                if trigger_def.type == "cron" and trigger_def.cron_expression:
                    existing_trigger.next_trigger_at = calculate_next_trigger_at(trigger_def.cron_expression)
                unchanged += 1
                del existing_map[key]
            else:
                # Create new
                # Calculate next trigger time for cron triggers
                next_trigger_at = None
                if trigger_def.type == "cron" and trigger_def.cron_expression:
                    next_trigger_at = calculate_next_trigger_at(trigger_def.cron_expression)

                trigger = ProcedureTrigger(
                    procedure_id=procedure.id,
                    organization_id=organization_id,
                    trigger_type=trigger_def.type,
                    cron_expression=trigger_def.cron_expression,
                    event_name=trigger_def.event_name,
                    event_filter=trigger_def.event_filter,
                    is_active=True,
                    next_trigger_at=next_trigger_at,
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
procedure_discovery_service = ProcedureDiscoveryService()
