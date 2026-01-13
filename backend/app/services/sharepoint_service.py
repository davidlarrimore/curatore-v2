"""SharePoint integration helpers for inventory and downloads via Microsoft Graph."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings


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
    candidate = settings.batch_path
    if str(candidate).startswith("/app") and not os.access(candidate, os.W_OK):
        return Path.cwd() / "files" / "batch_files"
    return candidate


def _normalize_folder_path(folder_path: str) -> str:
    if not folder_path:
        return "/"
    return "/" + folder_path.strip("/")


def _build_item(
    item: Dict[str, Any],
    include_folders: bool,
    folder_path: str,
    index: int,
) -> Optional[Dict[str, Any]]:
    is_folder = "folder" in item
    if is_folder and not include_folders:
        return None
    name = str(item.get("name", ""))
    ext = ""
    if not is_folder:
        ext = Path(name).suffix.lstrip(".")
    return {
        "index": index,
        "name": name,
        "type": "folder" if is_folder else "file",
        "folder": _normalize_folder_path(folder_path),
        "extension": ext,
        "size": item.get("size"),
        "created": item.get("createdDateTime"),
        "modified": item.get("lastModifiedDateTime"),
        "created_by": item.get("createdBy", {}).get("user", {}).get("displayName"),
        "last_modified_by": item.get("lastModifiedBy", {}).get("user", {}).get("displayName"),
        "mime": item.get("file", {}).get("mimeType"),
        "file_type": item.get("file", {}).get("mimeType"),
        "id": item.get("id", ""),
        "web_url": item.get("webUrl"),
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
