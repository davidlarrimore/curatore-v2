"""
WebSocket Router for Real-Time Job Updates.

Provides WebSocket endpoint for clients to receive real-time job status
updates, progress notifications, and queue statistics.

Usage:
    Connect to: /api/v1/ws/jobs?token=<JWT_TOKEN>

Messages (Server -> Client):
    - run_status: Job status changes (started, completed, failed, cancelled)
    - run_progress: Progress updates (processed items, current phase)
    - queue_stats: Queue statistics (every 10s)
    - initial_state: Sent on connection with active runs and queue stats

Authentication:
    JWT token is passed via query parameter for WebSocket connections.
    The token is validated using the same auth_service as REST endpoints.
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from uuid import UUID

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.auth_service import auth_service
from app.core.ops.websocket_manager import websocket_manager
from app.core.shared.database_service import database_service
from app.core.shared.pubsub_service import pubsub_service
from app.core.shared.run_service import run_service

logger = logging.getLogger("curatore.websocket")

router = APIRouter(prefix="/ws", tags=["websocket"])


async def verify_websocket_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify JWT token for WebSocket connections.

    Args:
        token: JWT token string

    Returns:
        Token payload if valid, None if invalid
    """
    try:
        payload = auth_service.decode_token(token)
        # Verify it's an access token
        if payload.get("type") != "access":
            logger.warning("WebSocket auth: not an access token")
            return None
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("WebSocket auth: token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"WebSocket auth: invalid token - {e}")
        return None


def get_display_name_for_run(run) -> str:
    """
    Get a human-readable display name for a run.

    Extracts display name from run config based on run_type.
    """
    config = run.config or {}

    if run.run_type == "extraction":
        return config.get("filename", "Document extraction")

    elif run.run_type == "sam_pull":
        return config.get("search_name", "SAM.gov Pull")

    elif run.run_type == "scrape":
        return config.get("collection_name", "Web Scrape")

    elif run.run_type in ("sharepoint_sync", "sharepoint_import", "sharepoint_delete"):
        return (
            config.get("sync_config_name")
            or config.get("config_name")
            or config.get("sync_name")
            or config.get("folder_path")
            or "SharePoint Job"
        )

    elif run.run_type == "system_maintenance":
        # Use scheduled task display name from config, or format task_name
        task_name = config.get("scheduled_task_name", "Maintenance Task")
        # Common task name mappings
        task_labels = {
            "search_reindex": "Search Index Rebuild",
            "queue_pending_assets": "Queue Pending Assets",
            "stale_run_cleanup": "Stale Run Cleanup",
            "system_health_report": "System Health Report",
            "sharepoint_sync_hourly": "SharePoint Sync",
            "sam_pull_hourly": "SAM Pull (Hourly)",
            "sam_pull_daily": "SAM Pull (Daily)",
        }
        return task_labels.get(task_name, task_name.replace("_", " ").title())

    elif run.run_type in ("procedure", "procedure_run"):
        return (
            config.get("procedure_name")
            or config.get("procedure_slug", "Procedure").replace("_", " ").replace("-", " ").title()
        )

    elif run.run_type in ("pipeline", "pipeline_run"):
        return config.get("pipeline_slug", "Pipeline").replace("_", " ").replace("-", " ").title()

    elif run.run_type == "salesforce_import":
        return config.get("connection_name", "Salesforce Import")

    elif run.run_type == "forecast_sync":
        return config.get("sync_name", "Forecast Sync")

    else:
        return run.run_type.replace("_", " ").title()


async def get_initial_state(
    session: AsyncSession,
    organization_id: Optional[UUID],
) -> Dict[str, Any]:
    """
    Get initial state to send on WebSocket connection.

    Includes active runs and current queue stats for the organization.
    When organization_id is None (system admin), returns active runs across all orgs.

    Args:
        session: Database session
        organization_id: Organization UUID, or None for system admins

    Returns:
        Initial state dictionary with active_runs and queue_stats
    """
    from sqlalchemy import select
    from app.core.database.models import Run

    active_statuses = ["pending", "submitted", "running"]
    active_runs = []

    for run_status in active_statuses:
        if organization_id:
            runs = await run_service.get_runs_by_organization(
                session=session,
                organization_id=organization_id,
                status=run_status,
                limit=100,
            )
        else:
            # System admin: get all active runs across all orgs
            query = (
                select(Run)
                .where(Run.status == run_status)
                .order_by(Run.created_at.desc())
                .limit(100)
            )
            result = await session.execute(query)
            runs = list(result.scalars().all())

        for run in runs:
            active_runs.append({
                "run_id": str(run.id),
                "run_type": run.run_type,
                "status": run.status,
                "progress": run.progress,
                "results_summary": run.results_summary,
                "error_message": run.error_message,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "display_name": get_display_name_for_run(run),
            })

    return {
        "active_runs": active_runs,
        "queue_stats": None,  # Will be populated by first queue_stats message
    }


@router.websocket("/jobs")
async def websocket_jobs(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    """
    WebSocket endpoint for real-time job updates.

    Connect to this endpoint with a valid JWT token to receive push notifications
    for job status changes, progress updates, and queue statistics.

    Query Parameters:
        token: JWT access token (required)

    Messages Received (Server -> Client):
        - run_status: Job status changes
            {
                "type": "run_status",
                "timestamp": "2024-01-15T12:00:00Z",
                "data": {
                    "run_id": "uuid",
                    "run_type": "sam_pull",
                    "status": "completed",
                    "progress": {...},
                    "results_summary": {...},
                    "error_message": null
                }
            }

        - run_progress: Progress updates
            {
                "type": "run_progress",
                "timestamp": "2024-01-15T12:00:00Z",
                "data": {
                    "run_id": "uuid",
                    "progress": {
                        "phase": "downloading",
                        "current": 5,
                        "total": 10,
                        "percent": 50
                    }
                }
            }

        - queue_stats: Queue statistics (every 10s)
            {
                "type": "queue_stats",
                "timestamp": "2024-01-15T12:00:00Z",
                "data": {
                    "extraction_queue": {...},
                    "celery_queues": {...}
                }
            }

        - initial_state: Sent on connection
            {
                "type": "initial_state",
                "timestamp": "2024-01-15T12:00:00Z",
                "data": {
                    "active_runs": [...],
                    "queue_stats": {...}
                }
            }

    Messages Sent (Client -> Server):
        - ping: Heartbeat (server responds with pong)
            {"type": "ping"}
    """
    # Verify token before accepting connection
    payload = await verify_websocket_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # Extract user and org info from token
    user_id = UUID(payload["sub"])
    org_id_raw = payload.get("org_id")
    organization_id = UUID(org_id_raw) if org_id_raw else None

    # Accept the WebSocket connection
    await websocket.accept()

    # Register the connection (pass None org for system admins)
    await websocket_manager.connect(websocket, organization_id, user_id)

    # Create tasks for receiving messages and listening to pubsub
    receive_task = None
    pubsub_task = None

    try:
        # Send initial state
        async with database_service.get_session() as session:
            initial_state = await get_initial_state(session, organization_id)

        from datetime import datetime
        await websocket_manager.send_to_connection(websocket, {
            "type": "initial_state",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": initial_state,
        })

        logger.info(f"WebSocket connected: user={user_id}, org={organization_id}")

        # Start receiving messages from client (for ping/pong)
        async def receive_messages():
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.warning(f"WebSocket receive error: {e}")

        # Start listening to Redis pubsub for this org (or all orgs for system admins)
        async def listen_pubsub():
            try:
                if organization_id:
                    channel = pubsub_service.subscribe_org_channel(organization_id)
                else:
                    # System admin: subscribe to all org channels
                    channel = pubsub_service.subscribe_all_org_channels()
                async for message in channel:
                    await websocket_manager.send_to_connection(websocket, message)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"WebSocket pubsub error: {e}")

        # Run both tasks concurrently
        receive_task = asyncio.create_task(receive_messages())
        pubsub_task = asyncio.create_task(listen_pubsub())

        # Wait for either task to complete (usually due to disconnect)
        done, pending = await asyncio.wait(
            [receive_task, pubsub_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user={user_id}, org={organization_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Clean up
        if receive_task and not receive_task.done():
            receive_task.cancel()
        if pubsub_task and not pubsub_task.done():
            pubsub_task.cancel()

        await websocket_manager.disconnect(websocket, organization_id)
