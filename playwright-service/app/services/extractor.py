"""
Content Extractor Service.

Extracts structured content from rendered HTML pages:
- Converts HTML to clean markdown
- Extracts all links for crawl queue
- Identifies document links (PDFs, DOCXs, etc.)
"""

import logging
import re
from typing import List, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, NavigableString
from markdownify import markdownify as md

from ..models import LinkInfo, DocumentLink

logger = logging.getLogger("playwright.extractor")


def clean_html(html: str) -> str:
    """
    Clean HTML by removing scripts, styles, and other non-content elements.

    Args:
        html: Raw HTML content

    Returns:
        Cleaned HTML string
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove script and style elements
    for element in soup.find_all(["script", "style", "noscript", "iframe", "svg"]):
        element.decompose()

    # Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove hidden elements
    for element in soup.find_all(attrs={"hidden": True}):
        element.decompose()
    for element in soup.find_all(attrs={"style": re.compile(r"display:\s*none", re.I)}):
        element.decompose()
    for element in soup.find_all(attrs={"style": re.compile(r"visibility:\s*hidden", re.I)}):
        element.decompose()

    return str(soup)


def html_to_markdown(html: str) -> str:
    """
    Convert HTML to clean markdown preserving structure.

    Args:
        html: HTML content

    Returns:
        Markdown string
    """
    # Clean HTML first
    cleaned = clean_html(html)

    # Convert to markdown
    markdown = md(
        cleaned,
        heading_style="atx",
        bullets="-",
        strip=["script", "style", "noscript", "iframe"],
        escape_underscores=False,
        escape_asterisks=False,
    )

    # Clean up excessive whitespace
    # Remove more than 2 consecutive newlines
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)

    # Remove leading/trailing whitespace from lines
    lines = [line.rstrip() for line in markdown.split("\n")]
    markdown = "\n".join(lines)

    # Remove leading/trailing whitespace
    markdown = markdown.strip()

    return markdown


def extract_text(html: str) -> str:
    """
    Extract clean text content from HTML.

    Args:
        html: HTML content

    Returns:
        Plain text string
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove script and style elements
    for element in soup.find_all(["script", "style", "noscript"]):
        element.decompose()

    # Get text with proper spacing
    text = soup.get_text(separator=" ", strip=True)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def extract_title(html: str) -> str:
    """
    Extract page title from HTML.

    Args:
        html: HTML content

    Returns:
        Page title or empty string
    """
    soup = BeautifulSoup(html, "lxml")

    # Try <title> tag first
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()

    # Try <h1> as fallback
    h1_tag = soup.find("h1")
    if h1_tag:
        return h1_tag.get_text(strip=True)

    # Try og:title meta tag
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    return ""


def extract_links(html: str, base_url: str) -> List[LinkInfo]:
    """
    Extract all links from HTML content.

    Args:
        html: HTML content
        base_url: Base URL for resolving relative links

    Returns:
        List of LinkInfo objects
    """
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen_urls = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]

        # Skip anchors, javascript, mailto, tel
        if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue

        # Resolve relative URLs
        absolute_url = urljoin(base_url, href)

        # Parse and normalize
        parsed = urlparse(absolute_url)
        if parsed.scheme not in ("http", "https"):
            continue

        # Remove fragment
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            normalized += f"?{parsed.query}"

        # Skip duplicates
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)

        # Get link text
        text = anchor.get_text(strip=True)

        # Get rel attribute
        rel = anchor.get("rel")
        if isinstance(rel, list):
            rel = " ".join(rel)

        links.append(LinkInfo(
            url=normalized,
            text=text,
            rel=rel,
        ))

    return links


def extract_document_links(
    links: List[LinkInfo],
    document_extensions: List[str],
) -> List[DocumentLink]:
    """
    Filter links to find document downloads.

    Args:
        links: List of all links
        document_extensions: Extensions to consider as documents

    Returns:
        List of DocumentLink objects
    """
    document_links = []
    extensions = [ext.lower() for ext in document_extensions]

    for link in links:
        # Check if URL ends with a document extension
        parsed = urlparse(link.url)
        path_lower = parsed.path.lower()

        for ext in extensions:
            if path_lower.endswith(ext):
                # Extract filename from URL
                filename = parsed.path.split("/")[-1]
                if not filename:
                    filename = f"document{ext}"

                document_links.append(DocumentLink(
                    url=link.url,
                    filename=filename,
                    extension=ext,
                    link_text=link.text,
                ))
                break

    return document_links


def extract_content(
    html: str,
    base_url: str,
    document_extensions: List[str],
) -> Tuple[str, str, str, List[LinkInfo], List[DocumentLink]]:
    """
    Extract all content from rendered HTML.

    Args:
        html: Rendered HTML content
        base_url: Base URL for link resolution
        document_extensions: Extensions to identify as documents

    Returns:
        Tuple of (markdown, text, title, links, document_links)
    """
    # Extract structured content
    markdown = html_to_markdown(html)
    text = extract_text(html)
    title = extract_title(html)

    # Extract links
    links = extract_links(html, base_url)

    # Filter document links
    document_links = extract_document_links(links, document_extensions)

    logger.debug(
        f"Extracted content: {len(markdown)} chars markdown, "
        f"{len(links)} links, {len(document_links)} documents"
    )

    return markdown, text, title, links, document_links
