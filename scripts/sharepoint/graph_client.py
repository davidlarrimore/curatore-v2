#!/usr/bin/env python3
"""Microsoft Graph helpers for SharePoint scripts."""
from __future__ import annotations

import base64
import os
from typing import Any, Dict, Iterable, Optional

import httpx

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


def load_env() -> None:
    if load_dotenv:
        load_dotenv()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def encode_share_url(url: str) -> str:
    encoded = base64.b64encode(url.encode("utf-8")).decode("ascii")
    encoded = encoded.rstrip("=").replace("/", "_").replace("+", "-")
    return f"u!{encoded}"


def get_graph_base_url() -> str:
    return os.getenv("MS_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")


def get_access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    token_url = os.getenv(
        "MS_GRAPH_TOKEN_URL",
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    )
    scope = os.getenv("MS_GRAPH_SCOPE", "https://graph.microsoft.com/.default")
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": scope,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(token_url, data=payload)
        response.raise_for_status()
        data = response.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("No access_token returned from Microsoft identity platform.")
    return token


def resolve_drive_item(graph_base: str, token: str, share_id: str) -> Dict[str, Any]:
    url = f"{graph_base}/shares/{share_id}/driveItem"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


def list_children_paged(
    graph_base: str,
    token: str,
    drive_id: str,
    item_id: str,
    page_size: int = 200,
    max_items: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{graph_base}/drives/{drive_id}/items/{item_id}/children"
    params = {"$top": str(page_size)}
    fetched = 0

    with httpx.Client(timeout=30.0) as client:
        while url:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            items = data.get("value", [])
            for item in items:
                yield item
                fetched += 1
                if max_items is not None and fetched >= max_items:
                    return
            url = data.get("@odata.nextLink")
            params = None


def download_drive_item(
    graph_base: str,
    token: str,
    drive_id: str,
    item_id: str,
    dest_path: str,
) -> None:
    url = f"{graph_base}/drives/{drive_id}/items/{item_id}/content"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            with open(dest_path, "wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
