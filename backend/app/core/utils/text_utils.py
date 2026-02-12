# backend/app/utils/text_utils.py
import re
from html.parser import HTMLParser


class _HTMLTextExtractor(HTMLParser):
    """Simple HTML to text converter using Python's built-in html.parser."""

    def __init__(self):
        super().__init__()
        self._text_parts = []
        self._skip_data = False

    def handle_starttag(self, tag, attrs):
        # Skip script and style content
        if tag in ('script', 'style'):
            self._skip_data = True
        # Add line breaks for block elements
        elif tag in ('p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._text_parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._skip_data = False
        elif tag in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._text_parts.append('\n')

    def handle_data(self, data):
        if not self._skip_data:
            self._text_parts.append(data)

    def get_text(self) -> str:
        text = ''.join(self._text_parts)
        # Clean up whitespace
        text = re.sub(r'[ \t]+', ' ', text)  # Collapse horizontal whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 consecutive newlines
        text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)  # Strip leading whitespace per line
        return text.strip()


def html_to_text(html: str) -> str:
    """
    Convert HTML to plain text using Python's built-in html.parser.

    - Strips all HTML tags
    - Preserves paragraph/block structure as line breaks
    - Removes script/style content
    - Decodes HTML entities

    Args:
        html: HTML string to convert

    Returns:
        Plain text string
    """
    if not html:
        return ""

    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
        return parser.get_text()
    except Exception:
        # Fallback: simple regex strip if parsing fails
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

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
