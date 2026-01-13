#!/usr/bin/env python3
"""List SharePoint folder contents with metadata via Microsoft Graph."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

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
from scripts.sharepoint.inventory_utils import collect_items  # noqa: E402


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


def _format_table(items: List[Dict[str, Any]]) -> str:
    headers = ["Index", "Name", "Type", "Folder", "Ext", "Size", "Created", "Modified", "Mime"]
    rows = [
        [
            str(item.get("index", "")),
            str(item.get("name", "")),
            str(item.get("type", "")),
            str(item.get("folder", "")),
            str(item.get("extension", "")),
            str(item.get("size", "")),
            str(item.get("created", "")),
            str(item.get("modified", "")),
            str(item.get("mime", "")),
        ]
        for item in items
    ]
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    line_sep = " | "
    header_line = line_sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))
    divider_line = "-+-".join("-" * widths[i] for i in range(len(headers)))
    table_lines = [header_line, divider_line]
    if not rows:
        table_lines.append("(no items)")
    for row in rows:
        table_lines.append(line_sep.join(row[i].ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(table_lines)




def main() -> int:
    parser = argparse.ArgumentParser(
        description="List SharePoint folder contents with metadata via Microsoft Graph."
    )
    parser.add_argument(
        "--folder-url",
        help="SharePoint folder URL to resolve (e.g., a shared folder link).",
    )
    parser.add_argument(
        "--output",
        choices=["table", "json"],
        default="table",
        help="Output format for the inventory.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=200,
        help="Page size for Graph list calls.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Maximum number of items to return (defaults to all).",
    )
    parser.add_argument(
        "--include-folders",
        action="store_true",
        help="Include folder entries in the output.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Traverse subfolders and include their contents in the inventory.",
    )
    args = parser.parse_args()

    load_env()

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
        folder = resolve_drive_item(graph_base, token, share_id)

        parent_ref = folder.get("parentReference", {})
        drive_id = parent_ref.get("driveId", "")
        if not drive_id or not folder.get("id"):
            raise RuntimeError("Resolved item is missing driveId or id fields.")

        items = collect_items(
            graph_base,
            token,
            drive_id,
            folder["id"],
            include_folders=args.include_folders,
            recursive=args.recursive,
            page_size=args.page_size,
            max_items=args.max_items,
        )

        if args.output == "json":
            payload = {
                "folder": {
                    "name": folder.get("name", ""),
                    "id": folder.get("id", ""),
                    "web_url": folder.get("webUrl", ""),
                    "drive_id": drive_id,
                },
                "items": items,
            }
            print(json.dumps(payload, indent=2))
            return 0

        summary = {
            "Name": folder.get("name", ""),
            "ID": folder.get("id", ""),
            "Web URL": folder.get("webUrl", ""),
            "Drive ID": drive_id,
            "Items": len(items),
        }
        output = [_format_kv_table("Folder Inventory", summary), "", _format_table(items)]
        print("\n".join(output))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
