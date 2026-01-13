#!/usr/bin/env python3
"""Helpers for SharePoint inventory and downloads."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from scripts.sharepoint.graph_client import list_children_paged


def build_item(
    item: Dict[str, Any],
    include_folders: bool,
    folder_path: str,
    index: int,
) -> Dict[str, Any] | None:
    is_folder = "folder" in item
    if is_folder and not include_folders:
        return None
    name = str(item.get("name", ""))
    ext = ""
    if not is_folder:
        _, ext = os.path.splitext(name)
        ext = ext.lstrip(".")
    return {
        "index": index,
        "name": name,
        "type": "folder" if is_folder else "file",
        "folder": folder_path or "/",
        "extension": ext,
        "size": item.get("size", ""),
        "created": item.get("createdDateTime", ""),
        "modified": item.get("lastModifiedDateTime", ""),
        "mime": item.get("file", {}).get("mimeType", ""),
        "id": item.get("id", ""),
        "web_url": item.get("webUrl", ""),
    }


def collect_items(
    graph_base: str,
    token: str,
    drive_id: str,
    root_id: str,
    include_folders: bool,
    recursive: bool,
    page_size: int,
    max_items: int | None,
) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    pending = [(root_id, "")]
    while pending:
        item_id, folder_path = pending.pop(0)
        raw_items = list(
            list_children_paged(
                graph_base,
                token,
                drive_id,
                item_id,
                page_size=page_size,
                max_items=None,
            )
        )
        for raw in raw_items:
            is_folder = "folder" in raw
            if is_folder and recursive:
                next_path = f"{folder_path}/{raw.get('name', '')}".strip("/")
                pending.append((raw.get("id", ""), next_path))
            entry = build_item(raw, include_folders, folder_path, len(collected) + 1)
            if entry:
                collected.append(entry)
                if max_items is not None and len(collected) >= max_items:
                    return collected
    return collected
