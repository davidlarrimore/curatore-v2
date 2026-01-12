#!/usr/bin/env python3
"""Basic SharePoint connectivity via Microsoft Graph.

This is a standalone script for sprint 1. It authenticates with app-only
credentials and resolves a SharePoint folder URL to a drive item.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from typing import Any, Dict

import httpx

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


def _load_env() -> None:
    if load_dotenv:
        load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _encode_share_url(url: str) -> str:
    encoded = base64.b64encode(url.encode("utf-8")).decode("ascii")
    encoded = encoded.rstrip("=").replace("/", "_").replace("+", "-")
    return f"u!{encoded}"


def _get_access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
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


def _resolve_drive_item(graph_base: str, token: str, share_id: str) -> Dict[str, Any]:
    url = f"{graph_base}/shares/{share_id}/driveItem"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


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
        tenant_id = _require_env("MS_TENANT_ID")
        client_id = _require_env("MS_CLIENT_ID")
        client_secret = _require_env("MS_CLIENT_SECRET")
        graph_base = os.getenv("MS_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")

        folder_url = args.folder_url or _prompt_folder_url()
        if not folder_url:
            raise RuntimeError("Folder URL is required.")

        token = _get_access_token(tenant_id, client_id, client_secret)
        share_id = _encode_share_url(folder_url)
        item = _resolve_drive_item(graph_base, token, share_id)

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
