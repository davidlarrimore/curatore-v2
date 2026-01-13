#!/usr/bin/env python3
"""Download SharePoint files into the Curatore batch folder."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.sharepoint.graph_client import (  # noqa: E402
    download_drive_item,
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


def _prompt_selection(max_index: int) -> str:
    prompt = "Select files by index (e.g., 1,3-5) or 'all': "
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _parse_selection(selection: str, max_index: int) -> List[int]:
    if selection.lower() == "all":
        return list(range(1, max_index + 1))
    indices: List[int] = []
    parts = [p.strip() for p in selection.split(",") if p.strip()]
    try:
        for part in parts:
            if "-" in part:
                start_str, end_str = part.split("-", 1)
                start = int(start_str)
                end = int(end_str)
                if start > end:
                    start, end = end, start
                indices.extend(range(start, end + 1))
            else:
                indices.append(int(part))
    except ValueError as exc:
        raise RuntimeError("Selection format is invalid.") from exc
    filtered = sorted({i for i in indices if 1 <= i <= max_index})
    return filtered


def _default_batch_dir() -> Path:
    env_dir = os.getenv("BATCH_DIR")
    if env_dir:
        candidate = Path(env_dir)
        if str(candidate).startswith("/app") and not os.access(candidate, os.W_OK):
            return ROOT_DIR / "files" / "batch_files"
        return candidate
    return ROOT_DIR / "files" / "batch_files"


def _format_table(items: List[Dict[str, str]]) -> str:
    headers = ["Index", "Name", "Folder", "Size"]
    rows = [
        [
            str(item.get("index", "")),
            str(item.get("name", "")),
            str(item.get("folder", "")),
            str(item.get("size", "")),
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


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _should_skip(path: Path, expected_size: int | None) -> bool:
    if not path.exists():
        return False
    if expected_size is None:
        return False
    try:
        return path.stat().st_size == expected_size
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download SharePoint files into the Curatore batch folder."
    )
    parser.add_argument(
        "--folder-url",
        help="SharePoint folder URL to resolve (e.g., a shared folder link).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Traverse subfolders and include their contents in the inventory.",
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
        "--download-dir",
        help="Override download directory (default: BATCH_DIR or ./files/batch_files).",
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
            include_folders=False,
            recursive=args.recursive,
            page_size=args.page_size,
            max_items=args.max_items,
        )
        if not items:
            print("No files found.")
            return 0

        print(_format_table(items))
        selection = _prompt_selection(len(items))
        if not selection:
            raise RuntimeError("No selection provided.")
        indices = _parse_selection(selection, len(items))
        if not indices:
            raise RuntimeError("Selection did not match any items.")

        download_dir = Path(args.download_dir) if args.download_dir else _default_batch_dir()
        _safe_mkdir(download_dir)

        for idx in indices:
            item = items[idx - 1]
            folder_path = item.get("folder", "/")
            relative_folder = folder_path.strip("/")
            target_dir = download_dir / relative_folder if relative_folder else download_dir
            _safe_mkdir(target_dir)
            target_path = target_dir / item["name"]

            expected_size = item.get("size")
            if isinstance(expected_size, str) and expected_size.isdigit():
                expected_size = int(expected_size)
            elif not isinstance(expected_size, int):
                expected_size = None
            if _should_skip(target_path, expected_size):
                print(f"Skip existing: {target_path}")
                continue

            download_drive_item(
                graph_base,
                token,
                drive_id,
                item["id"],
                str(target_path),
            )
            print(f"Downloaded: {target_path}")

        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
