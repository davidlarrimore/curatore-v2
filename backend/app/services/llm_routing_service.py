# backend/app/services/llm_routing_service.py
"""
LLM Routing Service - Centralized model resolution for task types.

This service resolves which LLM model to use for a given task based on:
1. Explicit model parameter (from procedure YAML)
2. Organization settings (database overrides)
3. config.yml task_types configuration
4. Function default task type with fallback to default_model

Usage:
    from app.services.llm_routing_service import llm_routing_service

    # Get model for a task type
    config = await llm_routing_service.get_config_for_task(
        task_type=LLMTaskType.STANDARD,
        organization_id=org_id,
        session=db_session,
        explicit_model="claude-opus-4"  # Optional override
    )
"""

import logging
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_models import (
    LLMTaskType,
    LLMTaskConfig,
    DEFAULT_FUNCTION_TASK_TYPES,
    DEFAULT_TEMPERATURES,
)
from app.services.config_loader import config_loader

logger = logging.getLogger(__name__)


class LLMRoutingService:
    """
    Centralized LLM model routing based on task types.

    Resolution Priority:
    1. Explicit model parameter (from procedure YAML step)
    2. Organization settings (database)
    3. config.yml task_types
    4. Default model from config
    """

    async def get_config_for_task(
        self,
        task_type: LLMTaskType,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None,
        explicit_model: Optional[str] = None,
        explicit_temperature: Optional[float] = None,
    ) -> LLMTaskConfig:
        """
        Resolve the complete LLM configuration for a task.

        Args:
            task_type: The type of task (embedding, quick, standard, quality, bulk, reasoning)
            organization_id: Organization UUID for database override lookup
            session: Database session for organization settings
            explicit_model: Override model from procedure YAML
            explicit_temperature: Override temperature from procedure YAML

        Returns:
            LLMTaskConfig with resolved model, temperature, and other settings
        """
        # Priority 1: Explicit model parameter (from procedure YAML)
        if explicit_model:
            logger.debug(f"Using explicit model override: {explicit_model}")
            return LLMTaskConfig(
                model=explicit_model,
                temperature=explicit_temperature if explicit_temperature is not None
                            else DEFAULT_TEMPERATURES.get(task_type, 0.5)
            )

        # Priority 2: Organization settings (database)
        if organization_id and session:
            org_config = await self._get_organization_override(
                session, organization_id, task_type
            )
            if org_config:
                logger.debug(f"Using organization override for {task_type.value}")
                return org_config

        # Priority 3 & 4: config.yml task_types or default_model
        config = config_loader.get_task_type_config(task_type)
        logger.debug(f"Using config.yml for {task_type.value}: {config.model}")
        return config

    async def get_model_for_task(
        self,
        task_type: LLMTaskType,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None,
        explicit_model: Optional[str] = None,
    ) -> str:
        """
        Convenience method to get just the model name for a task.

        Args:
            task_type: The type of task
            organization_id: Organization UUID
            session: Database session
            explicit_model: Override model from procedure YAML

        Returns:
            Model name string
        """
        config = await self.get_config_for_task(
            task_type=task_type,
            organization_id=organization_id,
            session=session,
            explicit_model=explicit_model,
        )
        return config.model

    async def get_config_for_function(
        self,
        function_name: str,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None,
        explicit_model: Optional[str] = None,
        explicit_temperature: Optional[float] = None,
    ) -> LLMTaskConfig:
        """
        Get LLM configuration for a function by looking up its default task type.

        Args:
            function_name: Name of the function (e.g., "llm_summarize", "llm_classify")
            organization_id: Organization UUID
            session: Database session
            explicit_model: Override model from procedure YAML
            explicit_temperature: Override temperature from procedure YAML

        Returns:
            LLMTaskConfig for the function's task type
        """
        # Get the default task type for this function
        task_type = DEFAULT_FUNCTION_TASK_TYPES.get(function_name, LLMTaskType.STANDARD)

        return await self.get_config_for_task(
            task_type=task_type,
            organization_id=organization_id,
            session=session,
            explicit_model=explicit_model,
            explicit_temperature=explicit_temperature,
        )

    async def _get_organization_override(
        self,
        session: AsyncSession,
        organization_id: UUID,
        task_type: LLMTaskType,
    ) -> Optional[LLMTaskConfig]:
        """
        Get organization-specific task type override from database.

        Args:
            session: Database session
            organization_id: Organization UUID
            task_type: Task type to look up

        Returns:
            LLMTaskConfig if override exists, None otherwise
        """
        try:
            from sqlalchemy import select
            from app.database.models import OrganizationSetting

            # Query for organization LLM settings
            result = await session.execute(
                select(OrganizationSetting).where(
                    OrganizationSetting.organization_id == organization_id,
                    OrganizationSetting.key == f"llm.task_types.{task_type.value}"
                )
            )
            setting = result.scalar_one_or_none()

            if setting and setting.value:
                # Parse the stored JSON config
                config_data = setting.value
                if isinstance(config_data, dict) and "model" in config_data:
                    return LLMTaskConfig(
                        model=config_data["model"],
                        temperature=config_data.get("temperature"),
                        max_tokens=config_data.get("max_tokens"),
                        timeout=config_data.get("timeout"),
                    )
        except Exception as e:
            # OrganizationSetting table might not exist yet
            logger.debug(f"Could not get organization override: {e}")

        return None

    def get_task_type_for_function(self, function_name: str) -> LLMTaskType:
        """
        Get the default task type for a function.

        Args:
            function_name: Name of the function

        Returns:
            LLMTaskType (defaults to STANDARD if not configured)
        """
        return DEFAULT_FUNCTION_TASK_TYPES.get(function_name, LLMTaskType.STANDARD)

    def get_all_task_types(self) -> Dict[str, LLMTaskConfig]:
        """
        Get all configured task types with their current settings.

        Useful for admin UI to display current configuration.

        Returns:
            Dict mapping task type name to LLMTaskConfig
        """
        result = {}
        for task_type in LLMTaskType:
            config = config_loader.get_task_type_config(task_type)
            result[task_type.value] = config
        return result


# Global singleton instance
llm_routing_service = LLMRoutingService()


def get_llm_routing_service() -> LLMRoutingService:
    """
    Get the global LLM routing service instance.

    Returns:
        LLMRoutingService singleton
    """
    return llm_routing_service
