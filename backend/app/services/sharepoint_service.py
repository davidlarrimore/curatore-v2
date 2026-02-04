"""SharePoint integration helpers for inventory and downloads via Microsoft Graph."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings


logger = logging.getLogger("curatore.sharepoint")


# =============================================================================
# TOKEN MANAGEMENT
# =============================================================================

class TokenManager:
    """
    Manages Microsoft Graph API tokens with automatic refresh.

    Tokens are refreshed proactively before expiration (at 50 minutes)
    or reactively when a 401 error is encountered.
    """

    # Refresh token at 50 minutes (tokens expire at 60 minutes)
    TOKEN_REFRESH_THRESHOLD_SECONDS = 50 * 60

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
    ):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._token_acquired_at: float = 0
        self._refresh_count = 0

    @property
    def token(self) -> Optional[str]:
        """Get current token (may be expired - use get_valid_token() instead)."""
        return self._token

    def is_token_expired(self) -> bool:
        """Check if token needs refresh based on age."""
        if not self._token:
            return True
        age = time.time() - self._token_acquired_at
        return age >= self.TOKEN_REFRESH_THRESHOLD_SECONDS

    async def get_valid_token(self, client: httpx.AsyncClient) -> str:
        """
        Get a valid token, refreshing if necessary.

        Args:
            client: httpx client to use for token request

        Returns:
            Valid access token
        """
        if self.is_token_expired():
            await self.refresh_token(client)
        return self._token

    async def refresh_token(self, client: httpx.AsyncClient) -> str:
        """
        Force refresh the token.

        Args:
            client: httpx client to use for token request

        Returns:
            New access token
        """
        token_url = _token_url(self.tenant_id)
        token_payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": _scope(),
        }

        token_resp = await client.post(token_url, data=token_payload)
        token_resp.raise_for_status()
        self._token = token_resp.json().get("access_token")

        if not self._token:
            raise RuntimeError("No access_token returned from Microsoft identity platform.")

        self._token_acquired_at = time.time()
        self._refresh_count += 1

        if self._refresh_count > 1:
            logger.info(f"Refreshed Microsoft Graph token (refresh #{self._refresh_count})")

        return self._token

    def get_headers(self) -> Dict[str, str]:
        """Get authorization headers with current token."""
        if not self._token:
            raise RuntimeError("Token not initialized - call get_valid_token() first")
        return {"Authorization": f"Bearer {self._token}"}


# =============================================================================
# RETRY LOGIC FOR TRANSIENT ERRORS
# =============================================================================

# Errors that should trigger a retry with wait
TRANSIENT_ERRORS = (
    "Server disconnected",
    "Connection reset",
    "Connection refused",
    "Timeout",
    "TimeoutException",
    "ConnectError",
    "RemoteProtocolError",
)

async def _retry_on_transient_error(
    func: Callable,
    *args,
    max_retries: int = 3,
    retry_delay_seconds: int = 30,
    on_retry: Optional[Callable[[int, str], None]] = None,
    **kwargs,
):
    """
    Execute a function with retry logic for transient errors.

    Args:
        func: Async function to execute
        max_retries: Maximum number of retry attempts
        retry_delay_seconds: Seconds to wait between retries
        on_retry: Optional callback(attempt, error_message) called before each retry
        *args, **kwargs: Arguments to pass to func

    Returns:
        Result from func

    Raises:
        Last exception if all retries fail
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            # Don't retry on 4xx errors except 401 (which is handled separately for token refresh)
            # and 429 (rate limiting)
            if 400 <= e.response.status_code < 500 and e.response.status_code not in (401, 429):
                raise
            last_error = e
            error_msg = f"HTTP {e.response.status_code}"
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
            last_error = e
            error_msg = str(e)
        except Exception as e:
            # Check if error message contains transient error patterns
            error_str = str(e)
            if any(pattern.lower() in error_str.lower() for pattern in TRANSIENT_ERRORS):
                last_error = e
                error_msg = error_str
            else:
                raise

        # If we get here, we had a retryable error
        if attempt < max_retries:
            if on_retry:
                on_retry(attempt + 1, error_msg)
            logger.warning(
                f"Transient error (attempt {attempt + 1}/{max_retries + 1}): {error_msg}. "
                f"Waiting {retry_delay_seconds}s before retry..."
            )
            await asyncio.sleep(retry_delay_seconds)

    # All retries exhausted
    raise last_error


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _encode_share_url(url: str) -> str:
    encoded = base64.b64encode(url.encode("utf-8")).decode("ascii")
    encoded = encoded.rstrip("=").replace("/", "_").replace("+", "-")
    return f"u!{encoded}"


def _graph_base_url() -> str:
    return os.getenv("MS_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")


def _token_url(tenant_id: str) -> str:
    return os.getenv(
        "MS_GRAPH_TOKEN_URL",
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    )


def _scope() -> str:
    return os.getenv("MS_GRAPH_SCOPE", "https://graph.microsoft.com/.default")


def _default_batch_dir() -> Path:
    """
    Get default batch directory for SharePoint downloads.

    Note: SharePoint service will be updated to upload directly to object storage
    in a future update. For now, downloads to temp directory.
    """
    import tempfile
    temp_dir = Path(tempfile.gettempdir()) / "sharepoint_downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _normalize_folder_path(folder_path: str) -> str:
    if not folder_path:
        return "/"
    return "/" + folder_path.strip("/")


def _build_item(
    item: Dict[str, Any],
    include_folders: bool,
    folder_path: str,
    index: int,
    skip_shortcuts: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Build a normalized item dict from Microsoft Graph DriveItem.

    Captures comprehensive metadata for searching and filtering:
    - Basic info: name, type, size, extension
    - Dates: created, modified (both from SharePoint and file system)
    - People: creator/modifier names and emails
    - Identifiers: id, etag, content hash
    - Location: folder path, web URL, parent path

    Args:
        item: Raw DriveItem from Microsoft Graph API
        include_folders: Whether to include folder items
        folder_path: Current folder path for context
        index: Item index for ordering
        skip_shortcuts: If True, skip shortcuts/links (items with remoteItem)
    """
    # Skip shortcuts/links - they have a remoteItem property pointing to the actual file
    # Shortcuts can cause duplicates since the real file will also be scanned
    if skip_shortcuts and "remoteItem" in item:
        return None

    is_folder = "folder" in item
    if is_folder and not include_folders:
        return None

    name = str(item.get("name", ""))
    ext = ""
    if not is_folder:
        ext = Path(name).suffix.lstrip(".")

    # Extract user info with both name and email
    created_by_info = item.get("createdBy", {}).get("user", {})
    modified_by_info = item.get("lastModifiedBy", {}).get("user", {})

    # Extract file hashes if available
    file_info = item.get("file", {})
    hashes = file_info.get("hashes", {})

    # Extract file system info (original creation/modified times)
    fs_info = item.get("fileSystemInfo", {})

    # Extract parent reference for full path
    parent_ref = item.get("parentReference", {})

    return {
        # Basic identification
        "index": index,
        "name": name,
        "type": "folder" if is_folder else "file",
        "folder": _normalize_folder_path(folder_path),
        "extension": ext,
        "id": item.get("id", ""),

        # Size
        "size": item.get("size"),

        # SharePoint timestamps
        "created": item.get("createdDateTime"),
        "modified": item.get("lastModifiedDateTime"),

        # File system timestamps (original file dates)
        "fs_created": fs_info.get("createdDateTime"),
        "fs_modified": fs_info.get("lastModifiedDateTime"),

        # Creator info
        "created_by": created_by_info.get("displayName"),
        "created_by_email": created_by_info.get("email"),
        "created_by_id": created_by_info.get("id"),

        # Modifier info
        "last_modified_by": modified_by_info.get("displayName"),
        "last_modified_by_email": modified_by_info.get("email"),
        "last_modified_by_id": modified_by_info.get("id"),

        # File type info
        "mime": file_info.get("mimeType"),
        "file_type": file_info.get("mimeType"),

        # Change detection
        "etag": item.get("eTag"),
        "ctag": item.get("cTag"),

        # Content hashes for deduplication/verification
        "quick_xor_hash": hashes.get("quickXorHash"),
        "sha1_hash": hashes.get("sha1Hash"),
        "sha256_hash": hashes.get("sha256Hash"),

        # URLs and paths
        "web_url": item.get("webUrl"),
        "parent_path": parent_ref.get("path"),
        "drive_id": parent_ref.get("driveId"),

        # Description (if set in SharePoint)
        "description": item.get("description"),

        # Sharing info
        "shared": item.get("shared"),
    }


def _should_skip(dest_path: Path, expected_size: Optional[int]) -> bool:
    if not dest_path.exists() or expected_size is None:
        return False
    try:
        return dest_path.stat().st_size == expected_size
    except OSError:
        return False


def _parse_size(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _select_items(items: List[Dict[str, Any]], indices: Optional[List[int]], download_all: bool) -> List[Dict[str, Any]]:
    if download_all:
        return items
    if not indices:
        raise RuntimeError("indices is required when download_all is false")
    selected: List[Dict[str, Any]] = []
    max_index = len(items)
    for idx in indices:
        if 1 <= idx <= max_index:
            selected.append(items[idx - 1])
    if not selected:
        raise RuntimeError("No matching indices selected")
    return selected


def _resolve_destination(
    batch_root: Path,
    item: Dict[str, Any],
    preserve_folders: bool,
) -> Path:
    folder_path = item.get("folder", "/")
    relative_folder = folder_path.strip("/")
    if preserve_folders and relative_folder:
        dest_dir = batch_root / relative_folder
    else:
        dest_dir = batch_root
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / str(item.get("name", ""))


def _extract_drive_info(item: Dict[str, Any]) -> Tuple[str, str]:
    parent_ref = item.get("parentReference", {})
    drive_id = parent_ref.get("driveId", "")
    item_id = item.get("id", "")
    if not drive_id or not item_id:
        raise RuntimeError("Resolved item is missing driveId or id fields.")
    return drive_id, item_id


async def _collect_items(
    client: httpx.AsyncClient,
    graph_base: str,
    token: str,
    drive_id: str,
    root_id: str,
    include_folders: bool,
    recursive: bool,
    page_size: int,
    max_items: Optional[int],
) -> Tuple[List[Dict[str, Any]], int]:
    collected: List[Dict[str, Any]] = []
    pending: List[Tuple[str, str]] = [(root_id, "")]
    fetched = 0

    async def _list_children(item_id: str) -> List[Dict[str, Any]]:
        url = f"{graph_base}/drives/{drive_id}/items/{item_id}/children"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"$top": str(page_size)}
        items: List[Dict[str, Any]] = []
        while url:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            page_items = data.get("value", [])
            items.extend(page_items)
            url = data.get("@odata.nextLink")
            params = None
        return items

    while pending:
        item_id, folder_path = pending.pop(0)
        raw_items = await _list_children(item_id)
        for raw in raw_items:
            is_folder = "folder" in raw
            if is_folder and recursive:
                next_path = f"{folder_path}/{raw.get('name', '')}".strip("/")
                pending.append((raw.get("id", ""), next_path))
            entry = _build_item(raw, include_folders, folder_path, len(collected) + 1)
            if entry:
                collected.append(entry)
                fetched += 1
                if max_items is not None and fetched >= max_items:
                    return collected, fetched
    return collected, fetched


async def _stream_items(
    client: httpx.AsyncClient,
    graph_base: str,
    token_manager: TokenManager,
    drive_id: str,
    root_id: str,
    include_folders: bool,
    recursive: bool,
    page_size: int,
    max_items: Optional[int],
    on_folder_scanned: Optional[callable] = None,
    on_folder_skipped: Optional[callable] = None,
    folder_exclude_patterns: Optional[List[str]] = None,
    retry_delay_seconds: int = 30,
    max_retries: int = 3,
):
    """
    Async generator that yields items as they are discovered.

    This allows processing files immediately while continuing to scan folders,
    rather than waiting for the complete inventory.

    Features:
    - Automatic token refresh before expiration (at 50 minutes)
    - Retry logic for transient errors with configurable delay
    - Handles 401 errors by refreshing token and retrying
    - Folder filtering to skip entire folder hierarchies

    Args:
        client: httpx AsyncClient for making requests
        graph_base: Microsoft Graph API base URL
        token_manager: TokenManager instance for handling token refresh
        drive_id: SharePoint drive ID
        root_id: Root folder ID to start scanning from
        include_folders: Whether to include folder items in results
        recursive: Whether to recursively scan subfolders
        page_size: Number of items per API page
        max_items: Maximum items to return (None for unlimited)
        on_folder_scanned: Optional callback called after each folder is scanned
                          with (folder_path, files_found, folders_pending)
        on_folder_skipped: Optional callback called when a folder is skipped due
                          to exclude patterns, with (folder_name, folder_path)
        folder_exclude_patterns: Optional list of fnmatch patterns to exclude folders
        retry_delay_seconds: Seconds to wait between retries (default: 30)
        max_retries: Maximum retry attempts for transient errors (default: 3)

    Yields:
        Dict items as they are discovered
    """
    pending: List[Tuple[str, str]] = [(root_id, "")]
    fetched = 0
    index = 0

    async def _list_children_single_page(
        url: str,
        params: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Fetch a single page of children with token refresh and retry support.

        Returns:
            Tuple of (items, next_page_url)
        """
        # Ensure token is valid before request
        await token_manager.get_valid_token(client)
        headers = token_manager.get_headers()

        for attempt in range(max_retries + 1):
            try:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                return data.get("value", []), data.get("@odata.nextLink")

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    # Token expired - refresh and retry
                    logger.warning("Received 401 Unauthorized - refreshing token...")
                    await token_manager.refresh_token(client)
                    headers = token_manager.get_headers()
                    if attempt < max_retries:
                        continue
                elif e.response.status_code == 429:
                    # Rate limited - wait and retry
                    retry_after = int(e.response.headers.get("Retry-After", retry_delay_seconds))
                    logger.warning(f"Rate limited (429) - waiting {retry_after}s...")
                    await asyncio.sleep(retry_after)
                    if attempt < max_retries:
                        continue
                elif 400 <= e.response.status_code < 500:
                    # Client error - don't retry
                    raise
                else:
                    # Server error - retry with delay
                    if attempt < max_retries:
                        logger.warning(
                            f"Server error {e.response.status_code} (attempt {attempt + 1}/{max_retries + 1}). "
                            f"Waiting {retry_delay_seconds}s..."
                        )
                        await asyncio.sleep(retry_delay_seconds)
                        continue
                raise

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
                # Transient network error - retry with delay
                if attempt < max_retries:
                    logger.warning(
                        f"Network error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Waiting {retry_delay_seconds}s..."
                    )
                    await asyncio.sleep(retry_delay_seconds)
                    # Refresh token in case it expired during the wait
                    await token_manager.get_valid_token(client)
                    headers = token_manager.get_headers()
                    continue
                raise

            except Exception as e:
                # Check for transient error patterns in message
                error_str = str(e)
                is_transient = any(
                    pattern.lower() in error_str.lower()
                    for pattern in TRANSIENT_ERRORS
                )
                if is_transient and attempt < max_retries:
                    logger.warning(
                        f"Transient error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Waiting {retry_delay_seconds}s..."
                    )
                    await asyncio.sleep(retry_delay_seconds)
                    await token_manager.get_valid_token(client)
                    headers = token_manager.get_headers()
                    continue
                raise

        # Should not reach here, but just in case
        raise RuntimeError("All retries exhausted")

    async def _list_children(item_id: str) -> List[Dict[str, Any]]:
        """List all children of a folder, handling pagination."""
        url = f"{graph_base}/drives/{drive_id}/items/{item_id}/children"
        params = {"$top": str(page_size)}
        items: List[Dict[str, Any]] = []

        while url:
            page_items, next_url = await _list_children_single_page(url, params)
            items.extend(page_items)
            url = next_url
            params = None  # Only use params on first request

        return items

    while pending:
        item_id, folder_path = pending.pop(0)

        try:
            raw_items = await _list_children(item_id)
        except Exception as e:
            # Log error but continue with other folders
            logger.error(f"Failed to list folder '{folder_path}': {e}")
            # Callback with error info
            if on_folder_scanned:
                try:
                    await on_folder_scanned(folder_path or "/", 0, len(pending))
                except Exception:
                    pass
            continue

        files_in_folder = 0

        for raw in raw_items:
            is_folder = "folder" in raw
            if is_folder and recursive:
                folder_name = raw.get('name', '')
                next_path = f"{folder_path}/{folder_name}".strip("/")

                # Check if folder should be excluded
                if folder_exclude_patterns:
                    import fnmatch
                    if any(fnmatch.fnmatch(folder_name, p) for p in folder_exclude_patterns):
                        # Folder matches exclude pattern - skip it entirely
                        if on_folder_skipped:
                            try:
                                await on_folder_skipped(folder_name, next_path)
                            except Exception:
                                pass  # Don't let callback errors stop the scan
                        continue  # Skip - don't add to pending queue

                pending.append((raw.get("id", ""), next_path))

            index += 1
            entry = _build_item(raw, include_folders, folder_path, index)
            if entry:
                if entry.get("type") == "file":
                    files_in_folder += 1
                fetched += 1
                yield entry
                if max_items is not None and fetched >= max_items:
                    return

        # Callback after scanning each folder
        if on_folder_scanned:
            try:
                await on_folder_scanned(folder_path or "/", files_in_folder, len(pending))
            except Exception:
                pass  # Don't let callback errors stop the scan


async def _get_sharepoint_credentials(
    organization_id: Optional[UUID] = None,
    session: Optional[AsyncSession] = None,
) -> Dict[str, str]:
    """
    Get SharePoint credentials from database or environment variables.

    Args:
        organization_id: Optional organization ID for database lookup
        session: Optional database session for connection lookup

    Returns:
        Dict with tenant_id, client_id, and client_secret

    Priority:
        1. Database connection (if organization_id and session provided)
        2. Environment variables (fallback)
    """
    # Try database connection first
    if organization_id and session:
        try:
            from .connection_service import connection_service

            connection = await connection_service.get_default_connection(
                session, organization_id, "sharepoint"
            )

            if connection and connection.is_active:
                config = connection.config
                return {
                    "tenant_id": config.get("tenant_id", _require_env("MS_TENANT_ID")),
                    "client_id": config.get("client_id", _require_env("MS_CLIENT_ID")),
                    "client_secret": config.get("client_secret", _require_env("MS_CLIENT_SECRET")),
                }
        except Exception:
            # Fall through to ENV fallback
            pass

    # Fallback to environment variables
    return {
        "tenant_id": _require_env("MS_TENANT_ID"),
        "client_id": _require_env("MS_CLIENT_ID"),
        "client_secret": _require_env("MS_CLIENT_SECRET"),
    }


async def sharepoint_inventory(
    folder_url: str,
    recursive: bool,
    include_folders: bool,
    page_size: int,
    max_items: Optional[int],
    organization_id: Optional[UUID] = None,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    List SharePoint folder contents with metadata.

    Args:
        folder_url: SharePoint folder URL
        recursive: Whether to recursively traverse subfolders
        include_folders: Whether to include folders in the results
        page_size: Number of items per page
        max_items: Maximum number of items to return
        organization_id: Optional organization ID for database connection lookup
        session: Optional database session for connection lookup

    Returns:
        Dict with folder info and items list

    Connection Priority:
        1. Database connection (if organization_id and session provided)
        2. Environment variables (fallback)
    """
    credentials = await _get_sharepoint_credentials(organization_id, session)
    tenant_id = credentials["tenant_id"]
    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]

    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": _scope(),
    }

    graph_base = _graph_base_url()
    share_id = _encode_share_url(folder_url)

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(_token_url(tenant_id), data=token_payload)
        token_resp.raise_for_status()
        token = token_resp.json().get("access_token")
        if not token:
            raise RuntimeError("No access_token returned from Microsoft identity platform.")

        headers = {"Authorization": f"Bearer {token}"}
        drive_resp = await client.get(f"{graph_base}/shares/{share_id}/driveItem", headers=headers)
        drive_resp.raise_for_status()
        folder = drive_resp.json()

        drive_id, item_id = _extract_drive_info(folder)
        items, _ = await _collect_items(
            client,
            graph_base,
            token,
            drive_id,
            item_id,
            include_folders,
            recursive,
            page_size,
            max_items,
        )

    return {
        "folder": {
            "name": folder.get("name", ""),
            "id": folder.get("id", ""),
            "web_url": folder.get("webUrl", ""),
            "drive_id": drive_id,
        },
        "items": items,
    }


async def sharepoint_inventory_stream(
    folder_url: str,
    recursive: bool,
    include_folders: bool,
    page_size: int,
    max_items: Optional[int],
    organization_id: Optional[UUID] = None,
    session: Optional[AsyncSession] = None,
    on_folder_scanned: Optional[callable] = None,
    on_folder_skipped: Optional[callable] = None,
    folder_exclude_patterns: Optional[List[str]] = None,
    retry_delay_seconds: int = 30,
    max_retries: int = 3,
):
    """
    Stream SharePoint folder contents, yielding items as they are discovered.

    This is a streaming version of sharepoint_inventory that yields items
    immediately as folders are scanned, rather than collecting everything first.

    Features:
    - Automatic token refresh for long-running syncs (refreshes at 50 minutes)
    - Retry logic for transient errors with configurable delay
    - Handles 401 errors by refreshing token and retrying
    - Folder filtering to skip entire folder hierarchies

    Args:
        folder_url: SharePoint folder URL
        recursive: Whether to recursively traverse subfolders
        include_folders: Whether to include folders in the results
        page_size: Number of items per page
        max_items: Maximum number of items to return
        organization_id: Optional organization ID for database connection lookup
        session: Optional database session for connection lookup
        on_folder_scanned: Optional callback(folder_path, files_found, folders_pending)
        on_folder_skipped: Optional callback(folder_name, folder_path) when folder excluded
        folder_exclude_patterns: Optional list of fnmatch patterns to exclude folders
        retry_delay_seconds: Seconds to wait between retries (default: 30)
        max_retries: Maximum retry attempts for transient errors (default: 3)

    Yields:
        Tuple of (folder_info, item) where folder_info is only set on first yield
    """
    credentials = await _get_sharepoint_credentials(organization_id, session)
    tenant_id = credentials["tenant_id"]
    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]

    graph_base = _graph_base_url()
    share_id = _encode_share_url(folder_url)

    # Create token manager for automatic token refresh
    token_manager = TokenManager(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )

    # Use longer timeout for large file operations
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Get initial token
        await token_manager.get_valid_token(client)
        headers = token_manager.get_headers()

        # Get drive info with retry logic
        for attempt in range(max_retries + 1):
            try:
                drive_resp = await client.get(
                    f"{graph_base}/shares/{share_id}/driveItem",
                    headers=headers
                )
                drive_resp.raise_for_status()
                break
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401 and attempt < max_retries:
                    logger.warning("Initial connection got 401 - refreshing token...")
                    await token_manager.refresh_token(client)
                    headers = token_manager.get_headers()
                    continue
                raise
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
                if attempt < max_retries:
                    logger.warning(
                        f"Connection error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                        f"Waiting {retry_delay_seconds}s..."
                    )
                    await asyncio.sleep(retry_delay_seconds)
                    continue
                raise

        folder = drive_resp.json()
        drive_id, item_id = _extract_drive_info(folder)

        folder_info = {
            "name": folder.get("name", ""),
            "id": folder.get("id", ""),
            "web_url": folder.get("webUrl", ""),
            "drive_id": drive_id,
        }

        # Yield folder info first
        yield folder_info, None

        # Stream items as they are discovered
        async for item in _stream_items(
            client,
            graph_base,
            token_manager,
            drive_id,
            item_id,
            include_folders,
            recursive,
            page_size,
            max_items,
            on_folder_scanned,
            on_folder_skipped=on_folder_skipped,
            folder_exclude_patterns=folder_exclude_patterns,
            retry_delay_seconds=retry_delay_seconds,
            max_retries=max_retries,
        ):
            yield None, item


async def sharepoint_download(
    folder_url: str,
    indices: Optional[List[int]],
    download_all: bool,
    recursive: bool,
    page_size: int,
    max_items: Optional[int],
    preserve_folders: bool,
    organization_id: Optional[UUID] = None,
    session: Optional[AsyncSession] = None,
) -> Dict[str, Any]:
    """
    Download files from SharePoint folder to batch directory.

    Args:
        folder_url: SharePoint folder URL
        indices: Optional list of file indices to download
        download_all: Whether to download all files
        recursive: Whether to recursively download from subfolders
        page_size: Number of items per page
        max_items: Maximum number of items to download
        preserve_folders: Whether to preserve folder structure
        organization_id: Optional organization ID for database connection lookup
        session: Optional database session for connection lookup

    Returns:
        Dict with download results (downloaded, skipped, failed)

    Connection Priority:
        1. Database connection (if organization_id and session provided)
        2. Environment variables (fallback)
    """
    credentials = await _get_sharepoint_credentials(organization_id, session)
    tenant_id = credentials["tenant_id"]
    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]

    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": _scope(),
    }

    graph_base = _graph_base_url()
    share_id = _encode_share_url(folder_url)
    batch_root = _default_batch_dir()
    batch_root.mkdir(parents=True, exist_ok=True)

    downloaded: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        token_resp = await client.post(_token_url(tenant_id), data=token_payload)
        token_resp.raise_for_status()
        token = token_resp.json().get("access_token")
        if not token:
            raise RuntimeError("No access_token returned from Microsoft identity platform.")

        headers = {"Authorization": f"Bearer {token}"}
        drive_resp = await client.get(f"{graph_base}/shares/{share_id}/driveItem", headers=headers)
        drive_resp.raise_for_status()
        folder = drive_resp.json()

        drive_id, item_id = _extract_drive_info(folder)
        items, _ = await _collect_items(
            client,
            graph_base,
            token,
            drive_id,
            item_id,
            include_folders=False,
            recursive=recursive,
            page_size=page_size,
            max_items=max_items,
        )
        selected = _select_items(items, indices, download_all)

        for entry in selected:
            dest_path = _resolve_destination(batch_root, entry, preserve_folders)
            expected_size = _parse_size(entry.get("size"))
            if _should_skip(dest_path, expected_size):
                skipped.append(
                    {
                        "index": entry.get("index"),
                        "name": entry.get("name"),
                        "folder": entry.get("folder"),
                        "path": str(dest_path),
                        "size": expected_size,
                    }
                )
                continue

            download_url = f"{graph_base}/drives/{drive_id}/items/{entry.get('id')}/content"
            async with client.stream("GET", download_url, headers=headers) as response:
                response.raise_for_status()
                with dest_path.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
            downloaded.append(
                {
                    "index": entry.get("index"),
                    "name": entry.get("name"),
                    "folder": entry.get("folder"),
                    "path": str(dest_path),
                    "size": expected_size,
                }
            )

    return {
        "downloaded": downloaded,
        "skipped": skipped,
        "batch_dir": str(batch_root),
    }


def _extract_relative_path_from_parent_ref(path: str) -> str:
    """
    Extract relative folder path from Microsoft Graph parentReference.path.

    Microsoft Graph returns paths in the format:
    - /drive/root:/path/to/folder
    - /drives/{drive_id}/root:/path/to/folder

    This function extracts just the relative path after '/root:'.

    Args:
        path: Full parentReference.path from Microsoft Graph

    Returns:
        Relative path (e.g., "Opportunities/GSA/TTS/Project")
    """
    if not path:
        return ""

    # Find /root: and take everything after it
    root_marker = "/root:"
    if root_marker in path:
        # Extract everything after /root:
        relative_path = path.split(root_marker, 1)[1]
        return relative_path.strip("/")

    # Fallback: strip leading/trailing slashes
    return path.strip("/")


async def sharepoint_delta_query(
    drive_id: str,
    item_id: str,
    delta_token: Optional[str] = None,
    organization_id: Optional[UUID] = None,
    session: Optional[AsyncSession] = None,
    on_item_received: Optional[callable] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Query Microsoft Graph Delta API for changed items.

    The Delta API provides incremental sync capability by returning only items
    that have changed since the last query. This is much more efficient than
    full enumeration for large sites with few changes.

    Args:
        drive_id: SharePoint drive ID
        item_id: Root folder item ID to track changes from
        delta_token: Previous delta token (None for initial sync)
                    Format: Full deltaLink URL from previous response
        organization_id: Optional organization ID for credentials lookup
        session: Optional database session for credentials lookup
        on_item_received: Optional async callback called for each item

    Returns:
        Tuple of (changed_items, new_delta_token)

    Delta response items include:
    - New/modified items: Full metadata with file/folder properties
    - Deleted items: Contains {"deleted": {}} property

    Token Notes:
    - Token is an opaque string (full URL) - don't parse it
    - Token may expire after extended inactivity (~30 days)
    - If token invalid, API returns 410 Gone → reset and do full sync

    Reference:
        https://learn.microsoft.com/en-us/graph/delta-query-overview
    """
    credentials = await _get_sharepoint_credentials(organization_id, session)
    tenant_id = credentials["tenant_id"]
    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]

    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": _scope(),
    }

    graph_base = _graph_base_url()

    changed_items: List[Dict[str, Any]] = []
    new_delta_token: str = ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Get access token
        token_resp = await client.post(_token_url(tenant_id), data=token_payload)
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise RuntimeError("No access_token returned from Microsoft identity platform.")

        headers = {"Authorization": f"Bearer {access_token}"}

        # Build delta URL
        if delta_token:
            # Continue from previous delta - token is the full URL
            url = delta_token
        else:
            # Initial delta - get all items with delta tracking
            url = f"{graph_base}/drives/{drive_id}/items/{item_id}/delta"

        # Fetch all pages of delta results
        while url:
            response = await client.get(url, headers=headers)

            # Handle 410 Gone - token expired
            if response.status_code == 410:
                raise DeltaTokenExpiredError(
                    "Delta token has expired. Perform a full sync to obtain a new token."
                )

            response.raise_for_status()
            data = response.json()

            for item in data.get("value", []):
                # Determine change type
                if "deleted" in item:
                    item["_change_type"] = "deleted"
                else:
                    item["_change_type"] = "modified"  # Could be new or updated

                # Build normalized item entry
                is_folder = "folder" in item
                if not is_folder:
                    # Build file entry with metadata
                    file_info = item.get("file", {})
                    parent_ref = item.get("parentReference", {})
                    created_by = item.get("createdBy", {}).get("user", {})
                    modified_by = item.get("lastModifiedBy", {}).get("user", {})

                    normalized_item = {
                        "id": item.get("id"),
                        "name": item.get("name", ""),
                        "type": "file",
                        "folder": _extract_relative_path_from_parent_ref(parent_ref.get("path", "")),
                        "size": item.get("size"),
                        "mime": file_info.get("mimeType"),
                        "file_type": file_info.get("mimeType"),
                        "web_url": item.get("webUrl"),
                        "drive_id": parent_ref.get("driveId") or drive_id,
                        "etag": item.get("eTag"),
                        "created": item.get("createdDateTime"),
                        "modified": item.get("lastModifiedDateTime"),
                        "created_by": created_by.get("displayName"),
                        "created_by_email": created_by.get("email"),
                        "last_modified_by": modified_by.get("displayName"),
                        "last_modified_by_email": modified_by.get("email"),
                        "_change_type": item["_change_type"],
                        "_raw": item,  # Keep raw for advanced processing
                    }
                else:
                    # Folder item (for deletions or if caller wants folders)
                    parent_ref = item.get("parentReference", {})
                    normalized_item = {
                        "id": item.get("id"),
                        "name": item.get("name", ""),
                        "type": "folder",
                        "folder": _extract_relative_path_from_parent_ref(parent_ref.get("path", "")),
                        "web_url": item.get("webUrl"),
                        "drive_id": parent_ref.get("driveId") or drive_id,
                        "_change_type": item["_change_type"],
                        "_raw": item,
                    }

                changed_items.append(normalized_item)

                # Call callback if provided
                if on_item_received:
                    await on_item_received(normalized_item)

            # Handle pagination and delta link
            if "@odata.nextLink" in data:
                # More pages available
                url = data["@odata.nextLink"]
            elif "@odata.deltaLink" in data:
                # Final page - capture new delta token
                new_delta_token = data["@odata.deltaLink"]
                url = None
            else:
                url = None

    return changed_items, new_delta_token


class DeltaTokenExpiredError(Exception):
    """Raised when the Microsoft Graph delta token has expired."""
    pass


async def _get_access_token(
    organization_id: Optional[UUID] = None,
    session: Optional[AsyncSession] = None,
) -> str:
    """
    Get a fresh Microsoft Graph access token.

    Helper function for delta sync to refresh tokens during long operations.
    """
    credentials = await _get_sharepoint_credentials(organization_id, session)
    tenant_id = credentials["tenant_id"]
    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]

    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": _scope(),
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(_token_url(tenant_id), data=token_payload)
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise RuntimeError("No access_token returned from Microsoft identity platform.")
        return access_token
