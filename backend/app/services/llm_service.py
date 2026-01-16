# ============================================================================
# backend/app/services/llm_service.py
# ============================================================================
#
# Large Language Model (LLM) Service for Curatore v2
#
# This module provides comprehensive LLM integration for document processing,
# evaluation, improvement, and optimization. It supports OpenAI-compatible APIs
# including local LLM servers (Ollama, LM Studio, OpenWebUI) and hosted services.
#
# Key Features:
#   - Document quality evaluation with structured scoring
#   - Content improvement and rewriting with custom prompts
#   - Vector database optimization for RAG applications
#   - Document summarization with configurable length
#   - Connection testing and status monitoring
#   - SSL verification control for local deployments
#   - Comprehensive error handling and fallback mechanisms
#
# Supported LLM Providers:
#   - OpenAI API (GPT-3.5, GPT-4, etc.)
#   - Local Ollama servers
#   - LM Studio local servers  
#   - OpenWebUI deployments
#   - Any OpenAI-compatible API endpoint
#
# Author: Curatore v2 Development Team
# Version: 2.0.0
# ============================================================================

import json
import re
import logging
from typing import Optional, Dict, Any
from uuid import UUID
from openai import OpenAI
import httpx
import urllib3
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import LLMEvaluation, LLMConnectionStatus
from ..utils.text_utils import clean_llm_response
from ..services.config_loader import config_loader

logger = logging.getLogger(__name__)


class LLMService:
    """
    Large Language Model service for document processing and evaluation.
    
    This service provides a unified interface for interacting with LLMs for various
    document processing tasks including evaluation, improvement, optimization, and
    summarization. It supports OpenAI-compatible APIs and handles connection
    management, SSL verification, and error recovery.
    
    Connection Management:
        - Automatic client initialization from configuration
        - SSL verification control for local LLM servers
        - Connection testing with detailed status reporting
        - Graceful degradation when LLM is unavailable
    
    Processing Features:
        - Document quality evaluation (4 dimensions)
        - Content improvement with custom prompts
        - Vector database optimization for RAG
        - Document summarization with length control
        - JSON response parsing with fallback extraction
    
    Attributes:
        _client (Optional[OpenAI]): Initialized OpenAI client or None if unavailable
    """
    
    def __init__(self):
        """
        Initialize the LLM service with automatic client configuration.
        
        Attempts to create an OpenAI client using configuration from settings.
        If initialization fails (missing API key, network issues, etc.), the
        client will be None and all LLM features will gracefully degrade.
        
        Side Effects:
            - Disables SSL warnings if SSL verification is disabled
            - Creates HTTP client with custom timeout and SSL settings
            - Sets _client to None if initialization fails
        """
        self._client: Optional[OpenAI] = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """
        Initialize OpenAI client with configuration from config.yml or settings.

        Creates an OpenAI client with custom HTTP client configuration for
        SSL verification control and timeout management. This method is
        called during service initialization and can be called again to
        reinitialize the client if settings change.

        Configuration Sources (priority order):
            1. config.yml (if present) via config_loader.get_llm_config()
            2. Environment variables via settings (backward compatibility)

        Configuration Parameters:
            - api_key: API key for authentication
            - base_url: Custom endpoint URL (for local LLMs)
            - verify_ssl: SSL verification control
            - timeout: Request timeout in seconds
            - max_retries: Maximum retry attempts

        Error Handling:
            - Missing API key: Client set to None, no error raised
            - Network/SSL issues: Client set to None, warning printed
            - Configuration errors: Client set to None, exception details logged
        """
        # Try loading from config.yml first
        llm_config = config_loader.get_llm_config()

        if llm_config:
            logger.info("Loading LLM configuration from config.yml")
            api_key = llm_config.api_key
            base_url = llm_config.base_url
            timeout = llm_config.timeout
            max_retries = llm_config.max_retries
            verify_ssl = llm_config.verify_ssl
        else:
            # Fallback to environment variables
            logger.info("Loading LLM configuration from environment variables")
            api_key = settings.openai_api_key
            base_url = settings.openai_base_url
            timeout = settings.openai_timeout
            max_retries = settings.openai_max_retries
            verify_ssl = settings.openai_verify_ssl

        if not api_key:
            logger.warning("No LLM API key configured (checked config.yml and environment)")
            self._client = None
            return

        try:
            # Disable SSL warnings if SSL verification is disabled
            if not verify_ssl:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            # Create HTTP client configuration
            http_client = httpx.Client(
                verify=verify_ssl,
                timeout=timeout
            )

            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client,
                max_retries=max_retries
            )
            
        except Exception as e:
            print(f"Warning: Failed to initialize OpenAI client: {e}")
            self._client = None

    async def _get_llm_config(
        self,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Get LLM configuration from database connection or ENV fallback.

        Tries to get LLM connection from database for the organization.
        If found, uses connection config. Otherwise, falls back to ENV settings.

        Args:
            organization_id: Organization UUID (optional)
            session: Database session (optional)

        Returns:
            Dict[str, Any]: LLM configuration with keys:
                - api_key: API key for authentication
                - model: Model name
                - base_url: API endpoint URL
                - timeout: Request timeout
                - verify_ssl: SSL verification flag

        Priority:
            1. Database connection (if organization_id and session provided)
            2. ENV variables (fallback)
        """
        # Try database connection first
        if organization_id and session:
            try:
                from .connection_service import connection_service

                connection = await connection_service.get_default_connection(
                    session, organization_id, "llm"
                )

                if connection and connection.is_active:
                    config = connection.config
                    return {
                        "api_key": config.get("api_key", ""),
                        "model": config.get("model", settings.openai_model),
                        "base_url": config.get("base_url", settings.openai_base_url),
                        "timeout": config.get("timeout", settings.openai_timeout),
                        "verify_ssl": config.get("verify_ssl", settings.openai_verify_ssl),
                    }
            except Exception as e:
                print(f"Warning: Failed to get LLM connection from database: {e}")

        # Fallback to ENV settings
        return {
            "api_key": settings.openai_api_key,
            "model": settings.openai_model,
            "base_url": settings.openai_base_url,
            "timeout": settings.openai_timeout,
            "verify_ssl": settings.openai_verify_ssl,
        }

    async def _create_client_from_config(self, config: Dict[str, Any]) -> Optional[OpenAI]:
        """
        Create OpenAI client from configuration dictionary.

        Args:
            config: Configuration dictionary with api_key, base_url, etc.

        Returns:
            Optional[OpenAI]: Initialized client or None if config invalid
        """
        api_key = config.get("api_key")
        if not api_key:
            return None

        try:
            # Disable SSL warnings if needed
            verify_ssl = config.get("verify_ssl", True)
            if not verify_ssl:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            # Create HTTP client
            http_client = httpx.Client(
                verify=verify_ssl,
                timeout=config.get("timeout", 60)
            )

            return OpenAI(
                api_key=api_key,
                base_url=config.get("base_url", "https://api.openai.com/v1"),
                http_client=http_client,
                max_retries=settings.openai_max_retries
            )
        except Exception as e:
            print(f"Warning: Failed to create OpenAI client: {e}")
            return None

    @property
    def is_available(self) -> bool:
        """
        Check if LLM client is available for processing.
        
        Returns:
            bool: True if the LLM client is initialized and ready, False otherwise
        
        Usage:
            >>> if llm_service.is_available:
            >>>     result = await llm_service.evaluate_document(content)
            >>> else:
            >>>     print("LLM not available, skipping evaluation")
        """
        return self._client is not None
    
    async def test_connection(self) -> LLMConnectionStatus:
        """
        Test the LLM connection and return detailed status information.
        
        Performs a simple API call to verify that the LLM is reachable and
        responding correctly. This is useful for health checks, configuration
        validation, and debugging connection issues.
        
        Returns:
            LLMConnectionStatus: Detailed connection status including:
                - connected: Whether the connection succeeded
                - endpoint: The API endpoint being used
                - model: The configured model name
                - error: Error message if connection failed
                - response: Sample response from the LLM if successful
                - ssl_verify: SSL verification setting
                - timeout: Request timeout setting
        
        Test Process:
            1. Checks if client is initialized
            2. Sends a simple "Hello" message to the LLM
            3. Expects "OK" response (tests model response capability)
            4. Returns detailed status with all configuration info
        
        Example:
            >>> status = await llm_service.test_connection()
            >>> if status.connected:
            >>>     print(f"LLM ready: {status.model} at {status.endpoint}")
            >>> else:
            >>>     print(f"LLM error: {status.error}")
        """
        if not self._client:
            return LLMConnectionStatus(
                connected=False,
                error="No API key provided or client initialization failed",
                endpoint=settings.openai_base_url,
                model=settings.openai_model,
                ssl_verify=settings.openai_verify_ssl,
                timeout=settings.openai_timeout
            )
        
        try:
            resp = self._client.chat.completions.create(
                model=settings.openai_model,
                messages=[{"role": "user", "content": "Hello, respond with just 'OK'"}],
                max_tokens=10,
                temperature=0
            )
            
            return LLMConnectionStatus(
                connected=True,
                endpoint=settings.openai_base_url,
                model=settings.openai_model,
                response=resp.choices[0].message.content.strip(),
                ssl_verify=settings.openai_verify_ssl,
                timeout=settings.openai_timeout
            )
        except Exception as e:
            return LLMConnectionStatus(
                connected=False,
                error=str(e),
                endpoint=settings.openai_base_url,
                model=settings.openai_model,
                ssl_verify=settings.openai_verify_ssl,
                timeout=settings.openai_timeout
            )
    
    async def evaluate_document(
        self,
        markdown_text: str,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None
    ) -> Optional[LLMEvaluation]:
        """
        Evaluate document quality using LLM across four key dimensions.

        Performs comprehensive document evaluation using structured prompting to
        assess document quality for RAG applications. The LLM evaluates content
        across four dimensions and provides actionable feedback for improvements.

        Args:
            markdown_text (str): The markdown content to evaluate
            organization_id (Optional[UUID]): Organization ID for database connection lookup
            session (Optional[AsyncSession]): Database session for connection lookup

        Returns:
            Optional[LLMEvaluation]: Structured evaluation results or None if LLM unavailable

        Connection Priority:
            1. Database connection (if organization_id and session provided)
            2. ENV-based client (fallback, backward compatible)
        
        Evaluation Dimensions:
            1. Clarity (1-10): Document structure, readability, logical flow
            2. Completeness (1-10): Information preservation, missing content detection  
            3. Relevance (1-10): Content focus, unnecessary information identification
            4. Markdown Quality (1-10): Formatting consistency, structure quality
        
        Response Structure:
            - Individual scores and feedback for each dimension
            - Overall improvement suggestions
            - Pass/Fail recommendation for RAG readiness
            - JSON format with fallback parsing for malformed responses
        
        Error Handling:
            - Client unavailable: Returns None
            - API errors: Returns None, logs error details
            - JSON parsing errors: Attempts regex extraction, returns None on failure
        
        Example:
            >>> evaluation = await llm_service.evaluate_document(content)
            >>> if evaluation and evaluation.clarity_score >= 7:
            >>>     print(f"Document clarity is good: {evaluation.clarity_feedback}")
        """
        # Get client (from database connection or fallback to ENV-based client)
        client = self._client
        model = settings.openai_model

        if organization_id and session:
            config = await self._get_llm_config(organization_id, session)
            client = await self._create_client_from_config(config)
            model = config.get("model", settings.openai_model)

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

        Uses the LLM to rewrite and improve document content based on specific
        user instructions. This method preserves factual content while improving
        structure, clarity, and formatting according to the provided prompt.

        Args:
            markdown_text (str): The original markdown content to improve
            prompt (str): Custom instructions for how to improve the document
            organization_id (Optional[UUID]): Organization ID for database connection lookup
            session (Optional[AsyncSession]): Database session for connection lookup

        Returns:
            str: Improved markdown content, or original content if LLM unavailable/fails

        Connection Priority:
            1. Database connection (if organization_id and session provided)
            2. ENV-based client (fallback, backward compatible)

        Improvement Process:
            1. Sends structured prompt with improvement instructions
            2. Includes original content in markdown code block
            3. Requests only the improved content (no wrappers)
            4. Cleans response to remove any code block formatting
            5. Falls back to original content on any error

        Temperature Settings:
            - Uses temperature=0.2 for controlled creativity
            - Balances improvement with content preservation
            - Maintains factual accuracy while enhancing presentation

        Error Handling:
            - Client unavailable: Returns original content
            - API errors: Returns original content, logs error
            - Response parsing errors: Returns original content

        Example:
            >>> prompt = "Make this more concise and add bullet points for key features"
            >>> improved = await llm_service.improve_document(content, prompt)
            >>> if improved != content:
            >>>     print("Document was successfully improved")
        """
        # Get client (from database connection or fallback to ENV-based client)
        client = self._client
        model = settings.openai_model

        if organization_id and session:
            config = await self._get_llm_config(organization_id, session)
            client = await self._create_client_from_config(config)
            model = config.get("model", settings.openai_model)

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
                temperature=0.2,  # Allow controlled creativity for editing
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            improved_content = resp.choices[0].message.content.strip()

            # Clean the response to remove any markdown code block wrappers
            return clean_llm_response(improved_content)

        except Exception as e:
            print(f"LLM improvement failed: {e}")
            return markdown_text
    
    async def optimize_for_vector_db(
        self,
        markdown_text: str,
        organization_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None
    ) -> str:
        """
        Optimize document content specifically for vector database storage and retrieval.

        Applies specialized optimization to make documents more suitable for RAG
        applications by improving structure, adding context, and enhancing semantic
        searchability while preserving all factual information.

        Args:
            markdown_text (str): The original markdown content to optimize
            organization_id (Optional[UUID]): Organization ID for database connection lookup
            session (Optional[AsyncSession]): Database session for connection lookup

        Returns:
            str: Vector-optimized markdown content, or original content if LLM unavailable

        Connection Priority:
            1. Database connection (if organization_id and session provided)
            2. ENV-based client (fallback, backward compatible)

        Optimization Guidelines Applied:
            1. Clear Structure: Descriptive headings capturing key concepts
            2. Chunk-Friendly: Self-contained sections that can stand alone
            3. Context Rich: Each section includes sufficient context for independent retrieval
            4. Keyword Rich: Natural inclusion of relevant keywords and synonyms
            5. Consistent Format: Uniform markdown formatting for easy parsing
            6. Concise but Complete: Removes redundancy while preserving information
            7. Question-Answer Ready: Structures content to answer potential queries
            8. Cross-References: Adds context when referencing other sections

        Implementation:
            - Uses the improve_document method with specialized RAG optimization prompt
            - Focuses on semantic search enhancement
            - Maintains factual accuracy while improving retrievability
            - Optimizes for vector embedding and similarity matching

        Use Cases:
            - Preparing documents for vector database ingestion
            - Enhancing semantic search performance
            - Improving RAG question-answering accuracy
            - Creating self-contained, context-rich content chunks

        Example:
            >>> optimized = await llm_service.optimize_for_vector_db(content)
            >>> # optimized content will have better structure and context for RAG
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

        Creates a professional 2-3 sentence summary that captures the document's
        main topic, type, and key content highlights. This is used for document
        previews, processing reports, and quick content identification.

        Args:
            markdown_text (str): The full markdown content to summarize
            filename (str): Original filename (for context, currently not used in prompt)
            organization_id (Optional[UUID]): Organization ID for database connection lookup
            session (Optional[AsyncSession]): Database session for connection lookup

        Returns:
            str: Concise document summary, or error message if LLM unavailable/fails

        Connection Priority:
            1. Database connection (if organization_id and session provided)
            2. ENV-based client (fallback, backward compatible)

        Summary Structure:
            1. Main topic/subject matter identification
            2. Document type classification (report, manual, guide, etc.)
            3. Key content highlights and document purpose

        Length Control:
            - Limited to 200 tokens maximum
            - Targets 2-3 sentences for optimal readability
            - Maintains professional, informative tone
            - Removes markdown formatting from output

        Error Handling:
            - Client unavailable: Returns unavailability message
            - API errors: Returns error message with truncated details
            - Response parsing errors: Returns cleaned response or error message

        Example:
            >>> summary = await llm_service.summarize_document(content, "user_guide.pdf")
            >>> print(f"Document summary: {summary}")
            >>> # Output: "This technical user guide covers software installation..."
        """
        # Get client (from database connection or fallback to ENV-based client)
        client = self._client
        model = settings.openai_model

        if organization_id and session:
            config = await self._get_llm_config(organization_id, session)
            client = await self._create_client_from_config(config)
            model = config.get("model", settings.openai_model)

        if not client:
            return f"Unable to generate summary - LLM not available"

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
                temperature=0.1,  # Deterministic summaries
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
            print(f"Summary generation failed: {e}")
            return f"Summary generation failed: {str(e)[:100]}..."


# ============================================================================
# Global LLM Service Instance
# ============================================================================

# Create a single global instance of the LLM service
# This ensures consistent configuration and connection management across the application
llm_service = LLMService()