# ============================================================================
# backend/app/core/llm/llm_service.py
# ============================================================================
#
# Large Language Model (LLM) Service for Curatore v2
#
# This module provides LLM integration for document processing, evaluation,
# improvement, and optimization. Connection management is delegated to
# LLMAdapter (connectors/adapters/llm_adapter.py); this service owns the
# business logic for document operations.
#
# Supported LLM Providers:
#   - OpenAI API (GPT-3.5, GPT-4, etc.)
#   - Local Ollama servers
#   - LM Studio local servers
#   - OpenWebUI deployments
#   - Any OpenAI-compatible API endpoint
#
# ============================================================================

import json
import logging
import re
from typing import Any, Dict, Optional
from uuid import UUID

from openai import OpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.adapters.llm_adapter import LLMAdapter, llm_adapter
from app.core.llm.llm_routing_service import llm_routing_service
from app.core.models import LLMConnectionStatus, LLMEvaluation
from app.core.models.llm_models import LLMTaskType
from app.core.utils.text_utils import clean_llm_response

logger = logging.getLogger(__name__)


class LLMService:
    """
    Large Language Model service for document processing and evaluation.

    Connection management (client initialization, config resolution, connection
    testing) is delegated to LLMAdapter. This service owns the document
    processing business logic: evaluation, improvement, optimization,
    and summarization.

    Attributes:
        _adapter (LLMAdapter): The adapter handling connection management
    """

    def __init__(self, adapter: Optional[LLMAdapter] = None):
        """
        Initialize the LLM service.

        Args:
            adapter: Optional LLMAdapter instance. Defaults to the global
                     llm_adapter singleton.
        """
        self._adapter = adapter or llm_adapter

    # ========================================================================
    # Backward-compatible property proxies
    # ========================================================================
    # 28+ files access llm_service._client directly. These proxies ensure
    # zero changes needed in any of those consumers.

    @property
    def _client(self) -> Optional[OpenAI]:
        """Proxy to adapter.client for backward compatibility."""
        return self._adapter.client

    @_client.setter
    def _client(self, value):
        """Allow tests to set _client directly."""
        self._adapter._client = value

    @property
    def is_available(self) -> bool:
        """Check if LLM client is available for processing."""
        return self._adapter.is_available

    def _get_model(self, task_type: LLMTaskType = LLMTaskType.STANDARD) -> str:
        """Get the LLM model name for a specific task type."""
        return self._adapter.get_model(task_type)

    def _get_temperature(self, task_type: LLMTaskType = LLMTaskType.STANDARD) -> float:
        """Get the temperature for a specific task type."""
        return self._adapter.get_temperature(task_type)

    async def _get_llm_config(
        self,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Get LLM configuration from database connection or ENV fallback.

        Args:
            organization_id: Organization UUID (optional)
            session: Database session (optional)

        Returns:
            Dict[str, Any]: LLM configuration dict
        """
        if organization_id and session:
            return await self._adapter.resolve_config_for_org(organization_id, session)
        return self._adapter.resolve_config()

    async def _create_client_from_config(self, config: Dict[str, Any]) -> Optional[OpenAI]:
        """Create OpenAI client from configuration dictionary."""
        return self._adapter.create_client_from_config(config)

    def _initialize_client(self) -> None:
        """Reinitialize the LLM client."""
        self._adapter._initialize_client()

    async def test_connection(self) -> LLMConnectionStatus:
        """Test the LLM connection and return detailed status information."""
        return await self._adapter.test_connection()

    # ========================================================================
    # Business logic methods (unchanged)
    # ========================================================================

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful assistant.",
        temperature: float = 0.3,
        max_tokens: int = 4000,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        General-purpose LLM generation for arbitrary prompts.

        Args:
            prompt: The user prompt to send
            system_prompt: System instructions for the model
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response
            organization_id: Organization ID for database connection lookup
            session: Database session for connection lookup

        Returns:
            Dict with "content" key containing the response text,
            or "content" empty string and "error" key on failure.
        """
        task_config = await llm_routing_service.get_config_for_task(
            task_type=LLMTaskType.STANDARD,
            organization_id=organization_id,
            session=session,
        )

        client = self._client
        model = task_config.model

        if organization_id and session:
            config = await self._get_llm_config(organization_id, session)
            client = await self._create_client_from_config(config)

        if not client:
            return {"content": "", "error": "LLM client not available"}

        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
            )

            content = resp.choices[0].message.content.strip()
            return {"content": content}

        except Exception as e:
            logger.error(f"LLM generate failed: {e}")
            return {"content": "", "error": str(e)}

    async def evaluate_document(
        self,
        markdown_text: str,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None
    ) -> Optional[LLMEvaluation]:
        """
        Evaluate document quality using LLM across four key dimensions.

        Args:
            markdown_text (str): The markdown content to evaluate
            organization_id (Optional[UUID]): Organization ID for database connection lookup
            session (Optional[AsyncSession]): Database session for connection lookup

        Returns:
            Optional[LLMEvaluation]: Structured evaluation results or None if LLM unavailable
        """
        # Get LLM configuration for QUALITY task type (high-stakes evaluation)
        task_config = await llm_routing_service.get_config_for_task(
            task_type=LLMTaskType.QUALITY,
            organization_id=organization_id,
            session=session,
        )

        # Get client (from database connection or fallback to ENV-based client)
        client = self._client
        model = task_config.model

        if organization_id and session:
            config = await self._get_llm_config(organization_id, session)
            client = await self._create_client_from_config(config)

        if not client:
            return None

        try:
            system_prompt = (
                "You are an expert documentation reviewer. "
                "Evaluate the document for Clarity, Completeness, Relevance, and Markdown Compatibility. "
                "Score each 1–10 and provide a one-sentence rationale. "
                "Give overall improvement suggestions. "
                "Finally, return pass_recommendation as 'Pass' if ALL categories are sufficient, else 'Fail'."
            )

            format_prompt = (
                "Respond ONLY as compact JSON with keys: "
                "clarity_score, clarity_feedback, "
                "completeness_score, completeness_feedback, "
                "relevance_score, relevance_feedback, "
                "markdown_score, markdown_feedback, "
                "overall_feedback, pass_recommendation."
            )

            content = f"Document (Markdown):\n```markdown\n{markdown_text}\n```"

            resp = client.chat.completions.create(
                model=model,
                temperature=0,  # Deterministic evaluation
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": format_prompt},
                ],
            )

            response_text = resp.choices[0].message.content

            # Try to parse JSON response
            try:
                eval_data = json.loads(response_text)
                return LLMEvaluation(**eval_data)
            except json.JSONDecodeError:
                # Try to extract JSON from response using regex
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    try:
                        eval_data = json.loads(json_match.group(0))
                        return LLMEvaluation(**eval_data)
                    except json.JSONDecodeError:
                        pass

            return None

        except Exception as e:
            print(f"LLM evaluation failed: {e}")
            return None

    async def improve_document(
        self,
        markdown_text: str,
        prompt: str,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None
    ) -> str:
        """
        Improve document content using LLM with a custom improvement prompt.

        Args:
            markdown_text (str): The original markdown content to improve
            prompt (str): Custom instructions for how to improve the document
            organization_id (Optional[UUID]): Organization ID for database connection lookup
            session (Optional[AsyncSession]): Database session for connection lookup

        Returns:
            str: Improved markdown content, or original content if LLM unavailable/fails
        """
        # Get LLM configuration for STANDARD task type (balanced improvement)
        task_config = await llm_routing_service.get_config_for_task(
            task_type=LLMTaskType.STANDARD,
            organization_id=organization_id,
            session=session,
        )

        # Get client (from database connection or fallback to ENV-based client)
        client = self._client
        model = task_config.model
        temperature = task_config.temperature if task_config.temperature is not None else 0.2

        if organization_id and session:
            config = await self._get_llm_config(organization_id, session)
            client = await self._create_client_from_config(config)

        if not client:
            return markdown_text

        try:
            system_prompt = (
                "You are a technical editor. Improve the given Markdown in-place per the user's instructions. "
                "Preserve facts and structure when possible. "
                "Return ONLY the revised Markdown content without any code block wrappers or extra formatting."
            )

            user_prompt = f"Instructions:\n{prompt}\n\nCurrent Markdown:\n```markdown\n{markdown_text}\n```"

            resp = client.chat.completions.create(
                model=model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            improved_content = resp.choices[0].message.content.strip()

            # Clean the response to remove any markdown code block wrappers
            return clean_llm_response(improved_content)

        except Exception as e:
            logger.error(f"LLM improvement failed: {e}")
            return markdown_text

    async def optimize_for_vector_db(
        self,
        markdown_text: str,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None
    ) -> str:
        """
        Optimize document content specifically for vector database storage and retrieval.

        Args:
            markdown_text (str): The original markdown content to optimize
            organization_id (Optional[UUID]): Organization ID for database connection lookup
            session (Optional[AsyncSession]): Database session for connection lookup

        Returns:
            str: Vector-optimized markdown content, or original content if LLM unavailable
        """
        optimization_prompt = """
        Reformat this document to be optimized for vector database storage and retrieval. Follow these guidelines:

        1. **Clear Structure**: Use descriptive headings and subheadings that capture key concepts
        2. **Chunk-Friendly**: Break content into logical, self-contained sections that can stand alone
        3. **Context Rich**: Ensure each section includes enough context to be meaningful when retrieved independently
        4. **Keyword Rich**: Include relevant keywords and synonyms naturally throughout
        5. **Consistent Format**: Use consistent markdown formatting for easy parsing
        6. **Concise but Complete**: Remove redundancy while preserving all important information
        7. **Question-Answer Ready**: Structure content to answer potential user queries
        8. **Cross-References**: Add brief context when referencing other sections

        Transform the content while preserving all factual information and making it ideal for semantic search and retrieval.
        Return only the optimized markdown content without any code block wrappers.
        """

        return await self.improve_document(
            markdown_text,
            optimization_prompt,
            organization_id=organization_id,
            session=session
        )

    async def summarize_document(
        self,
        markdown_text: str,
        filename: str,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None
    ) -> str:
        """
        Generate a concise summary of document content for metadata and previews.

        Args:
            markdown_text (str): The full markdown content to summarize
            filename (str): Original filename (for context)
            organization_id (Optional[UUID]): Organization ID for database connection lookup
            session (Optional[AsyncSession]): Database session for connection lookup

        Returns:
            str: Concise document summary, or error message if LLM unavailable/fails
        """
        # Get LLM configuration for STANDARD task type (summarization)
        task_config = await llm_routing_service.get_config_for_task(
            task_type=LLMTaskType.STANDARD,
            organization_id=organization_id,
            session=session,
        )

        # Get client (from database connection or fallback to ENV-based client)
        client = self._client
        model = task_config.model
        temperature = task_config.temperature if task_config.temperature is not None else 0.1

        if organization_id and session:
            config = await self._get_llm_config(organization_id, session)
            client = await self._create_client_from_config(config)

        if not client:
            return "Unable to generate summary - LLM not available"

        try:
            system_prompt = (
                "You are a document analyzer. Create a concise 2-3 sentence summary that captures: "
                "1. The main topic/subject matter, "
                "2. The document type (e.g., report, manual, guide, etc.), "
                "3. Key content highlights or purpose. "
                "Keep the summary professional and informative. "
                "Return ONLY the summary text without any markdown formatting or code blocks."
            )

            user_prompt = f"Analyze this document and provide a summary:\n\n```markdown\n{markdown_text}\n```"

            resp = client.chat.completions.create(
                model=model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=200  # Limit summary length
            )

            summary = resp.choices[0].message.content.strip()

            # Clean the response to remove any markdown formatting
            summary = clean_llm_response(summary)
            return summary.strip()

        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return f"Summary generation failed: {str(e)[:100]}..."


# ============================================================================
# Global LLM Service Instance
# ============================================================================

# Create a single global instance of the LLM service
# This ensures consistent configuration and connection management across the application
llm_service = LLMService()
