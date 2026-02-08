"""
Apache Tika engine implementation.

This module implements the extraction engine for Apache Tika Server,
which provides content detection and extraction for over 1000 file formats.

Apache Tika is a content analysis framework that extracts text and metadata
from documents. It's particularly useful for:
- Wide format support (1000+ file types)
- Metadata extraction
- Language detection
- Content type detection

Tika Server REST API:
- PUT /tika - Extract text (Accept: text/plain or text/html)
- PUT /meta - Extract metadata (Accept: application/json)
- GET /tika - Server version info
- PUT /rmeta - Recursive metadata extraction

Reference: https://cwiki.apache.org/confluence/display/TIKA/TikaServer
"""

from pathlib import Path
from typing import Dict, Any
import httpx
import mimetypes
import re

from .base import BaseExtractionEngine, ExtractionResult


class TikaEngine(BaseExtractionEngine):
    """
    Extraction engine for Apache Tika Server.

    Apache Tika is a content detection and analysis framework that can extract
    text and metadata from over 1000 different file types. It's particularly
    useful for wide format support and metadata extraction.

    Features:
    - Supports 1000+ file formats (PDF, Office, images, archives, etc.)
    - Extracts text as plain text or HTML (converted to Markdown)
    - Extracts metadata (author, title, creation date, etc.)
    - Language detection
    - Configurable output format

    Configuration options:
    - accept_format: 'markdown' (default), 'text', or 'html'
    - extract_metadata: Include document metadata (default: true)
    - language_detection: Enable language detection (default: false)
    - ocr_strategy: OCR strategy for images ('no_ocr', 'ocr_only', 'ocr_and_text')
    """

    @property
    def engine_type(self) -> str:
        return "tika"

    @property
    def display_name(self) -> str:
        return "Apache Tika"

    @property
    def description(self) -> str:
        return "Wide format support (1000+ types) with metadata extraction"

    @property
    def default_endpoint(self) -> str:
        """
        Default API endpoint for text extraction.

        Returns:
            str: API endpoint path (/tika)
        """
        return "/tika"

    def get_supported_formats(self) -> list[str]:
        """
        Get supported file formats for Tika.

        Apache Tika supports 1000+ formats. This is a subset of common formats
        that are most relevant for document processing.

        Returns:
            List of supported file extensions
        """
        return [
            # Documents
            ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md",
            # Spreadsheets (including xlsb - Excel Binary Workbook)
            ".xls", ".xlsx", ".xlsb", ".ods", ".csv",
            # Presentations
            ".ppt", ".pptx", ".odp",
            # Images (with OCR support)
            ".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".webp",
            # Archives (extracts contents)
            ".zip", ".tar", ".gz", ".7z", ".rar",
            # Web content
            ".html", ".htm", ".xml", ".xhtml",
            # Email
            ".eml", ".msg", ".mbox",
            # eBooks
            ".epub", ".mobi",
            # Other
            ".json", ".yaml", ".yml"
        ]

    def _get_tika_headers(self, file_path: Path) -> Dict[str, str]:
        """
        Build HTTP headers for Tika request.

        Args:
            file_path: Path to the file being processed

        Returns:
            Dict of HTTP headers
        """
        # Guess MIME type for the file
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        # Get output format preference from options
        accept_format = self.options.get('accept_format', 'markdown')

        # Determine Accept header based on format preference
        # text/html gives better structure for conversion to markdown
        if accept_format == 'text':
            accept = 'text/plain; charset=UTF-8'
        elif accept_format == 'html':
            accept = 'text/html; charset=UTF-8'
        else:
            # Default: request HTML for better markdown conversion
            accept = 'text/html; charset=UTF-8'

        headers = {
            'Content-Type': mime_type,
            'Accept': accept,
            'Accept-Charset': 'UTF-8',
        }

        # Add OCR strategy if specified
        ocr_strategy = self.options.get('ocr_strategy')
        if ocr_strategy:
            # X-Tika-OCRstrategy: no_ocr, ocr_only, ocr_and_text
            headers['X-Tika-OCRstrategy'] = ocr_strategy

        # Add OCR language if specified
        ocr_language = self.options.get('ocr_language', 'eng')
        if ocr_language:
            headers['X-Tika-OCRLanguage'] = ocr_language

        # Add PDF strategy if specified
        pdf_strategy = self.options.get('pdf_strategy')
        if pdf_strategy:
            # X-Tika-PDFextractInlineImages, X-Tika-PDFOcrStrategy
            headers['X-Tika-PDFOcrStrategy'] = pdf_strategy

        # Add API key if configured
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        return headers

    def _html_to_markdown(self, html_content: str) -> str:
        """
        Convert HTML content to Markdown.

        This is a simple HTML to Markdown converter that handles basic
        HTML elements. For more complex conversions, consider using
        a dedicated library like html2text or markdownify.

        Args:
            html_content: HTML string to convert

        Returns:
            Markdown formatted string
        """
        if not html_content:
            return ""

        # Remove DOCTYPE and html/head tags
        content = re.sub(r'<!DOCTYPE[^>]*>', '', html_content, flags=re.IGNORECASE)
        content = re.sub(r'<html[^>]*>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'</html>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'<head>.*?</head>', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'<body[^>]*>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'</body>', '', content, flags=re.IGNORECASE)

        # Convert headers
        for i in range(6, 0, -1):
            content = re.sub(
                rf'<h{i}[^>]*>(.*?)</h{i}>',
                rf'{"#" * i} \1\n\n',
                content,
                flags=re.IGNORECASE | re.DOTALL
            )

        # Convert paragraphs
        content = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', content, flags=re.IGNORECASE | re.DOTALL)

        # Convert line breaks
        content = re.sub(r'<br\s*/?>', '\n', content, flags=re.IGNORECASE)

        # Convert bold
        content = re.sub(r'<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>', r'**\1**', content, flags=re.IGNORECASE | re.DOTALL)

        # Convert italic
        content = re.sub(r'<(?:i|em)[^>]*>(.*?)</(?:i|em)>', r'*\1*', content, flags=re.IGNORECASE | re.DOTALL)

        # Convert links
        content = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r'[\2](\1)', content, flags=re.IGNORECASE | re.DOTALL)

        # Convert unordered lists
        content = re.sub(r'<ul[^>]*>', '\n', content, flags=re.IGNORECASE)
        content = re.sub(r'</ul>', '\n', content, flags=re.IGNORECASE)
        content = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', content, flags=re.IGNORECASE | re.DOTALL)

        # Convert ordered lists (simplified)
        content = re.sub(r'<ol[^>]*>', '\n', content, flags=re.IGNORECASE)
        content = re.sub(r'</ol>', '\n', content, flags=re.IGNORECASE)

        # Convert code blocks
        content = re.sub(r'<pre[^>]*><code[^>]*>(.*?)</code></pre>', r'```\n\1\n```\n', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'<pre[^>]*>(.*?)</pre>', r'```\n\1\n```\n', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', content, flags=re.IGNORECASE | re.DOTALL)

        # Convert blockquotes
        content = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', r'> \1\n', content, flags=re.IGNORECASE | re.DOTALL)

        # Convert horizontal rules
        content = re.sub(r'<hr\s*/?>', '\n---\n', content, flags=re.IGNORECASE)

        # Convert tables (basic)
        content = re.sub(r'<table[^>]*>', '\n', content, flags=re.IGNORECASE)
        content = re.sub(r'</table>', '\n', content, flags=re.IGNORECASE)
        content = re.sub(r'<tr[^>]*>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'</tr>', ' |\n', content, flags=re.IGNORECASE)
        content = re.sub(r'<t[hd][^>]*>(.*?)</t[hd]>', r'| \1 ', content, flags=re.IGNORECASE | re.DOTALL)

        # Convert div and span (just extract content)
        content = re.sub(r'<div[^>]*>(.*?)</div>', r'\1\n', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'<span[^>]*>(.*?)</span>', r'\1', content, flags=re.IGNORECASE | re.DOTALL)

        # Remove remaining HTML tags
        content = re.sub(r'<[^>]+>', '', content)

        # Decode HTML entities
        content = content.replace('&nbsp;', ' ')
        content = content.replace('&amp;', '&')
        content = content.replace('&lt;', '<')
        content = content.replace('&gt;', '>')
        content = content.replace('&quot;', '"')
        content = content.replace('&#39;', "'")

        # Clean up whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)
        content = re.sub(r' {2,}', ' ', content)
        content = content.strip()

        return content

    async def _extract_metadata(
        self,
        client: httpx.AsyncClient,
        file_path: Path
    ) -> Dict[str, Any]:
        """
        Extract metadata from document using Tika's /meta endpoint.

        Args:
            client: HTTP client
            file_path: Path to the document

        Returns:
            Dictionary of extracted metadata
        """
        if not self.options.get('extract_metadata', True):
            return {}

        try:
            mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            headers = {
                'Content-Type': mime_type,
                'Accept': 'application/json',
            }
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'

            meta_url = f"{self.service_url}/meta"

            with file_path.open('rb') as f:
                response = await client.put(
                    meta_url,
                    headers=headers,
                    content=f.read()
                )

            if response.status_code == 200:
                return response.json()
        except Exception as e:
            self._logger.warning("Failed to extract metadata: %s", str(e))

        return {}

    async def extract(
        self,
        file_path: Path,
        max_retries: int = 2
    ) -> ExtractionResult:
        """
        Extract markdown content using Apache Tika.

        Sends the document to Tika Server for text extraction.
        HTML output is converted to Markdown for better structure.

        Args:
            file_path: Path to the document file
            max_retries: Maximum number of retry attempts

        Returns:
            ExtractionResult with extracted content or error
        """
        url = self.full_url
        timeout_extension = 30.0  # 30 seconds per retry

        for attempt in range(max_retries + 1):
            current_timeout = self.timeout + (attempt * timeout_extension)

            try:
                if attempt == 0:
                    self._logger.info(
                        "Using Apache Tika: %s (timeout: %.0fs) for file: %s",
                        url, current_timeout, file_path.name
                    )
                else:
                    self._logger.info(
                        "Retrying Tika (attempt %d/%d, timeout: %.0fs): %s",
                        attempt + 1, max_retries + 1, current_timeout, file_path.name
                    )
            except Exception:
                pass

            headers = self._get_tika_headers(file_path)

            try:
                async with httpx.AsyncClient(
                    timeout=current_timeout,
                    verify=self.verify_ssl
                ) as client:
                    # Read file content
                    with file_path.open('rb') as f:
                        file_content = f.read()

                    # Send PUT request to Tika
                    response = await client.put(
                        url,
                        headers=headers,
                        content=file_content
                    )

                    response.raise_for_status()

                    # Get response content
                    content_type = response.headers.get('content-type', '').lower()
                    raw_content = response.text

                    # Convert HTML to Markdown if needed
                    accept_format = self.options.get('accept_format', 'markdown')
                    if 'text/html' in content_type or accept_format == 'markdown':
                        markdown_content = self._html_to_markdown(raw_content)
                    else:
                        markdown_content = raw_content

                    if not markdown_content or not markdown_content.strip():
                        self._logger.warning("Tika returned empty content for %s", file_path.name)
                        if attempt < max_retries:
                            continue
                        else:
                            return ExtractionResult(
                                content="",
                                success=False,
                                error="Tika returned empty content",
                                metadata={
                                    "engine": self.engine_type,
                                    "url": url,
                                    "attempts": attempt + 1
                                }
                            )

                    # Extract metadata if enabled
                    metadata_dict = await self._extract_metadata(client, file_path)

                    # Build result metadata
                    result_metadata = {
                        "engine": self.engine_type,
                        "url": url,
                        "attempts": attempt + 1,
                        "processing_time": current_timeout,
                        "content_type": content_type,
                        "options": {
                            "accept_format": accept_format,
                            "ocr_strategy": self.options.get('ocr_strategy'),
                            "ocr_language": self.options.get('ocr_language', 'eng'),
                        }
                    }

                    # Add document metadata if extracted
                    if metadata_dict:
                        result_metadata["document_metadata"] = metadata_dict

                    self._logger.info(
                        "Extraction successful: %d characters extracted from %s",
                        len(markdown_content), file_path.name
                    )

                    return ExtractionResult(
                        content=markdown_content,
                        success=True,
                        metadata=result_metadata
                    )

            except httpx.TimeoutException as e:
                self._logger.warning(
                    "Tika timeout (attempt %d/%d) for %s: %s",
                    attempt + 1, max_retries + 1, file_path.name, str(e)
                )
                if attempt < max_retries:
                    continue
                else:
                    return ExtractionResult(
                        content="",
                        success=False,
                        error=f"Timeout after {max_retries + 1} attempts",
                        metadata={
                            "engine": self.engine_type,
                            "url": url,
                            "attempts": attempt + 1
                        }
                    )

            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                self._logger.error(
                    "Tika extraction failed for %s: %s",
                    file_path.name, error_msg
                )
                return ExtractionResult(
                    content="",
                    success=False,
                    error=error_msg,
                    metadata={
                        "engine": self.engine_type,
                        "url": url,
                        "attempts": attempt + 1,
                        "status_code": e.response.status_code
                    }
                )

            except Exception as e:
                self._logger.error(
                    "Tika error (attempt %d/%d) for %s: %s",
                    attempt + 1, max_retries + 1, file_path.name, str(e)
                )
                if attempt < max_retries:
                    continue
                else:
                    return ExtractionResult(
                        content="",
                        success=False,
                        error=str(e),
                        metadata={
                            "engine": self.engine_type,
                            "url": url,
                            "attempts": attempt + 1
                        }
                    )

        # Should never reach here, but just in case
        return ExtractionResult(
            content="",
            success=False,
            error="Extraction failed after all retries",
            metadata={
                "engine": self.engine_type,
                "url": url,
                "attempts": max_retries + 1
            }
        )

    async def test_connection(self) -> Dict[str, Any]:
        """
        Test connectivity to Apache Tika service.

        Tika Server responds to GET /tika with version information.

        Returns:
            Dict with health status
        """
        headers = {}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        # Try the main tika endpoint first
        health_paths = [
            "/tika",  # Returns "This is Tika Server..."
            "/version",  # Some Tika versions have this
        ]

        async with httpx.AsyncClient(
            timeout=10.0,
            verify=self.verify_ssl
        ) as client:
            for path in health_paths:
                try:
                    url = f"{self.service_url}{path}"
                    response = await client.get(url, headers=headers)

                    if response.status_code == 200:
                        content = response.text
                        # Check if it looks like a Tika response
                        if 'tika' in content.lower() or path == '/tika':
                            # Try to get parsers info for additional details
                            parsers_info = None
                            try:
                                parsers_response = await client.get(
                                    f"{self.service_url}/parsers",
                                    headers={'Accept': 'application/json', **headers}
                                )
                                if parsers_response.status_code == 200:
                                    parsers_data = parsers_response.json()
                                    if isinstance(parsers_data, list):
                                        parsers_info = {"count": len(parsers_data)}
                            except Exception:
                                pass

                            details = {
                                "url": url,
                                "version_info": content[:200] if content else None,
                            }
                            if parsers_info:
                                details["parsers"] = parsers_info

                            return {
                                "success": True,
                                "status": "healthy",
                                "message": "Apache Tika service is responding",
                                "details": details
                            }

                except httpx.RequestError as e:
                    self._logger.debug("Health check failed for %s: %s", path, str(e))
                    continue

        # If all health checks fail, return error
        return {
            "success": False,
            "status": "unhealthy",
            "message": "Cannot reach Apache Tika service",
            "details": {
                "url": self.service_url,
                "tried_paths": health_paths
            }
        }
