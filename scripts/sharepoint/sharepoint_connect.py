#!/usr/bin/env python3
"""Basic SharePoint connectivity via Microsoft Graph.

This is a standalone script for sprint 1. It authenticates with app-only
credentials and resolves a SharePoint folder URL to a drive item.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

import httpx

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.sharepoint.graph_client import (  # noqa: E402
    encode_share_url,
    get_access_token,
    get_graph_base_url,
    load_env,
    resolve_drive_item,
    require_env,
)


def _load_env() -> None:
    load_env()


def _list_children(
    graph_base: str, token: str, drive_id: str, item_id: str, max_items: int
) -> Dict[str, Any]:
    url = f"{graph_base}/drives/{drive_id}/items/{item_id}/children"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"$top": str(max_items)}
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()


def _prompt_folder_url() -> str:
    try:
        return input("SharePoint folder URL: ").strip()
    except EOFError:
        return ""


def _format_kv_table(title: str, rows: Dict[str, Any]) -> str:
    key_width = max(len(str(k)) for k in rows.keys())
    val_width = max(len(str(v)) for v in rows.values())
    width = max(key_width + val_width + 3, len(title))
    lines = [
        title,
        "-" * width,
    ]
    for key, value in rows.items():
        lines.append(f"{key:<{key_width}} : {value}")
    return "\n".join(lines)


def _format_children_table(children: Dict[str, Any]) -> str:
    items = children.get("value", [])
    headers = ["Name", "Type", "Size", "Modified", "ID"]
    rows = []
    for item in items:
        is_folder = "folder" in item
        rows.append(
            [
                str(item.get("name", "")),
                "folder" if is_folder else "file",
                str(item.get("size", "")),
                str(item.get("lastModifiedDateTime", "")),
                str(item.get("id", "")),
            ]
        )
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    line_sep = " | "
    header_line = line_sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))
    divider_line = "-+-".join("-" * widths[i] for i in range(len(headers)))
    table_lines = [header_line, divider_line]
    for row in rows:
        table_lines.append(line_sep.join(row[i].ljust(widths[i]) for i in range(len(headers))))
    if not rows:
        table_lines.append("(no items)")
    return "\n".join(table_lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Connect to SharePoint and resolve a folder URL via Microsoft Graph."
    )
    parser.add_argument(
        "--folder-url",
        help="SharePoint folder URL to resolve (e.g., a shared folder link).",
    )
    parser.add_argument(
        "--list-children",
        action="store_true",
        help="List child items for the resolved folder (up to --max-items).",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=50,
        help="Maximum number of child items to list when --list-children is set.",
    )
    args = parser.parse_args()

    _load_env()

    try:
        tenant_id = require_env("MS_TENANT_ID")
        client_id = require_env("MS_CLIENT_ID")
        client_secret = require_env("MS_CLIENT_SECRET")
        graph_base = get_graph_base_url()

        folder_url = args.folder_url or _prompt_folder_url()
        if not folder_url:
            raise RuntimeError("Folder URL is required.")

        token = get_access_token(tenant_id, client_id, client_secret)
        share_id = encode_share_url(folder_url)
        item = resolve_drive_item(graph_base, token, share_id)

        parent_ref = item.get("parentReference", {})
        drive_id = parent_ref.get("driveId", "")
        drive_name = parent_ref.get("driveName", "")
        drive_type = parent_ref.get("driveType", "")

        summary = {
            "Name": item.get("name", ""),
            "ID": item.get("id", ""),
            "Type": "folder" if "folder" in item else "file",
            "Web URL": item.get("webUrl", ""),
            "Drive ID": drive_id,
            "Drive Name": drive_name,
            "Drive Type": drive_type,
        }

        output = [_format_kv_table("Resolved Folder", summary)]

        if args.list_children:
            item_id = item.get("id")
            if not drive_id or not item_id:
                raise RuntimeError("Resolved item is missing driveId or id fields.")
            children = _list_children(graph_base, token, drive_id, item_id, args.max_items)
            output.append("")
            output.append(_format_children_table(children))

        print("\n".join(output))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
