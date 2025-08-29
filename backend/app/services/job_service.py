"""
Redis-backed job tracking utilities for Celery tasks.

Responsibilities:
- Enqueue metadata, set and clear per-document active job locks
- Persist job status payloads for API consumption
- Index job by document id
"""
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

import redis


def get_redis_client() -> redis.Redis:
    url = os.getenv("JOB_REDIS_URL") or os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    return redis.Redis.from_url(url)


JOB_KEY = "job:{job_id}"
DOC_ACTIVE_KEY = "doc:{doc_id}:active_job"
DOC_LAST_KEY = "doc:{doc_id}:last_job"


def _now_ts() -> float:
    return time.time()


def set_active_job(document_id: str, job_id: str, ttl: Optional[int] = None) -> bool:
    r = get_redis_client()
    key = DOC_ACTIVE_KEY.format(doc_id=document_id)
    # NX = only set if not exists
    ok = r.set(key, job_id, nx=True, ex=ttl)
    if ok:
        r.set(DOC_LAST_KEY.format(doc_id=document_id), job_id, ex=max(ttl or 0, int(os.getenv("JOB_STATUS_TTL_SECONDS", "259200"))))
        return True
    return False


def clear_active_job(document_id: str, job_id: Optional[str] = None):
    r = get_redis_client()
    key = DOC_ACTIVE_KEY.format(doc_id=document_id)
    if job_id:
        try:
            current = r.get(key)
            if current and current.decode() != job_id:
                return
        except Exception:
            pass
    r.delete(key)


def record_job_status(job_id: str, payload: Dict[str, Any], ttl: Optional[int] = None):
    """Merge status payload into existing job record while preserving logs."""
    r = get_redis_client()
    key = JOB_KEY.format(job_id=job_id)
    if ttl is None:
        ttl = int(os.getenv("JOB_STATUS_TTL_SECONDS", "259200"))
    try:
        existing_raw = r.get(key)
        data: Dict[str, Any] = json.loads(existing_raw) if existing_raw else {}
    except Exception:
        data = {}
    # Preserve and merge logs
    existing_logs = data.get("logs", []) if isinstance(data.get("logs"), list) else []
    incoming_logs = payload.get("logs", []) if isinstance(payload.get("logs"), list) else []
    # Shallow merge other fields
    for k, v in payload.items():
        if k == "logs":
            continue
        data[k] = v
    if incoming_logs:
        existing_logs.extend(incoming_logs)
    if existing_logs:
        data["logs"] = existing_logs
    # Always ensure job_id set
    data.setdefault("job_id", job_id)
    r.set(key, json.dumps(data, default=str), ex=ttl)


def append_job_log(job_id: str, level: str, message: str, ts: Optional[str] = None):
    """Append a log entry to the job's log list."""
    r = get_redis_client()
    key = JOB_KEY.format(job_id=job_id)
    try:
        existing_raw = r.get(key)
        data: Dict[str, Any] = json.loads(existing_raw) if existing_raw else {"job_id": job_id}
    except Exception:
        data = {"job_id": job_id}
    logs = data.get("logs") if isinstance(data.get("logs"), list) else []
    entry = {"ts": ts or datetime.utcnow().isoformat(), "level": level, "message": message}
    logs.append(entry)
    data["logs"] = logs
    r.set(key, json.dumps(data, default=str), ex=int(os.getenv("JOB_STATUS_TTL_SECONDS", "259200")))


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    r = get_redis_client()
    raw = r.get(JOB_KEY.format(job_id=job_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def get_active_job_for_document(document_id: str) -> Optional[str]:
    r = get_redis_client()
    val = r.get(DOC_ACTIVE_KEY.format(doc_id=document_id))
    return val.decode() if val else None


def get_last_job_for_document(document_id: str) -> Optional[str]:
    r = get_redis_client()
    val = r.get(DOC_LAST_KEY.format(doc_id=document_id))
    return val.decode() if val else None


def _scan_and_delete(pattern: str) -> int:
    r = get_redis_client()
    total = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor=cursor, match=pattern, count=500)
        if keys:
            total += r.delete(*keys)
        if cursor == 0:
            break
    return total


def clear_all_jobs_and_locks() -> Dict[str, int]:
    """Delete all job status keys and per-document lock/index keys from Redis."""
    deleted_jobs = _scan_and_delete("job:*")
    deleted_active = _scan_and_delete("doc:*:active_job")
    deleted_last = _scan_and_delete("doc:*:last_job")
    return {
        "jobs": deleted_jobs,
        "active_locks": deleted_active,
        "last_job_keys": deleted_last,
    }
