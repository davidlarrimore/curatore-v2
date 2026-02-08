"""
Storage Path Service.

Provides utilities for generating human-readable, navigable storage paths
for different content types in MinIO/S3.

Storage Structure:
    {org_id}/
    ├── uploads/                              # File uploads
    │   └── {asset_uuid}/
    │       └── {original_filename}
    │
    ├── scrape/                               # Web scraping - grouped by collection
    │   └── {collection_slug}/
    │       ├── pages/                        # Scraped web pages
    │       │   ├── _index.html              # Root page (/)
    │       │   ├── about.html               # /about
    │       │   ├── article/
    │       │   │   └── some-article.html
    │       │   └── ...
    │       │
    │       └── documents/                    # Downloaded documents
    │           ├── capability-statement.pdf
    │           └── ...
    │
    └── sharepoint/                           # SharePoint imports
        └── {site_name}/
            └── {folder_path}/
                └── {filename}

Processed files mirror this structure in curatore-processed bucket.
"""

import hashlib
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse, unquote
from uuid import UUID

logger = logging.getLogger("curatore.storage_path")


# Maximum path component length (to avoid filesystem issues)
MAX_COMPONENT_LENGTH = 100

# Maximum total path length
MAX_PATH_LENGTH = 500

# Characters that are safe in storage paths
SAFE_CHARS = re.compile(r"[^a-zA-Z0-9._-]")


def slugify(text: str, max_length: int = MAX_COMPONENT_LENGTH) -> str:
    """
    Convert text to a safe slug for storage paths.

    Args:
        text: Text to slugify
        max_length: Maximum length of result

    Returns:
        Safe slug string
    """
    if not text:
        return "_empty"

    # Decode URL encoding
    text = unquote(text)

    # Lowercase
    text = text.lower()

    # Replace spaces and common separators with hyphens
    text = re.sub(r"[\s_]+", "-", text)

    # Remove unsafe characters
    text = SAFE_CHARS.sub("", text)

    # Collapse multiple hyphens
    text = re.sub(r"-+", "-", text)

    # Remove leading/trailing hyphens
    text = text.strip("-")

    # Truncate if too long
    if len(text) > max_length:
        # Try to truncate at a hyphen
        truncated = text[:max_length]
        last_hyphen = truncated.rfind("-")
        if last_hyphen > max_length // 2:
            text = truncated[:last_hyphen]
        else:
            text = truncated

    return text or "_unnamed"


def url_to_path_components(url: str) -> Tuple[str, str, str]:
    """
    Parse URL into domain, path, and extension components.

    Args:
        url: Full URL

    Returns:
        Tuple of (domain, path, extension)
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.strip("/")

    # Determine extension
    extension = ""
    if "." in path.split("/")[-1]:
        path_base, extension = path.rsplit(".", 1)
        extension = extension.lower()
        if extension not in ("html", "htm", "php", "asp", "aspx", "jsp"):
            # Keep the extension in the path for non-HTML files
            pass
        else:
            path = path_base
            extension = "html"

    return domain, path, extension


def scrape_page_path(
    org_id: str,
    collection_slug: str,
    url: str,
    file_type: str = "raw",
) -> str:
    """
    Generate storage path for a scraped web page.

    Args:
        org_id: Organization UUID string
        collection_slug: Collection slug (e.g., "amivero")
        url: Page URL
        file_type: "raw" for HTML, "extracted" for markdown

    Returns:
        Storage path like: {org_id}/scrape/{slug}/pages/article/some-page.html
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    # Handle root page
    if not path:
        filename = "_index"
    else:
        # Convert URL path to storage path
        parts = path.split("/")

        # Slugify each component
        safe_parts = [slugify(part) for part in parts if part]

        if not safe_parts:
            filename = "_index"
        else:
            # Last part is the filename, rest is the directory structure
            filename = safe_parts[-1]
            safe_parts = safe_parts[:-1]

    # Add extension
    extension = "html" if file_type == "raw" else "md"

    # Build path
    if file_type == "raw":
        bucket_type = "pages"
    else:
        bucket_type = "pages"  # Extracted also goes in pages, just with .md

    # Construct full path
    if 'safe_parts' in dir() and safe_parts:
        dir_path = "/".join(safe_parts)
        full_path = f"{org_id}/scrape/{collection_slug}/{bucket_type}/{dir_path}/{filename}.{extension}"
    else:
        full_path = f"{org_id}/scrape/{collection_slug}/{bucket_type}/{filename}.{extension}"

    # Ensure path isn't too long
    if len(full_path) > MAX_PATH_LENGTH:
        # Fall back to hash-based path
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        full_path = f"{org_id}/scrape/{collection_slug}/{bucket_type}/_hashed/{url_hash}.{extension}"

    return full_path


def scrape_document_path(
    org_id: str,
    collection_slug: str,
    filename: str,
    file_type: str = "raw",
) -> str:
    """
    Generate storage path for a document downloaded during scraping.

    Args:
        org_id: Organization UUID string
        collection_slug: Collection slug
        filename: Original document filename
        file_type: "raw" for original, "extracted" for markdown

    Returns:
        Storage path like: {org_id}/scrape/{slug}/documents/capability-statement.pdf
    """
    # Sanitize filename
    safe_filename = slugify_filename(filename)

    if file_type == "extracted":
        # Change extension to .md
        base, _ = safe_filename.rsplit(".", 1) if "." in safe_filename else (safe_filename, "")
        safe_filename = f"{base}.md"

    return f"{org_id}/scrape/{collection_slug}/documents/{safe_filename}"


def slugify_filename(filename: str) -> str:
    """
    Sanitize a filename while preserving extension.

    Args:
        filename: Original filename

    Returns:
        Safe filename
    """
    if not filename:
        return "_unnamed"

    # Split name and extension
    if "." in filename:
        name, ext = filename.rsplit(".", 1)
        ext = ext.lower()
    else:
        name = filename
        ext = ""

    # Slugify the name part
    safe_name = slugify(name, max_length=MAX_COMPONENT_LENGTH - len(ext) - 1)

    if ext:
        return f"{safe_name}.{ext}"
    return safe_name


def upload_path(
    org_id: str,
    asset_id: str,
    filename: str,
    file_type: str = "raw",
) -> str:
    """
    Generate storage path for an uploaded file.

    Uploads keep UUID-based paths for simplicity and deduplication.

    Args:
        org_id: Organization UUID string
        asset_id: Asset UUID string
        filename: Original filename
        file_type: "raw" for original, "extracted" for markdown

    Returns:
        Storage path like: {org_id}/uploads/{asset_id}/{filename}
    """
    safe_filename = slugify_filename(filename)

    if file_type == "extracted":
        base, _ = safe_filename.rsplit(".", 1) if "." in safe_filename else (safe_filename, "")
        safe_filename = f"{base}.md"

    return f"{org_id}/uploads/{asset_id}/{safe_filename}"


def sharepoint_path(
    org_id: str,
    site_name: str,
    folder_path: str,
    filename: str,
    file_type: str = "raw",
) -> str:
    """
    Generate storage path for a SharePoint file.

    Preserves SharePoint folder structure for familiarity.

    Args:
        org_id: Organization UUID string
        site_name: SharePoint site name (slugified)
        folder_path: Folder path within SharePoint
        filename: Original filename
        file_type: "raw" for original, "extracted" for markdown

    Returns:
        Storage path like: {org_id}/sharepoint/{site}/Documents/Reports/q4-report.pdf
    """
    # Slugify site name
    safe_site = slugify(site_name)

    # Sanitize folder path components
    if folder_path:
        path_parts = folder_path.strip("/").split("/")
        safe_path_parts = [slugify(p) for p in path_parts if p]
        safe_folder_path = "/".join(safe_path_parts)
    else:
        safe_folder_path = ""

    # Sanitize filename
    safe_filename = slugify_filename(filename)

    if file_type == "extracted":
        base, _ = safe_filename.rsplit(".", 1) if "." in safe_filename else (safe_filename, "")
        safe_filename = f"{base}.md"

    if safe_folder_path:
        return f"{org_id}/sharepoint/{safe_site}/{safe_folder_path}/{safe_filename}"
    return f"{org_id}/sharepoint/{safe_site}/{safe_filename}"


def temp_path(
    org_id: str,
    content_hash: str,
    filename: str,
) -> str:
    """
    Generate temporary storage path for processing.

    Args:
        org_id: Organization UUID string
        content_hash: SHA256 hash of content
        filename: Original filename

    Returns:
        Temporary storage path
    """
    safe_filename = slugify_filename(filename)
    return f"{org_id}/temp/{content_hash[:16]}/{safe_filename}"


def sharepoint_sync_path(
    org_id: str,
    sync_slug: str,
    relative_path: str,
    filename: str,
    file_type: str = "raw",
) -> str:
    """
    Generate storage path for a SharePoint synced file.

    Files are stored preserving the folder structure from SharePoint
    within the sync config's slug directory.

    Args:
        org_id: Organization UUID string
        sync_slug: Sync config slug (e.g., "it-documents")
        relative_path: Relative path within SharePoint synced folder
        filename: Original filename
        file_type: "raw" for original, "extracted" for markdown

    Returns:
        Storage path like: {org_id}/sharepoint/{sync_slug}/{relative_path}/{filename}

    Examples:
        >>> sharepoint_sync_path("org1", "it-docs", "Reports/Q4", "summary.pdf")
        "org1/sharepoint/it-docs/reports/q4/summary.pdf"

        >>> sharepoint_sync_path("org1", "hr-files", "", "handbook.docx")
        "org1/sharepoint/hr-files/handbook.docx"
    """
    # Slugify the sync slug
    safe_slug = slugify(sync_slug)

    # Sanitize relative path components
    if relative_path:
        path_parts = relative_path.strip("/").split("/")
        safe_path_parts = [slugify(p) for p in path_parts if p]
        safe_relative_path = "/".join(safe_path_parts)
    else:
        safe_relative_path = ""

    # Sanitize filename
    safe_filename = slugify_filename(filename)

    if file_type == "extracted":
        base, _ = safe_filename.rsplit(".", 1) if "." in safe_filename else (safe_filename, "")
        safe_filename = f"{base}.md"

    if safe_relative_path:
        return f"{org_id}/sharepoint/{safe_slug}/{safe_relative_path}/{safe_filename}"
    return f"{org_id}/sharepoint/{safe_slug}/{safe_filename}"


# Convenience class for organized access
class StoragePathService:
    """
    Service for generating storage paths.

    Usage:
        from app.core.storage.storage_path_service import storage_paths

        # Scrape paths
        raw_path = storage_paths.scrape_page(org_id, "amivero", url)
        md_path = storage_paths.scrape_page(org_id, "amivero", url, extracted=True)
        doc_path = storage_paths.scrape_document(org_id, "amivero", "report.pdf")

        # Upload paths
        path = storage_paths.upload(org_id, asset_id, "document.pdf")

        # SharePoint paths
        path = storage_paths.sharepoint(org_id, "MySite", "Documents/Reports", "q4.xlsx")
    """

    def scrape_page(
        self,
        org_id: str,
        collection_slug: str,
        url: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for scraped page."""
        file_type = "extracted" if extracted else "raw"
        return scrape_page_path(org_id, collection_slug, url, file_type)

    def scrape_document(
        self,
        org_id: str,
        collection_slug: str,
        filename: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for scraped document."""
        file_type = "extracted" if extracted else "raw"
        return scrape_document_path(org_id, collection_slug, filename, file_type)

    def upload(
        self,
        org_id: str,
        asset_id: str,
        filename: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for uploaded file."""
        file_type = "extracted" if extracted else "raw"
        return upload_path(org_id, asset_id, filename, file_type)

    def sharepoint(
        self,
        org_id: str,
        site_name: str,
        folder_path: str,
        filename: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for SharePoint file."""
        file_type = "extracted" if extracted else "raw"
        return sharepoint_path(org_id, site_name, folder_path, filename, file_type)

    def temp(
        self,
        org_id: str,
        content_hash: str,
        filename: str,
    ) -> str:
        """Generate temporary path."""
        return temp_path(org_id, content_hash, filename)

    def sharepoint_sync(
        self,
        org_id: str,
        sync_slug: str,
        relative_path: str,
        filename: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for SharePoint synced file."""
        file_type = "extracted" if extracted else "raw"
        return sharepoint_sync_path(org_id, sync_slug, relative_path, filename, file_type)


def sam_attachment_path(
    org_id: str,
    agency: str,
    bureau: str,
    notice_id: str,
    filename: str,
    file_type: str = "raw",
) -> str:
    """
    Generate storage path for a SAM.gov attachment.

    Preserves the SAM folder structure for organized browsing.

    Args:
        org_id: Organization UUID string
        agency: Contracting agency name (e.g., "DEPT OF DEFENSE")
        bureau: Bureau/sub-agency name (e.g., "ARMY")
        notice_id: SAM.gov solicitation number (e.g., "W123ABC")
        filename: Original filename
        file_type: "raw" for original, "extracted" for markdown

    Returns:
        Storage path like: {org_id}/sam/{agency}/{bureau}/solicitations/{notice_id}/attachments/{filename}
    """
    # Slugify agency names to be safe for paths
    safe_agency = slugify(agency) if agency else "unknown-agency"
    safe_bureau = slugify(bureau) if bureau else safe_agency
    safe_notice_id = slugify(notice_id) if notice_id else "unknown-notice"

    # Sanitize filename
    safe_filename = slugify_filename(filename)

    if file_type == "extracted":
        base, _ = safe_filename.rsplit(".", 1) if "." in safe_filename else (safe_filename, "")
        safe_filename = f"{base}.md"

    return f"{org_id}/sam/{safe_agency}/{safe_bureau}/solicitations/{safe_notice_id}/attachments/{safe_filename}"


# Convenience class for organized access
class StoragePathService:
    """
    Service for generating storage paths.

    Usage:
        from app.core.storage.storage_path_service import storage_paths

        # Scrape paths
        raw_path = storage_paths.scrape_page(org_id, "amivero", url)
        md_path = storage_paths.scrape_page(org_id, "amivero", url, extracted=True)
        doc_path = storage_paths.scrape_document(org_id, "amivero", "report.pdf")

        # Upload paths
        path = storage_paths.upload(org_id, asset_id, "document.pdf")

        # SharePoint paths
        path = storage_paths.sharepoint(org_id, "MySite", "Documents/Reports", "q4.xlsx")

        # SAM.gov paths
        path = storage_paths.sam_attachment(org_id, "dept-of-defense", "army", "W123ABC", "rfp.pdf")
    """

    def scrape_page(
        self,
        org_id: str,
        collection_slug: str,
        url: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for scraped page."""
        file_type = "extracted" if extracted else "raw"
        return scrape_page_path(org_id, collection_slug, url, file_type)

    def scrape_document(
        self,
        org_id: str,
        collection_slug: str,
        filename: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for scraped document."""
        file_type = "extracted" if extracted else "raw"
        return scrape_document_path(org_id, collection_slug, filename, file_type)

    def upload(
        self,
        org_id: str,
        asset_id: str,
        filename: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for uploaded file."""
        file_type = "extracted" if extracted else "raw"
        return upload_path(org_id, asset_id, filename, file_type)

    def sharepoint(
        self,
        org_id: str,
        site_name: str,
        folder_path: str,
        filename: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for SharePoint file."""
        file_type = "extracted" if extracted else "raw"
        return sharepoint_path(org_id, site_name, folder_path, filename, file_type)

    def temp(
        self,
        org_id: str,
        content_hash: str,
        filename: str,
    ) -> str:
        """Generate temporary path."""
        return temp_path(org_id, content_hash, filename)

    def sharepoint_sync(
        self,
        org_id: str,
        sync_slug: str,
        relative_path: str,
        filename: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for SharePoint synced file."""
        file_type = "extracted" if extracted else "raw"
        return sharepoint_sync_path(org_id, sync_slug, relative_path, filename, file_type)

    def sam_attachment(
        self,
        org_id: str,
        agency: str,
        bureau: str,
        notice_id: str,
        filename: str,
        extracted: bool = False,
    ) -> str:
        """Generate path for SAM.gov attachment."""
        file_type = "extracted" if extracted else "raw"
        return sam_attachment_path(org_id, agency, bureau, notice_id, filename, file_type)


# Singleton instance
storage_paths = StoragePathService()
