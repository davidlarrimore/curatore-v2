#!/usr/bin/env python3
"""Process batch files via Curatore backend and write markdown outputs."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import httpx

from scripts.sharepoint.graph_client import load_env  # noqa: E402


POLL_STATUS_ACTIVE = {"PENDING", "STARTED", "RETRY"}


def _default_dir(env_name: str, fallback: Path) -> Path:
    env_dir = os.getenv(env_name)
    if env_dir:
        candidate = Path(env_dir)
        if str(candidate).startswith("/app") and not os.access(candidate, os.W_OK):
            return fallback
        return candidate
    return fallback


def _iter_files(root: Path) -> Iterable[Path]:
    for base, _, files in os.walk(root):
        for name in files:
            if name == ".gitkeep" or name.startswith("."):
                continue
            yield Path(base) / name


def _api_base() -> str:
    return os.getenv("CURATORE_API_URL") or os.getenv("NEXT_PUBLIC_API_URL") or "http://localhost:8000"


def _upload_file(client: httpx.Client, api_base: str, file_path: Path) -> str:
    url = f"{api_base}/api/v1/documents/upload"
    with file_path.open("rb") as handle:
        files = {"file": (file_path.name, handle)}
        response = client.post(url, files=files)
    response.raise_for_status()
    data = response.json()
    document_id = data.get("document_id")
    if not document_id:
        raise RuntimeError("Upload response missing document_id")
    return document_id


def _enqueue_process(client: httpx.Client, api_base: str, document_id: str) -> str:
    url = f"{api_base}/api/v1/documents/{document_id}/process"
    response = client.post(url)
    response.raise_for_status()
    data = response.json()
    job_id = data.get("job_id")
    if not job_id:
        raise RuntimeError("Process response missing job_id")
    return job_id


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


def _process_file(
    client: httpx.Client,
    api_base: str,
    input_root: Path,
    output_root: Path,
    file_path: Path,
    poll_interval: float,
    overwrite: bool,
) -> Tuple[Path, str]:
    output_path = _resolve_output_path(input_root, output_root, file_path)
    if output_path.exists() and not overwrite:
        return output_path, "skipped"

    document_id = _upload_file(client, api_base, file_path)
    job_id = _enqueue_process(client, api_base, document_id)
    result = _poll_job(client, api_base, job_id, poll_interval)
    status = result.get("status")
    if status != "SUCCESS":
        return output_path, f"failed ({status})"

    content = _fetch_content(client, api_base, document_id)
    _ensure_parent(output_path)
    output_path.write_text(content, encoding="utf-8")
    _cleanup_backend_output(client, api_base, document_id, output_path, output_root)
    return output_path, "processed"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process batch files via Curatore backend and write markdown outputs."
    )
    parser.add_argument(
        "--input-dir",
        help="Directory of files to process (default: BATCH_DIR or ./files/batch_files).",
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
        "--max-files",
        type=int,
        default=None,
        help="Maximum number of files to process.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing markdown files.",
    )
    args = parser.parse_args()

    load_env()

    input_root = Path(args.input_dir) if args.input_dir else _default_dir(
        "BATCH_DIR", ROOT_DIR / "files" / "batch_files"
    )
    output_root = Path(args.output_dir) if args.output_dir else _default_dir(
        "PROCESSED_DIR", ROOT_DIR / "files" / "processed_files"
    )
    api_base = (args.api_url or _api_base()).rstrip("/")

    if not input_root.exists():
        print(f"Input directory not found: {input_root}", file=sys.stderr)
        return 1

    files = [path for path in _iter_files(input_root) if path.is_file()]
    if args.max_files is not None:
        files = files[: args.max_files]

    if not files:
        print("No files found to process.")
        return 0

    results: List[str] = []
    with httpx.Client(timeout=60.0) as client:
        for file_path in files:
            try:
                output_path, status = _process_file(
                    client,
                    api_base,
                    input_root,
                    output_root,
                    file_path,
                    args.poll_interval,
                    args.overwrite,
                )
                results.append(f"{status}: {output_path}")
                print(f"{status}: {file_path}")
            except Exception as exc:
                results.append(f"failed: {file_path} ({exc})")
                print(f"failed: {file_path} ({exc})", file=sys.stderr)

    print("\n".join(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
