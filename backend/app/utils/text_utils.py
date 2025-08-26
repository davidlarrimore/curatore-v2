# backend/app/utils/text_utils.py
import re

def clean_llm_response(text: str) -> str:
    """
    Utility function to clean LLM-generated text by removing common artifacts
    like markdown code block wrappers and excessive newlines.
    """
    if not text:
        return text
    
    # Remove markdown code block wrappers (```markdown ... ``` or ``` ... ```)
    text = re.sub(r'^```(?:markdown|md)?\s*\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```(?:markdown|md)?\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    
    # Remove any leading/trailing whitespace
    text = text.strip()
    
    # Remove multiple consecutive newlines (more than 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Remove common summary prefixes that LLMs add
    for prefix in [r'^## Summary\s*', r'^Summary:\s*', r'^\*\*Summary\*\*:\s*', r'^Document Summary:\s*', r'^Analysis:\s*']:
        text = re.sub(prefix, '', text, flags=re.IGNORECASE)
    
    return text.strip()