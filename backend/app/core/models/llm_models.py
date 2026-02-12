# backend/app/models/llm_models.py
"""
LLM Task Type Models - Configuration for model routing.

Defines the taxonomy of LLM task types and their configurations.
Task types allow different models to be used for different purposes:
- embedding: Vector representations (specialized embedding models)
- quick: Fast, simple decisions (economy models like Haiku)
- standard: Balanced quality/cost (mid-tier models like Sonnet)
- quality: High-stakes outputs (premium models like Opus)
- bulk: High-volume batch processing (cheapest viable models)
- reasoning: Complex multi-step analysis (best available models)
"""

from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field


class LLMTaskType(str, Enum):
    """
    LLM task type categories for model routing.

    Each task type maps to a model configuration, allowing different
    models to be used for different purposes based on complexity,
    volume, and quality requirements.
    """
    EMBEDDING = "embedding"   # Vector embeddings (specialized model)
    QUICK = "quick"           # Fast decisions: classify, decide, route
    STANDARD = "standard"     # Balanced: summarize, extract, generate
    QUALITY = "quality"       # High-stakes: evaluate, final reports
    BULK = "bulk"             # High-volume: map phase of chunked processing
    REASONING = "reasoning"   # Complex: multi-step analysis, synthesis


class LLMTaskConfig(BaseModel):
    """
    Configuration for a specific LLM task type.

    Attributes:
        model: Model identifier (e.g., "claude-4-5-haiku", "gpt-4o")
        temperature: Sampling temperature (0.0-2.0, lower = more deterministic)
        max_tokens: Maximum tokens in response
        timeout: Request timeout in seconds
    """
    model: str = Field(..., description="Model identifier")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, gt=0, description="Maximum response tokens")
    timeout: Optional[int] = Field(None, gt=0, description="Request timeout in seconds")

    class Config:
        extra = "allow"  # Allow additional provider-specific fields


class LLMRoutingConfig(BaseModel):
    """
    Complete LLM routing configuration.

    Defines the default model and task-type-specific configurations.

    Attributes:
        default_model: Fallback model when task type not configured
        task_types: Map of task type to configuration
    """
    default_model: str = Field(..., description="Default model for unspecified task types")
    task_types: Dict[LLMTaskType, LLMTaskConfig] = Field(
        default_factory=dict,
        description="Task type configurations"
    )

    def get_config_for_task(self, task_type: LLMTaskType) -> LLMTaskConfig:
        """Get configuration for a task type, falling back to default."""
        if task_type in self.task_types:
            return self.task_types[task_type]
        return LLMTaskConfig(model=self.default_model)

    def get_model_for_task(self, task_type: LLMTaskType) -> str:
        """Get model name for a task type."""
        return self.get_config_for_task(task_type).model


# Default task type assignments for LLM functions
# These can be overridden via config.yml or procedure parameters
DEFAULT_FUNCTION_TASK_TYPES: Dict[str, LLMTaskType] = {
    # LLM Functions
    "llm_classify": LLMTaskType.QUICK,
    "llm_decide": LLMTaskType.QUICK,
    "llm_extract": LLMTaskType.STANDARD,
    "llm_generate": LLMTaskType.STANDARD,
    "llm_summarize": LLMTaskType.STANDARD,
    "llm_route": LLMTaskType.QUICK,

    # Compound Functions
    "analyze_solicitation": LLMTaskType.QUALITY,
    "summarize_solicitations": LLMTaskType.STANDARD,
    "classify_document": LLMTaskType.QUICK,
    "generate_digest": LLMTaskType.STANDARD,

    # Service Operations
    "evaluate_document": LLMTaskType.QUALITY,
    "improve_document": LLMTaskType.STANDARD,
    "summarize_document": LLMTaskType.QUICK,
    "generate_procedure": LLMTaskType.REASONING,
    "sam_summarization": LLMTaskType.STANDARD,

    # Chunked processing phases
    "chunk_map": LLMTaskType.BULK,
    "chunk_reduce": LLMTaskType.STANDARD,

    # Embedding
    "embedding": LLMTaskType.EMBEDDING,
}


# Recommended temperature settings per task type
DEFAULT_TEMPERATURES: Dict[LLMTaskType, float] = {
    LLMTaskType.EMBEDDING: 0.0,      # N/A for embeddings
    LLMTaskType.QUICK: 0.1,          # Very deterministic
    LLMTaskType.STANDARD: 0.5,       # Balanced
    LLMTaskType.QUALITY: 0.3,        # Controlled but nuanced
    LLMTaskType.BULK: 0.3,           # Consistent for batch
    LLMTaskType.REASONING: 0.2,      # Logical, low variance
}
