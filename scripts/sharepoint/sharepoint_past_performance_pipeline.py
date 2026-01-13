#!/usr/bin/env python3
"""SharePoint document processing with summaries and past performance synthesis."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

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
SUMMARY_MAX_CHARS = 1000
CHUNK_SIZE_CHARS = 12000
CHUNK_OVERLAP_CHARS = 500
LLM_MODEL = "gpt-4o"
LLM_TEMPERATURE = 0.1
DOC_TYPE_MAX_TOKENS = 120


@dataclass
class LLMCallConfig:
    api_key: str
    base_url: str
    model: str


def _default_dir(env_name: str, fallback: Path) -> Path:
    env_dir = os.getenv(env_name)
    if env_dir:
        candidate = Path(env_dir)
        if str(candidate).startswith("/app") and not os.access(candidate, os.W_OK):
            return fallback
        return candidate
    return fallback


def _sanitize_folder_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "_" for ch in name).strip()
    return cleaned.replace(" ", "_") or "sharepoint_folder"


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
    headers = ["Index", "Name", "Folder", "Size", "Modified"]
    rows = [
        [
            str(item.get("index", "")),
            str(item.get("name", "")),
            str(item.get("folder", "")),
            str(item.get("size", "")),
            str(item.get("modified", "")),
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


def _openai_config() -> LLMCallConfig:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for LLM calls.")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    return LLMCallConfig(api_key=api_key, base_url=base_url, model=LLM_MODEL)


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
    config: LLMCallConfig,
    messages: List[Dict[str, str]],
    max_tokens: int,
    log_path: Path | None,
    label: str,
) -> str:
    url = f"{config.base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}"}
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "max_tokens": max_tokens,
    }
    _log_llm_event(log_path, f"{label}.request", {"url": url, "model": config.model, "max_tokens": max_tokens})
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


def _llm_chat_with_retries(
    client: httpx.Client,
    config: LLMCallConfig,
    messages: List[Dict[str, str]],
    max_tokens: int,
    log_path: Path | None,
    label: str,
    attempts: int = 3,
) -> str:
    for attempt in range(1, attempts + 1):
        try:
            return _llm_chat(client, config, messages, max_tokens, log_path, label)
        except Exception as exc:
            _log_llm_event(log_path, f"{label}.error", {"attempt": attempt, "error": str(exc)})
            if attempt == attempts:
                raise
            time.sleep(1.5 * attempt)
    raise RuntimeError("LLM call failed")


def _extract_json_payload(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
            try:
                return json.loads(text[obj_start : obj_end + 1])
            except json.JSONDecodeError:
                pass
        arr_start = text.find("[")
        arr_end = text.rfind("]")
        if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
            return json.loads(text[arr_start : arr_end + 1])
        raise


def _chunk_text(text: str) -> List[str]:
    if len(text) <= CHUNK_SIZE_CHARS:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE_CHARS)
        chunk = text[start:end]
        if end < len(text):
            last_break = chunk.rfind("\n")
            if last_break > 2000:
                end = start + last_break
                chunk = text[start:end]
        chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - CHUNK_OVERLAP_CHARS)
    return chunks


def _summarize_content(
    client: httpx.Client,
    config: LLMCallConfig,
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
        f"Summarize the document below in no more than {SUMMARY_MAX_CHARS} characters. "
        "Start with a short phrase stating the document type (e.g., 'RFP response', 'RFI', "
        "'past performance summary', 'whitepaper', 'proposal', 'review/ratings', or 'sales/growth memo'), "
        "then continue with the summary. Return only the summary text with no labels, headings, bullet points, "
        "or field concatenation. If the summary would exceed the limit, rewrite to fit. "
        "Focus on key topics, decisions, and audiences.\n\n"
        f"Document: {file_name}\n\n{clipped}"
    )
    return _llm_chat_with_retries(
        client,
        config,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=450,
        log_path=log_path,
        label="summary",
    )


def _detect_document_type(
    client: httpx.Client,
    config: LLMCallConfig,
    file_name: str,
    content: str,
    log_path: Path | None,
) -> str:
    clipped = content[:6000]
    system = (
        "You classify document types for government contracting materials. "
        "Return ONLY a short type label from this list: "
        "template, reference_list, RFI, RFP, whitepaper, proposal, review_ratings, "
        "past_performance, sales_growth_memo, other."
    )
    user = (
        "Identify the document type from the content and file name. "
        "Return only the label.\n\n"
        f"File name: {file_name}\n\nContent:\n{clipped}"
    )
    response = _llm_chat_with_retries(
        client,
        config,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=DOC_TYPE_MAX_TOKENS,
        log_path=log_path,
        label="document_type",
    )
    return response.strip().split()[0].lower()


def _summarize_for_type(
    client: httpx.Client,
    config: LLMCallConfig,
    file_name: str,
    content: str,
    doc_type: str,
    log_path: Path | None,
) -> str:
    if doc_type in {"template", "reference_list"}:
        clipped = content[:6000]
        system = (
            "You summarize government contracting templates and reference lists. "
            "Be concise and descriptive; do not summarize detailed contents."
        )
        user = (
            f"Summarize the document below in no more than {SUMMARY_MAX_CHARS} characters. "
            "Return only the summary text with no labels, headings, bullet points, or field concatenation. "
            "Describe what the document is used for and what it contains at a high level. "
            "If the summary would exceed the limit, rewrite to fit.\n\n"
            f"Document: {file_name}\n\n{clipped}"
        )
        return _llm_chat_with_retries(
            client,
            config,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=300,
            log_path=log_path,
            label="summary_template",
        )
    return _summarize_content(client, config, file_name, content, log_path)


def _extract_past_performance(
    client: httpx.Client,
    config: LLMCallConfig,
    content: str,
    metadata: Dict[str, Any],
    log_path: Path | None,
) -> List[Dict[str, Any]]:
    chunks = _chunk_text(content)
    extracted: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        system = (
            "You extract past performance narratives for U.S. Federal proposal use. "
            "Return ONLY valid JSON with a top-level 'entries' array."
        )
        user = (
            "Extract past performance narratives from the document content below. "
            "Return ONLY JSON (no markdown). Each entry must include: "
            "performance_id (normalized customer/project/contract identifier), "
            "narrative (concise factual write-up), "
            "source_link (SharePoint link), "
            "source_file (processed file path). "
            "If no past performance is present, return {\"entries\": []}. "
            "Use only information in the content; do not infer.\n\n"
            f"Chunk {idx} of {len(chunks)}\n"
            f"Source link: {metadata.get('web_url', '')}\n"
            f"Source file: {metadata.get('path', '')}\n\n"
            f"Content:\n{chunk}"
        )
        response = _llm_chat_with_retries(
            client,
            config,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=2000,
            log_path=log_path,
            label=f"past_performance_chunk_{idx}",
        )
        try:
            parsed = _extract_json_payload(response)
            if isinstance(parsed, dict):
                entries = parsed.get("entries", [])
            elif isinstance(parsed, list):
                entries = parsed
            else:
                entries = []
        except Exception:
            entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry.setdefault("source_link", metadata.get("web_url"))
            entry.setdefault("source_file", metadata.get("path"))
            if not entry.get("performance_id") or not entry.get("narrative"):
                continue
            extracted.append(entry)
    return extracted


def _fallback_synthesis(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        perf_id = str(entry.get("performance_id", "")).strip()
        if not perf_id:
            continue
        group = grouped.setdefault(
            perf_id,
            {"performance_id": perf_id, "narrative": entry.get("narrative", ""), "source_links": []},
        )
        link = entry.get("source_link")
        if link and link not in group["source_links"]:
            group["source_links"].append(link)
    return list(grouped.values())


def _synthesize_past_performance(
    client: httpx.Client,
    config: LLMCallConfig,
    entries: List[Dict[str, Any]],
    log_path: Path | None,
) -> List[Dict[str, Any]]:
    if not entries:
        return []
    parsed_entries: List[Dict[str, Any]] = []
    system = (
        "You synthesize proposal-ready past performance write-ups. "
        "Return ONLY valid JSON with a top-level 'entries' array."
    )
    user = (
        "Group entries by performance_id and synthesize a single best-of narrative per group. "
        "Do not introduce new facts. Each synthesized entry must include: "
        "performance_id, narrative, source_links (list of SharePoint links). "
        "Return ONLY JSON.\n\n"
        f"Extracted entries:\n{json.dumps(entries, indent=2)}"
    )
    response = _llm_chat_with_retries(
        client,
        config,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=2000,
        log_path=log_path,
        label="past_performance_synthesis",
    )
    try:
        parsed = _extract_json_payload(response)
        if isinstance(parsed, dict):
            parsed_entries = parsed.get("entries", [])
        elif isinstance(parsed, list):
            parsed_entries = parsed
        else:
            parsed_entries = []
        if not parsed_entries:
            raise ValueError("Empty synthesis entries")
        return parsed_entries
    except Exception:
        _log_llm_event(log_path, "past_performance_synthesis.parse_error", {"preview": response[:2000]})
        return _fallback_synthesis(entries)


def _write_front_matter(metadata: Dict[str, Any], summary: str, content: str) -> str:
    lines = [
        "---",
        f"file_name: {metadata.get('name', '')}",
        f"sharepoint_link: {metadata.get('web_url', '')}",
        f"created_date: {metadata.get('created', '')}",
        f"last_modified_date: {metadata.get('modified', '')}",
        f"created_by: {metadata.get('created_by', '')}",
        f"last_modified_by: {metadata.get('last_modified_by', '')}",
        f"file_type: {metadata.get('file_type', '')}",
        f"document_type: {metadata.get('document_type', '')}",
        "summary: |",
    ]
    for line in summary.splitlines():
        lines.append(f"  {line}")
    lines.append("---")
    lines.append("")
    lines.append(content)
    return "\n".join(lines)


def _resolve_output_path(input_root: Path, output_root: Path, file_path: Path) -> Path:
    relative = file_path.relative_to(input_root)
    out_path = output_root / relative
    return out_path.with_suffix(".md")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


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


def _cleanup_backend_output(processed_root: Path, document_id: str, output_path: Path) -> None:
    for candidate in processed_root.glob(f"{document_id}_*.md"):
        if candidate == output_path:
            continue
        try:
            candidate.unlink()
        except OSError:
            pass


def _load_inventory(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"schema_version": "1.0", "generated_at": None, "runs": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": "1.0", "generated_at": None, "runs": []}


def _write_inventory(path: Path, inventory: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _write_consolidated_markdown(path: Path, synthesized: List[Dict[str, Any]]) -> None:
    lines = ["# Past Performance Consolidated", ""]
    for entry in synthesized:
        identifier = entry.get("performance_id", "Unknown")
        lines.append(f"## {identifier}")
        lines.append("")
        narrative = entry.get("narrative", "")
        lines.append(narrative)
        lines.append("")
        links = entry.get("source_links", [])
        if links:
            lines.append("Sources:")
            for link in links:
                lines.append(f"- {link}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _load_download_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": "1.0", "generated_at": None, "files": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "1.0", "generated_at": None, "files": {}}


def _write_download_registry(path: Path, registry: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _registry_key(item: Dict[str, Any]) -> str:
    return str(item.get("web_url") or item.get("id") or item.get("name") or "").strip()


def _should_download(item: Dict[str, Any], registry: Dict[str, Any]) -> bool:
    key = _registry_key(item)
    if not key:
        return True
    record = registry.get("files", {}).get(key)
    if not record:
        return True
    if record.get("last_modified") != item.get("modified"):
        return True
    if record.get("size") != item.get("size"):
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SharePoint processing with summaries and past performance synthesis."
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
        help="Preserve subfolder structure under the batch directory (ignored; downloads are flattened).",
    )
    parser.add_argument(
        "--clear-dirs",
        action="store_true",
        help="Clear batch and processed directories before running.",
    )
    args = parser.parse_args()

    load_env()

    batch_base = Path(args.download_dir) if args.download_dir else _default_dir(
        "BATCH_DIR", ROOT_DIR / "files" / "batch_files"
    )
    processed_base = Path(args.output_dir) if args.output_dir else _default_dir(
        "PROCESSED_DIR", ROOT_DIR / "files" / "processed_files"
    )
    api_base = (args.api_url or os.getenv("CURATORE_API_URL") or os.getenv("NEXT_PUBLIC_API_URL") or "http://localhost:8000").rstrip("/")
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

    folder_name = _sanitize_folder_name(str(folder.get("name", "")))
    input_root = batch_base / folder_name
    output_root = processed_base / folder_name

    if args.clear_dirs:
        if input_root.exists():
            shutil.rmtree(input_root)
    if output_root.exists():
        shutil.rmtree(output_root)
    input_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

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

    inventory_path = output_root / f"sharepoint_inventory_{folder_name}.json"
    llm_log_path = output_root / f"sharepoint_inventory_{folder_name}_llm.log"
    consolidated_path = output_root / f"past_performance_consolidated_{folder_name}.md"
    deprecated_inventory_md = output_root / f"sharepoint_inventory_{folder_name}.md"
    registry_path = input_root / "sharepoint_download_registry.json"

    if deprecated_inventory_md.exists():
        try:
            deprecated_inventory_md.unlink()
        except OSError:
            pass

    inventory = _load_inventory(inventory_path)
    registry = _load_download_registry(registry_path)
    run_id = uuid.uuid4().hex
    run_record: Dict[str, Any] = {
        "run_id": run_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_folder_url": folder_url,
        "items": [],
        "past_performance": {"extracted": [], "synthesized": []},
    }
    inventory.setdefault("runs", []).append(run_record)

    results: List[str] = []
    extracted_entries: List[Dict[str, Any]] = []
    with httpx.Client(timeout=60.0) as client, httpx.Client(timeout=60.0) as llm_client:
        for item in selected_items:
            try:
                target_path = _resolve_download_path(input_root, item, preserve_folders=False)
                expected_size = _parse_size(item.get("size"))
                needs_download = _should_download(item, registry)
                if needs_download:
                    download_drive_item(
                        graph_base,
                        token,
                        drive_id,
                        str(item.get("id", "")),
                        str(target_path),
                    )
                    key = _registry_key(item)
                    registry.setdefault("files", {})[key] = {
                        "name": item.get("name"),
                        "web_url": item.get("web_url"),
                        "last_modified": item.get("modified"),
                        "size": item.get("size"),
                        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "path": str(target_path),
                    }
                    registry["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    _write_download_registry(registry_path, registry)
                elif not _should_skip(target_path, expected_size):
                    download_drive_item(
                        graph_base,
                        token,
                        drive_id,
                        str(item.get("id", "")),
                        str(target_path),
                    )
                    key = _registry_key(item)
                    registry.setdefault("files", {})[key] = {
                        "name": item.get("name"),
                        "web_url": item.get("web_url"),
                        "last_modified": item.get("modified"),
                        "size": item.get("size"),
                        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "path": str(target_path),
                    }
                    registry["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    _write_download_registry(registry_path, registry)

                if not target_path.exists():
                    raise RuntimeError("Downloaded file missing.")

                batch_response = _enqueue_batch_process(client, api_base, target_path.name)
                job_id = batch_response["job_id"]
                document_id = batch_response["document_id"]
                result = _poll_job(client, api_base, job_id, args.poll_interval)
                status = result.get("status")
                if status != "SUCCESS":
                    results.append(f"failed ({status}): {target_path}")
                    continue

                content = _fetch_content(client, api_base, document_id)
                output_path = _resolve_output_path(input_root, output_root, target_path)
                document_type = _detect_document_type(
                    llm_client,
                    llm_config,
                    target_path.name,
                    content,
                    llm_log_path,
                )
                summary = _summarize_for_type(
                    llm_client,
                    llm_config,
                    target_path.name,
                    content,
                    document_type,
                    llm_log_path,
                )
                metadata = {**item, "document_type": document_type}
                header = _write_front_matter(metadata, summary, content)
                _ensure_parent(output_path)
                output_path.write_text(header, encoding="utf-8")
                _cleanup_backend_output(output_root, document_id, output_path)

                item_record = {
                    "name": item.get("name"),
                    "folder": item.get("folder"),
                    "path": str(output_path),
                    "web_url": item.get("web_url"),
                    "created": item.get("created"),
                    "modified": item.get("modified"),
                    "last_updated": item.get("last_updated") or item.get("modified"),
                    "created_by": item.get("created_by"),
                    "last_modified_by": item.get("last_modified_by"),
                    "file_type": item.get("file_type"),
                    "mime": item.get("mime"),
                    "document_type": document_type,
                    "summary": summary,
                    "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "past_performance_refs": [],
                }

                past_entries = _extract_past_performance(llm_client, llm_config, content, item_record, llm_log_path)
                for entry in past_entries:
                    entry_id = f"pp_{uuid.uuid4().hex}"
                    entry["entry_id"] = entry_id
                    extracted_entries.append(entry)
                    item_record["past_performance_refs"].append(entry_id)

                run_record["items"].append(item_record)
                inventory["generated_at"] = run_record["generated_at"]
                run_record["past_performance"]["extracted"] = extracted_entries
                _write_inventory(inventory_path, inventory)

                results.append(f"processed: {target_path}")
                print(f"processed: {target_path}")
            except Exception as exc:
                results.append(f"failed: {item.get('name', '')} ({exc})")
                print(f"failed: {item.get('name', '')} ({exc})", file=sys.stderr)

        synthesized = _synthesize_past_performance(llm_client, llm_config, extracted_entries, llm_log_path)
        run_record["past_performance"]["synthesized"] = synthesized
        _write_inventory(inventory_path, inventory)
        _write_consolidated_markdown(consolidated_path, synthesized)

    print("\n".join(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
