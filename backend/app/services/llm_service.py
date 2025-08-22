# backend/app/services/llm_service.py
import json
import re
from typing import Optional, Dict, Any
from openai import OpenAI
import httpx
import urllib3

from ..config import settings
from ..models import LLMEvaluation, LLMConnectionStatus


class LLMService:
    """Service for LLM interactions."""
    
    def __init__(self):
        self._client: Optional[OpenAI] = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize OpenAI client with configuration."""
        if not settings.openai_api_key:
            self._client = None
            return
        
        try:
            # Disable SSL warnings if SSL verification is disabled
            if not settings.openai_verify_ssl:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            # Create HTTP client configuration
            http_client = httpx.Client(
                verify=settings.openai_verify_ssl,
                timeout=settings.openai_timeout
            )
            
            self._client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                http_client=http_client,
                max_retries=settings.openai_max_retries
            )
            
        except Exception as e:
            print(f"Warning: Failed to initialize OpenAI client: {e}")
            self._client = None
    
    @property
    def is_available(self) -> bool:
        """Check if LLM client is available."""
        return self._client is not None
    
    async def test_connection(self) -> LLMConnectionStatus:
        """Test the LLM connection and return status."""
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
    
    async def evaluate_document(self, markdown_text: str) -> Optional[LLMEvaluation]:
        """Evaluate document quality using LLM."""
        if not self._client:
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
            
            resp = self._client.chat.completions.create(
                model=settings.openai_model,
                temperature=0,
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
                # Try to extract JSON from response
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
    
    async def improve_document(self, markdown_text: str, prompt: str) -> str:
        """Improve document using LLM with custom prompt."""
        if not self._client:
            return markdown_text
        
        try:
            system_prompt = (
                "You are a technical editor. Improve the given Markdown in-place per the user's instructions. "
                "Preserve facts and structure when possible. Return ONLY the revised Markdown content."
            )
            
            user_prompt = f"Instructions:\n{prompt}\n\nCurrent Markdown:\n```markdown\n{markdown_text}\n```"
            
            resp = self._client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            
            return resp.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"LLM improvement failed: {e}")
            return markdown_text
    
    async def optimize_for_vector_db(self, markdown_text: str) -> str:
        """Optimize document for vector database storage and retrieval."""
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
        """
        
        return await self.improve_document(markdown_text, optimization_prompt)
    
    async def summarize_document(self, markdown_text: str, filename: str) -> str:
        """Generate a summary of the document content."""
        summary_prompt = """
        Analyze this document and provide a concise 2-3 sentence summary that captures:
        1. The main topic/subject matter
        2. The document type (e.g., report, manual, article, etc.)
        3. Key content highlights or purpose
        
        Keep the summary professional and informative, suitable for a document processing log.
        """
        
        return await self.improve_document(markdown_text, summary_prompt)


# Global LLM service instance
llm_service = LLMService()