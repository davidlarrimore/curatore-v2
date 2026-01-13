#!/usr/bin/env python3
"""Process batch files and create SharePoint inventory summaries via LLM."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
import shutil

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import httpx

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


POLL_STATUS_ACTIVE = {"PENDING", "STARTED", "RETRY"}


def _default_dir(env_name: str, fallback: Path) -> Path:
    env_dir = os.getenv(env_name)
    if env_dir:
        candidate = Path(env_dir)
        if str(candidate).startswith("/app") and not os.access(candidate, os.W_OK):
            return fallback
        return candidate
    return fallback


def _prompt_folder_url() -> str:
    try:
        return input("SharePoint folder URL: ").strip()
    except EOFError:
        return ""


def _prompt_selection() -> str:
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
    return sorted({i for i in indices if 1 <= i <= max_index})


def _format_table(items: List[Dict[str, Any]]) -> str:
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


def _api_base() -> str:
    return os.getenv("CURATORE_API_URL") or os.getenv("NEXT_PUBLIC_API_URL") or "http://localhost:8000"


def _openai_config() -> Dict[str, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for summaries.")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return {"api_key": api_key, "base_url": base_url, "model": model}


def _enqueue_batch_process(client: httpx.Client, api_base: str, filename: str) -> Dict[str, str]:
    url = f"{api_base}/api/v1/documents/batch/{filename}/process"
    response = client.post(url)
    response.raise_for_status()
    payload = response.json()
    job_id = payload.get("job_id")
    document_id = payload.get("document_id")
    if not job_id or not document_id:
        raise RuntimeError("Batch process response missing job_id or document_id")
    return {"job_id": job_id, "document_id": document_id}


def _poll_job(client: httpx.Client, api_base: str, job_id: str, poll_interval: float) -> Dict[str, str]:
    url = f"{api_base}/api/v1/jobs/{job_id}"
    while True:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
        status = data.get("status")
        if status not in POLL_STATUS_ACTIVE:
            return data
        time.sleep(poll_interval)


def _fetch_content(client: httpx.Client, api_base: str, document_id: str) -> str:
    url = f"{api_base}/api/v1/documents/{document_id}/content"
    response = client.get(url)
    response.raise_for_status()
    data = response.json()
    content = data.get("content")
    if content is None:
        raise RuntimeError("Content response missing content")
    return content


def _fetch_result_path(client: httpx.Client, api_base: str, document_id: str) -> str | None:
    url = f"{api_base}/api/v1/documents/{document_id}/result"
    response = client.get(url)
    response.raise_for_status()
    data = response.json()
    return data.get("markdown_path")


def _map_backend_path(path_str: str, processed_root: Path) -> Path | None:
    candidate = Path(path_str)
    if candidate.exists():
        return candidate
    app_root = Path("/app/files")
    if str(candidate).startswith(str(app_root)):
        relative = candidate.relative_to(app_root)
        mapped = ROOT_DIR / "files" / relative
        return mapped
    if str(candidate).startswith(str(processed_root)):
        return processed_root / candidate.relative_to(processed_root)
    return None


def _cleanup_backend_output(
    client: httpx.Client,
    api_base: str,
    document_id: str,
    output_path: Path,
    processed_root: Path,
) -> None:
    for candidate in processed_root.glob(f"{document_id}_*.md"):
        if candidate == output_path:
            continue
        try:
            candidate.unlink()
        except OSError:
            pass
    hashed_prefix = f"{document_id}_{document_id}_"
    for candidate in processed_root.glob(f"{hashed_prefix}*.md"):
        if candidate == output_path:
            continue
        try:
            candidate.unlink()
        except OSError:
            pass
    try:
        backend_path = _fetch_result_path(client, api_base, document_id)
    except Exception:
        return
    if not backend_path:
        return
    mapped = _map_backend_path(backend_path, processed_root)
    if not mapped or mapped == output_path:
        return
    try:
        if mapped.exists():
            mapped.unlink()
    except OSError:
        pass


def _resolve_output_path(input_root: Path, output_root: Path, file_path: Path) -> Path:
    relative = file_path.relative_to(input_root)
    out_path = output_root / relative
    return out_path.with_suffix(".md")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _clear_directory(path: Path) -> None:
    if not path.exists():
        return
    for entry in path.iterdir():
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError:
            pass


def _parse_size(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _should_skip(dest_path: Path, expected_size: int | None) -> bool:
    if not dest_path.exists() or expected_size is None:
        return False
    try:
        return dest_path.stat().st_size == expected_size
    except OSError:
        return False


def _resolve_download_path(batch_root: Path, item: Dict[str, Any], preserve_folders: bool) -> Path:
    folder_path = str(item.get("folder", "/"))
    relative_folder = folder_path.strip("/")
    if preserve_folders and relative_folder:
        dest_dir = batch_root / relative_folder
    else:
        dest_dir = batch_root
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / str(item.get("name", ""))


def _log_llm_event(log_path: Path | None, label: str, payload: Dict[str, Any]) -> None:
    if not log_path:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"label": label, **payload}) + "\n")
    except OSError:
        pass


def _llm_chat(
    client: httpx.Client,
    config: Dict[str, str],
    messages: List[Dict[str, str]],
    log_path: Path | None,
    label: str,
) -> str:
    url = f"{config['base_url']}/chat/completions"
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": 0.2,
    }
    _log_llm_event(log_path, f"{label}.request", {"url": url, "model": config["model"]})
    response = client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("LLM response missing choices")
    content = choices[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError("LLM response missing content")
    _log_llm_event(log_path, f"{label}.response", {"chars": len(content)})
    return content.strip()


def _summarize_content(
    client: httpx.Client,
    config: Dict[str, str],
    file_name: str,
    content: str,
    log_path: Path | None,
) -> str:
    clipped = content[:8000]
    system = (
        "You are a precise document summarizer for government contracting materials. "
        "The organization is Amivero, a government contractor. "
        "Documents include RFIs, RFPs, whitepapers, proposals, reviews/ratings, and past performance write-ups."
    )
    user = (
        "Summarize the document below in no more than 1000 characters. "
        "Start with a short phrase stating the document type (e.g., 'RFP response', 'RFI', 'past performance summary', "
        "'whitepaper', 'proposal', 'review/ratings', or 'sales/growth memo'), then continue with the summary. "
        "Return only the summary text, with no labels, no headings, no bullet points, and no field concatenation. "
        "If the summary would exceed 1000 characters, rewrite to fit within the limit. "
        "Focus on key topics, decisions, and audiences.\n\n"
        f"Document: {file_name}\n\n{clipped}"
    )
    summary = _llm_chat(
        client,
        config,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        log_path,
        "summary",
    )
    return summary.strip()


def _format_inventory_markdown(
    client: httpx.Client,
    config: Dict[str, str],
    inventory: Dict[str, Any],
    log_path: Path | None,
) -> str:
    system = "You format knowledge base inventories for RAG retrieval."
    user = (
        "Transform the JSON inventory into a clean markdown document optimized for RAG. "
        "Use headings by folder, include filename, link, summary, and metadata. "
        "Keep it compact and consistent.\n\n"
        f"Inventory JSON:\n{json.dumps(inventory, indent=2)}"
    )
    return _llm_chat(
        client,
        config,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        log_path,
        "inventory_markdown",
    )


def _fallback_inventory_markdown(inventory: Dict[str, Any]) -> str:
    items = inventory.get("items", [])
    by_folder: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        folder = item.get("folder", "/")
        by_folder.setdefault(folder, []).append(item)
    lines = ["# SharePoint Inventory", ""]
    for folder in sorted(by_folder.keys()):
        lines.append(f"## {folder}")
        lines.append("")
        for entry in by_folder[folder]:
            lines.append(f"- {entry.get('name', '')}")
            if entry.get("summary"):
                lines.append(f"  - Summary: {entry.get('summary')}")
            if entry.get("web_url"):
                lines.append(f"  - Link: {entry.get('web_url')}")
            if entry.get("last_updated"):
                lines.append(f"  - Last updated: {entry.get('last_updated')}")
        lines.append("")
    return "\n".join(lines)


def _process_file(
    client: httpx.Client,
    llm_client: httpx.Client,
    llm_config: Dict[str, str],
    api_base: str,
    input_root: Path,
    output_root: Path,
    file_path: Path,
    poll_interval: float,
    overwrite: bool,
    log_path: Path | None,
) -> Tuple[Path, str, str]:
    output_path = _resolve_output_path(input_root, output_root, file_path)
    if output_path.exists() and not overwrite:
        return output_path, "skipped", ""

    batch_response = _enqueue_batch_process(client, api_base, file_path.name)
    job_id = batch_response["job_id"]
    document_id = batch_response["document_id"]
    result = _poll_job(client, api_base, job_id, poll_interval)
    status = result.get("status")
    if status != "SUCCESS":
        return output_path, f"failed ({status})", ""

    content = _fetch_content(client, api_base, document_id)
    _ensure_parent(output_path)
    output_path.write_text(content, encoding="utf-8")
    _cleanup_backend_output(client, api_base, document_id, output_path, output_root)
    summary = _summarize_content(llm_client, llm_config, file_path.name, content, log_path)
    return output_path, "processed", summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventory, download, and process SharePoint files with LLM summaries."
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to write markdown (default: PROCESSED_DIR or ./files/processed_files).",
    )
    parser.add_argument(
        "--api-url",
        help="Base URL for Curatore API (default: CURATORE_API_URL or NEXT_PUBLIC_API_URL).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds between job status polls.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing markdown files.",
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
    parser.add_argument(
        "--preserve-folders",
        action="store_true",
        help="Preserve subfolder structure under the batch directory.",
    )
    args = parser.parse_args()

    load_env()

    input_root = Path(args.download_dir) if args.download_dir else _default_dir(
        "BATCH_DIR", ROOT_DIR / "files" / "batch_files"
    )
    output_root = Path(args.output_dir) if args.output_dir else _default_dir(
        "PROCESSED_DIR", ROOT_DIR / "files" / "processed_files"
    )
    api_base = (args.api_url or _api_base()).rstrip("/")
    llm_config = _openai_config()

    folder_url = args.folder_url or _prompt_folder_url()
    if not folder_url:
        print("Folder URL is required.", file=sys.stderr)
        return 1

    tenant_id = require_env("MS_TENANT_ID")
    client_id = require_env("MS_CLIENT_ID")
    client_secret = require_env("MS_CLIENT_SECRET")
    graph_base = get_graph_base_url()
    token = get_access_token(tenant_id, client_id, client_secret)
    share_id = encode_share_url(folder_url)
    folder = resolve_drive_item(graph_base, token, share_id)
    parent_ref = folder.get("parentReference", {})
    drive_id = parent_ref.get("driveId", "")
    folder_id = folder.get("id", "")
    if not drive_id or not folder_id:
        print("Resolved item is missing driveId or id fields.", file=sys.stderr)
        return 1

    items = collect_items(
        graph_base,
        token,
        drive_id,
        folder_id,
        include_folders=False,
        recursive=args.recursive,
        page_size=args.page_size,
        max_items=args.max_items,
    )
    if not items:
        print("No files found to process.")
        return 0

    print(_format_table(items))
    selection = _prompt_selection()
    if not selection:
        print("No selection provided.", file=sys.stderr)
        return 1
    indices = _parse_selection(selection, len(items))
    if not indices:
        print("Selection did not match any items.", file=sys.stderr)
        return 1

    selected_items = [items[idx - 1] for idx in indices]
    input_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    _clear_directory(input_root)
    _clear_directory(output_root)
    inventory_path = output_root / "sharepoint_inventory.json"
    markdown_path = output_root / "sharepoint_inventory.md"
    llm_log_path = output_root / "sharepoint_inventory_llm.log"

    inventory: Dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "items": [],
    }

    results: List[str] = []
    with httpx.Client(timeout=60.0) as client, httpx.Client(timeout=60.0) as llm_client:
        for item in selected_items:
            try:
                target_path = _resolve_download_path(input_root, item, args.preserve_folders)
                expected_size = _parse_size(item.get("size"))
                if not _should_skip(target_path, expected_size):
                    download_drive_item(
                        graph_base,
                        token,
                        drive_id,
                        str(item.get("id", "")),
                        str(target_path),
                    )
                else:
                    results.append(f"skipped download: {target_path}")

                if not target_path.exists():
                    raise RuntimeError("Downloaded file missing.")

                output_path, status, summary = _process_file(
                    client,
                    llm_client,
                    llm_config,
                    api_base,
                    input_root,
                    output_root,
                    target_path,
                    args.poll_interval,
                    args.overwrite,
                    llm_log_path,
                )
                if status == "processed":
                    inventory["items"].append(
                        {
                            "name": str(item.get("name", "")),
                            "folder": str(item.get("folder", "/")),
                            "path": str(output_path),
                            "link": item.get("web_url"),
                            "size": item.get("size"),
                            "created": item.get("created"),
                            "created_by": item.get("created_by"),
                            "modified": item.get("modified"),
                            "last_updated": item.get("last_updated") or item.get("modified"),
                            "last_modified_by": item.get("last_modified_by"),
                            "web_url": item.get("web_url"),
                            "file_type": item.get("file_type"),
                            "mime": item.get("mime"),
                            "summary": summary,
                        }
                    )
                    inventory_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
                results.append(f"{status}: {target_path}")
                print(f"{status}: {target_path}")
            except Exception as exc:
                results.append(f"failed: {item.get('name', '')} ({exc})")
                print(f"failed: {item.get('name', '')} ({exc})", file=sys.stderr)

        try:
            formatted = _format_inventory_markdown(llm_client, llm_config, inventory, llm_log_path)
            markdown_path.write_text(formatted, encoding="utf-8")
        except Exception as exc:
            print(f"failed to format inventory markdown: {exc}", file=sys.stderr)
            markdown_path.write_text(_fallback_inventory_markdown(inventory), encoding="utf-8")

    print("\n".join(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
