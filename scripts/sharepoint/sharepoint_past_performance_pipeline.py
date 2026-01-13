#!/usr/bin/env python3
"""SharePoint document processing with summaries and past performance synthesis."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, Future
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
SUMMARY_MAX_CHARS = 1500
MIN_SUMMARY_CHARS = 300
CHUNK_SIZE_CHARS = 12000
CHUNK_OVERLAP_CHARS = 500
LLM_MODEL = "claude-4-5-haiku"
LLM_TEMPERATURE = 0.1
DOC_TYPE_MAX_TOKENS = 120
SUMMARY_MAX_TOKENS = 900
SUMMARY_TEMPLATE_MAX_TOKENS = 400


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


def _graph_access_token() -> str:
    tenant_id = require_env("MS_TENANT_ID")
    client_id = require_env("MS_CLIENT_ID")
    client_secret = require_env("MS_CLIENT_SECRET")
    return get_access_token(tenant_id, client_id, client_secret)


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
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            _log_llm_event(log_path, f"{label}.error", {"attempt": attempt, "status": status, "error": str(exc)})
            if attempt == attempts:
                raise
            if status == 429:
                delay = min(60.0, 5.0 * attempt)
            else:
                delay = 1.5 * attempt
            time.sleep(delay)
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
    extra_instruction: str = "",
) -> str:
    clipped = content[:8000]
    _log_llm_event(
        log_path,
        "summary.prompt_meta",
        {
            "file": file_name,
            "content_chars": len(content),
            "clipped_chars": len(clipped),
            "max_tokens": SUMMARY_MAX_TOKENS,
        },
    )
    system = (
        "You are a data engineer summarizing government contracting documents for classification and tagging. "
        "The organization is Amivero, a government contractor. "
        "Documents include RFIs, RFPs, whitepapers, proposals, reviews/ratings, and past performance write-ups."
    )
    user = (
        f"Summarize the document below in no more than {SUMMARY_MAX_CHARS} characters. "
        "Start with the document type and purpose (e.g., "
        "'RFP response for [contract] to [agency]', 'RFI response for [program]', "
        "'whitepaper on [topic]' or 'past performance write-up for [customer]'). "
        "Then add technical details needed for tagging: year created (or most likely year), "
        "customer/agency/office names, contract/RFI/RFP numbers, key requirements, "
        "customer requirements outlined in the document, "
        "and technologies/capabilities (e.g., DevSecOps, AI/ML, RPA, cloud, data analytics). "       
        "If the summary would exceed the limit, rewrite to fit. "
        f"{extra_instruction}"
        "Be concise but information-dense and end with a full sentence.\n\n"
        f"Document: {file_name}\n\n{clipped}"
    )
    return _llm_chat_with_retries(
        client,
        config,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=SUMMARY_MAX_TOKENS,
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
        _log_llm_event(
            log_path,
            "summary_template.prompt_meta",
            {
                "file": file_name,
                "content_chars": len(content),
                "clipped_chars": len(clipped),
                "max_tokens": SUMMARY_TEMPLATE_MAX_TOKENS,
            },
        )
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
            max_tokens=SUMMARY_TEMPLATE_MAX_TOKENS,
            log_path=log_path,
            label="summary_template",
        )
    summary = _summarize_content(client, config, file_name, content, log_path)
    _log_llm_event(
        log_path,
        "summary.length",
        {"file": file_name, "chars": len(summary), "preview": summary[:200]},
    )
    _log_llm_event(
        log_path,
        "summary.full",
        {"file": file_name, "text": summary},
    )
    needs_retry = len(summary) < MIN_SUMMARY_CHARS or not summary.rstrip().endswith((".", "!", "?"))
    if needs_retry:
        summary = _summarize_content(
            client,
            config,
            file_name,
            content,
            log_path,
            extra_instruction=(
                f"Ensure at least {MIN_SUMMARY_CHARS} characters and 3-5 sentences unless the source text is very short. "
                "Do not end mid-sentence or mid-word; end with a complete sentence. "
            ),
        )
        _log_llm_event(
            log_path,
            "summary.length.retry",
            {"file": file_name, "chars": len(summary), "preview": summary[:200]},
        )
        _log_llm_event(
            log_path,
            "summary.full.retry",
            {"file": file_name, "text": summary},
        )
        if len(summary) < MIN_SUMMARY_CHARS or not summary.rstrip().endswith((".", "!", "?")):
            _log_llm_event(
                log_path,
                "summary.short.final",
                {"file": file_name, "chars": len(summary), "preview": summary[:200]},
            )
    return summary


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
            entry.setdefault("source_file_name", metadata.get("name"))
            entry.setdefault("source_last_updated", metadata.get("last_updated") or metadata.get("modified"))
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


def _resolve_temp_path(output_root: Path, file_path: Path) -> Path:
    temp_root = output_root / "temp_files"
    temp_root.mkdir(parents=True, exist_ok=True)
    return temp_root / f"tmp_{file_path.stem}.md"


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


def _get_job_status(client: httpx.Client, api_base: str, job_id: str) -> Dict[str, Any]:
    url = f"{api_base}/api/v1/jobs/{job_id}"
    response = client.get(url)
    response.raise_for_status()
    return response.json()


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


def _cleanup_base_processed(processed_base: Path, document_id: str) -> None:
    for candidate in processed_base.glob(f"{document_id}_*.md"):
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


def _write_consolidated_markdown(
    path: Path,
    synthesized: List[Dict[str, Any]],
    extracted_entries: List[Dict[str, Any]],
) -> None:
    sources_map: Dict[str, List[Dict[str, Any]]] = {}
    for entry in extracted_entries:
        perf_id = str(entry.get("performance_id", "")).strip()
        if not perf_id:
            continue
        sources_map.setdefault(perf_id, []).append(
            {
                "name": entry.get("source_file_name"),
                "last_updated": entry.get("source_last_updated"),
                "link": entry.get("source_link"),
            }
        )
    lines = ["# Past Performance Consolidated", ""]
    for entry in synthesized:
        identifier = entry.get("performance_id", "Unknown")
        lines.append(f"## {identifier}")
        lines.append("")
        narrative = entry.get("narrative", "")
        lines.append(narrative)
        lines.append("")
        sources = sources_map.get(identifier, [])
        if sources:
            lines.append("Sources:")
            for source in sources:
                name = source.get("name") or "Unknown"
                updated = source.get("last_updated") or ""
                link = source.get("link") or ""
                suffix = f" (last_updated: {updated})" if updated else ""
                lines.append(f"- {name}{suffix} | {link}")
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


def _download_item(
    item: Dict[str, Any],
    input_root: Path,
    graph_base: str,
    drive_id: str,
    token_holder: Dict[str, str],
    token_lock: threading.Lock,
    registry: Dict[str, Any],
    registry_lock: threading.Lock,
) -> Dict[str, Any]:
    target_path = _resolve_download_path(input_root, item, preserve_folders=False)
    expected_size = _parse_size(item.get("size"))
    needs_download = _should_download(item, registry)
    if not target_path.exists():
        needs_download = True
    if needs_download or not _should_skip(target_path, expected_size):
        try:
            download_drive_item(
                graph_base,
                token_holder["token"],
                drive_id,
                str(item.get("id", "")),
                str(target_path),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                with token_lock:
                    token_holder["token"] = _graph_access_token()
                download_drive_item(
                    graph_base,
                    token_holder["token"],
                    drive_id,
                    str(item.get("id", "")),
                    str(target_path),
                )
            else:
                raise
        key = _registry_key(item)
        if key:
            with registry_lock:
                registry.setdefault("files", {})[key] = {
                    "name": item.get("name"),
                    "web_url": item.get("web_url"),
                    "last_modified": item.get("modified"),
                    "size": item.get("size"),
                    "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "path": str(target_path),
                }
                registry["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not target_path.exists():
        raise RuntimeError("Downloaded file missing.")
    return {"item": item, "target_path": target_path}


def _summarize_only(
    api_base: str,
    llm_config: LLMCallConfig,
    input_root: Path,
    output_root: Path,
    target_path: Path,
    document_id: str,
    item: Dict[str, Any],
    llm_log_path: Path,
) -> Dict[str, Any]:
    step_times: Dict[str, float] = {}
    with httpx.Client(timeout=60.0) as client, httpx.Client(timeout=60.0) as llm_client:
        start = time.perf_counter()
        content = _fetch_content(client, api_base, document_id)
        step_times["fetch_content_s"] = time.perf_counter() - start

        start = time.perf_counter()
        temp_path = _resolve_temp_path(output_root, target_path)
        temp_path.write_text(content, encoding="utf-8")
        output_path = _resolve_output_path(input_root, output_root, target_path)
        step_times["write_temp_s"] = time.perf_counter() - start

        start = time.perf_counter()
        document_type = _detect_document_type(
            llm_client,
            llm_config,
            target_path.name,
            content,
            llm_log_path,
        )
        step_times["detect_type_s"] = time.perf_counter() - start

        start = time.perf_counter()
        summary = _summarize_for_type(
            llm_client,
            llm_config,
            target_path.name,
            content,
            document_type,
            llm_log_path,
        )
        step_times["summarize_s"] = time.perf_counter() - start
        metadata = {**item, "document_type": document_type}
        header = _write_front_matter(metadata, summary, content)
        start = time.perf_counter()
        _ensure_parent(output_path)
        output_path.write_text(header, encoding="utf-8")
        _cleanup_backend_output(output_root, document_id, output_path)
        step_times["write_final_s"] = time.perf_counter() - start

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
            "summary_chars": len(summary),
            "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "past_performance_refs": [],
            "timings": step_times,
        }

        start = time.perf_counter()
        _log_llm_event(
            llm_log_path,
            "timings",
            {"file": target_path.name, "timings": step_times},
        )
        return {
            "item_record": item_record,
            "content": content,
            "target_path": target_path,
            "document_id": document_id,
            "item": item,
        }


def _extract_past_performance_task(
    llm_config: LLMCallConfig,
    content: str,
    item_record: Dict[str, Any],
    llm_log_path: Path,
) -> List[Dict[str, Any]]:
    with httpx.Client(timeout=60.0) as llm_client:
        start = time.perf_counter()
        entries = _extract_past_performance(llm_client, llm_config, content, item_record, llm_log_path)
        _log_llm_event(
            llm_log_path,
            "timings",
            {
                "file": item_record.get("name", ""),
                "extract_past_performance_s": time.perf_counter() - start,
            },
        )
        return entries


def _print_status_table(
    pending: List[Dict[str, Any]],
    completed: int,
    total: int,
    queue_stats: Dict[str, int] | None = None,
) -> None:
    status_counts: Dict[str, int] = {}
    stage_counts: Dict[str, int] = {}
    lines = ["Status update:"]
    for entry in pending:
        status = entry.get("status", "UNKNOWN")
        stage = entry.get("stage", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    status_summary = " | ".join(f"{key}: {value}" for key, value in sorted(status_counts.items()))
    stage_summary = " | ".join(f"{key}: {value}" for key, value in sorted(stage_counts.items()))
    lines.append(f"Progress: {completed}/{total} | {status_summary}")
    lines.append(f"Stages: {stage_summary}")
    if queue_stats:
        queue_summary = " | ".join(f"{key}: {value}" for key, value in sorted(queue_stats.items()))
        lines.append(f"Queues: {queue_summary}")
    for entry in pending:
        name = entry.get("item", {}).get("name", "")
        status = entry.get("status", "UNKNOWN")
        stage = entry.get("stage", "UNKNOWN")
        lines.append(f"- {name}: {stage} ({status})")
    print("\n".join(lines))


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
    parser.add_argument(
        "--max-downloads",
        type=int,
        default=5,
        help="Maximum number of simultaneous downloads.",
    )
    parser.add_argument(
        "--max-extracting",
        type=int,
        default=5,
        help="Maximum number of simultaneous extraction jobs.",
    )
    parser.add_argument(
        "--max-summarizing",
        type=int,
        default=2,
        help="Maximum number of simultaneous summarization tasks.",
    )
    parser.add_argument(
        "--max-past-performance",
        type=int,
        default=2,
        help="Maximum number of simultaneous past performance extraction tasks.",
    )
    parser.add_argument(
        "--disable-past-performance",
        action="store_true",
        help="Skip past performance extraction and synthesis.",
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
    enable_past_performance = not args.disable_past_performance
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
    total_items = len(selected_items)
    completed = 0
    download_queue = list(selected_items)
    download_futures: Dict[Future, Dict[str, Any]] = {}
    downloaded_ready: List[Dict[str, Any]] = []
    extracting: List[Dict[str, Any]] = []
    summarize_futures: Dict[Future, Dict[str, Any]] = {}
    summarize_ready: List[Dict[str, Any]] = []
    extract_futures: Dict[Future, Dict[str, Any]] = {}
    extract_ready: List[Dict[str, Any]] = []

    token_holder = {"token": token}
    token_lock = threading.Lock()
    registry_lock = threading.Lock()
    inventory_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.max_downloads) as download_executor, ThreadPoolExecutor(
        max_workers=args.max_summarizing
    ) as summarize_executor, ThreadPoolExecutor(max_workers=args.max_past_performance) as extract_executor, httpx.Client(
        timeout=60.0
    ) as client:
        while (
            download_queue
            or download_futures
            or downloaded_ready
            or extracting
            or summarize_ready
            or summarize_futures
            or extract_ready
            or extract_futures
        ):
            while download_queue and len(download_futures) < args.max_downloads:
                item = download_queue.pop(0)
                future = download_executor.submit(
                    _download_item,
                    item,
                    input_root,
                    graph_base,
                    drive_id,
                    token_holder,
                    token_lock,
                    registry,
                    registry_lock,
                )
                download_futures[future] = item
                _print_status_table(
                    [{"item": item, "status": "PENDING", "stage": "DOWNLOADING"}],
                    completed,
                    total_items,
                )

            for future in list(download_futures):
                if not future.done():
                    continue
                item = download_futures.pop(future)
                try:
                    downloaded_ready.append(future.result())
                except Exception as exc:
                    completed += 1
                    results.append(f"[{completed}/{total_items}] failed: {item.get('name', '')} ({exc})")
                    print(f"[{completed}/{total_items}] failed: {item.get('name', '')} ({exc})", file=sys.stderr)

            while downloaded_ready and len(extracting) < args.max_extracting:
                entry = downloaded_ready.pop(0)
                batch_response = _enqueue_batch_process(client, api_base, entry["target_path"].name)
                extracting.append(
                    {
                        "item": entry["item"],
                        "target_path": entry["target_path"],
                        "job_id": batch_response["job_id"],
                        "document_id": batch_response["document_id"],
                        "status": "PENDING",
                        "stage": "EXTRACTING",
                    }
                )

            for entry in list(extracting):
                job_id = entry["job_id"]
                try:
                    status_payload = _get_job_status(client, api_base, job_id)
                except Exception as exc:
                    _log_llm_event(llm_log_path, "job_status.error", {"job_id": job_id, "error": str(exc)})
                    continue
                status = status_payload.get("status")
                entry["status"] = status
                if status in POLL_STATUS_ACTIVE:
                    continue
                extracting.remove(entry)
                if status != "SUCCESS":
                    completed += 1
                    results.append(f"[{completed}/{total_items}] failed ({status}): {entry['target_path']}")
                    print(f"[{completed}/{total_items}] failed ({status}): {entry['target_path']}", file=sys.stderr)
                    continue
                entry["stage"] = "SUMMARIZING"
                summarize_ready.append(entry)

            while summarize_ready and len(summarize_futures) < args.max_summarizing:
                entry = summarize_ready.pop(0)
                future = summarize_executor.submit(
                    _summarize_only,
                    api_base,
                    llm_config,
                    input_root,
                    output_root,
                    entry["target_path"],
                    entry["document_id"],
                    entry["item"],
                    llm_log_path,
                )
                summarize_futures[future] = entry

            for future in list(summarize_futures):
                if not future.done():
                    continue
                entry = summarize_futures.pop(future)
                try:
                    result = future.result()
                except Exception as exc:
                    completed += 1
                    results.append(f"[{completed}/{total_items}] failed: {entry['target_path']} ({exc})")
                    print(f"[{completed}/{total_items}] failed: {entry['target_path']} ({exc})", file=sys.stderr)
                    continue

                if enable_past_performance:
                    extract_ready.append(
                        {
                            "item_record": result["item_record"],
                            "content": result["content"],
                            "target_path": result["target_path"],
                            "item": result["item"],
                        }
                    )
                else:
                    with inventory_lock:
                        run_record["items"].append(result["item_record"])
                        inventory["generated_at"] = run_record["generated_at"]
                        _write_inventory(inventory_path, inventory)
                    completed += 1
                    output_path = result["item_record"].get("path", str(result["target_path"]))
                    results.append(f"[{completed}/{total_items}] processed: {output_path}")
                    print(f"[{completed}/{total_items}] processed: {output_path}")

            if enable_past_performance:
                while extract_ready and len(extract_futures) < args.max_past_performance:
                    entry = extract_ready.pop(0)
                    future = extract_executor.submit(
                        _extract_past_performance_task,
                        llm_config,
                        entry["content"],
                        entry["item_record"],
                        llm_log_path,
                    )
                    extract_futures[future] = entry

            if enable_past_performance:
                for future in list(extract_futures):
                    if not future.done():
                        continue
                    entry = extract_futures.pop(future)
                    try:
                        past_entries = future.result()
                    except Exception as exc:
                        completed += 1
                        results.append(f"[{completed}/{total_items}] failed: {entry['target_path']} ({exc})")
                        print(f"[{completed}/{total_items}] failed: {entry['target_path']} ({exc})", file=sys.stderr)
                        continue

                    item_record = entry["item_record"]
                    for pp_entry in past_entries:
                        entry_id = f"pp_{uuid.uuid4().hex}"
                        pp_entry["entry_id"] = entry_id
                        extracted_entries.append(pp_entry)
                        item_record["past_performance_refs"].append(entry_id)

                    with inventory_lock:
                        run_record["items"].append(item_record)
                        inventory["generated_at"] = run_record["generated_at"]
                        run_record["past_performance"]["extracted"] = extracted_entries
                        _write_inventory(inventory_path, inventory)

                    completed += 1
                    output_path = item_record.get("path", str(entry["target_path"]))
                    results.append(f"[{completed}/{total_items}] processed: {output_path}")
                    print(f"[{completed}/{total_items}] processed: {output_path}")

            pending_entries: List[Dict[str, Any]] = []
            pending_entries.extend(
                [{"item": item, "status": "QUEUED", "stage": "DOWNLOADING"} for item in download_queue]
            )
            pending_entries.extend(
                [{"item": item, "status": "RUNNING", "stage": "DOWNLOADING"} for item in download_futures.values()]
            )
            pending_entries.extend(extracting)
            pending_entries.extend(
                [{**entry, "status": "QUEUED", "stage": "SUMMARIZING"} for entry in summarize_ready]
            )
            pending_entries.extend(
                [{**entry, "status": "RUNNING", "stage": "SUMMARIZING"} for entry in summarize_futures.values()]
            )
            if enable_past_performance:
                pending_entries.extend(
                    [
                        {
                            "item": entry.get("item"),
                            "status": "QUEUED",
                            "stage": "PAST_PERFORMANCE",
                        }
                        for entry in extract_ready
                    ]
                )
                pending_entries.extend(
                    [
                        {
                            "item": entry.get("item"),
                            "status": "RUNNING",
                            "stage": "PAST_PERFORMANCE",
                        }
                        for entry in extract_futures.values()
                    ]
                )
            if pending_entries:
                queue_stats = {
                    "download_queue": len(download_queue),
                    "downloaded_ready": len(downloaded_ready),
                    "summarize_queue": len(summarize_ready),
                }
                if enable_past_performance:
                    queue_stats["past_performance_queue"] = len(extract_ready)
                _print_status_table(pending_entries, completed, total_items, queue_stats)
                time.sleep(args.poll_interval)

    if enable_past_performance:
        with httpx.Client(timeout=60.0) as llm_client:
            synthesized = _synthesize_past_performance(llm_client, llm_config, extracted_entries, llm_log_path)
        run_record["past_performance"]["synthesized"] = synthesized
        _write_inventory(inventory_path, inventory)
        _write_consolidated_markdown(consolidated_path, synthesized, extracted_entries)
    else:
        if consolidated_path.exists():
            try:
                consolidated_path.unlink()
            except OSError:
                pass
        _write_inventory(inventory_path, inventory)

    temp_root = output_root / "temp_files"
    if temp_root.exists():
        shutil.rmtree(temp_root)
    for candidate in processed_base.glob("batch_*.md"):
        try:
            candidate.unlink()
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
