# Progress Service
"""Track and stream progress for long-running tool executions."""

import asyncio
import logging
import time
from typing import Any, Dict, Optional, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("mcp.services.progress")


class ProgressStatus(str, Enum):
    """Progress status values."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ProgressState:
    """State for a single progress-tracked execution."""
    token: str
    tool_name: str
    status: ProgressStatus = ProgressStatus.PENDING
    progress: int = 0
    total: Optional[int] = None
    message: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Event for notifying subscribers
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _subscribers: int = field(default=0, repr=False)

    def update(
        self,
        progress: Optional[int] = None,
        total: Optional[int] = None,
        message: Optional[str] = None,
        status: Optional[ProgressStatus] = None,
    ):
        """Update progress state and notify subscribers."""
        if progress is not None:
            self.progress = progress
        if total is not None:
            self.total = total
        if message is not None:
            self.message = message
        if status is not None:
            self.status = status
        self.updated_at = time.time()
        self._event.set()
        self._event.clear()

    def complete(self, result: Dict[str, Any]):
        """Mark execution as complete with result."""
        self.status = ProgressStatus.COMPLETED
        self.result = result
        self.progress = self.total or 100
        self.updated_at = time.time()
        self._event.set()

    def fail(self, error: str):
        """Mark execution as failed."""
        self.status = ProgressStatus.ERROR
        self.error = error
        self.updated_at = time.time()
        self._event.set()

    def to_notification(self) -> Dict[str, Any]:
        """Convert to MCP progress notification format."""
        data = {
            "progressToken": self.token,
            "progress": self.progress,
        }
        if self.total is not None:
            data["total"] = self.total
        if self.message:
            data["message"] = self.message
        return data

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "token": self.token,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "progress": self.progress,
            "total": self.total,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ProgressService:
    """
    Service for tracking tool execution progress.

    Supports MCP's notifications/progress pattern with SSE streaming.
    """

    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize progress service.

        Args:
            ttl_seconds: Time-to-live for completed progress entries
        """
        self._states: Dict[str, ProgressState] = {}
        self._ttl = ttl_seconds
        self._cleanup_task: Optional[asyncio.Task] = None

    def start(self, token: str, tool_name: str, total: Optional[int] = None) -> ProgressState:
        """
        Start tracking progress for a tool execution.

        Args:
            token: Progress token from client
            tool_name: Name of the tool being executed
            total: Total steps if known

        Returns:
            ProgressState for this execution
        """
        state = ProgressState(
            token=token,
            tool_name=tool_name,
            status=ProgressStatus.RUNNING,
            total=total,
            message=f"Starting {tool_name}...",
        )
        self._states[token] = state
        logger.info(f"Started progress tracking: {token} for {tool_name}")
        return state

    def get(self, token: str) -> Optional[ProgressState]:
        """Get progress state by token."""
        return self._states.get(token)

    def update(
        self,
        token: str,
        progress: Optional[int] = None,
        total: Optional[int] = None,
        message: Optional[str] = None,
    ):
        """
        Update progress for a token.

        Args:
            token: Progress token
            progress: Current progress value
            total: Total steps (can be updated)
            message: Human-readable status message
        """
        state = self._states.get(token)
        if state:
            state.update(progress=progress, total=total, message=message)
            logger.debug(f"Progress update: {token} - {progress}/{total} - {message}")

    def complete(self, token: str, result: Dict[str, Any]):
        """Mark execution as complete."""
        state = self._states.get(token)
        if state:
            state.complete(result)
            logger.info(f"Progress complete: {token}")

    def fail(self, token: str, error: str):
        """Mark execution as failed."""
        state = self._states.get(token)
        if state:
            state.fail(error)
            logger.warning(f"Progress failed: {token} - {error}")

    async def subscribe(
        self,
        token: str,
        timeout: float = 300,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Subscribe to progress updates for a token.

        Yields MCP-formatted progress notifications until completion.

        Args:
            token: Progress token to subscribe to
            timeout: Maximum time to wait for updates

        Yields:
            Progress notification dictionaries
        """
        state = self._states.get(token)
        if not state:
            return

        state._subscribers += 1
        start_time = time.time()

        try:
            # Yield initial state
            yield {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": state.to_notification(),
            }

            # Stream updates until complete or timeout
            while state.status == ProgressStatus.RUNNING:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.warning(f"Progress subscription timeout: {token}")
                    break

                try:
                    await asyncio.wait_for(
                        state._event.wait(),
                        timeout=min(30, timeout - elapsed),
                    )
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield {
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": state.to_notification(),
                    }
                    continue

                # Yield update
                yield {
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": state.to_notification(),
                }

            # Yield final state
            if state.status == ProgressStatus.COMPLETED:
                yield {
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {
                        **state.to_notification(),
                        "status": "completed",
                    },
                }
            elif state.status == ProgressStatus.ERROR:
                yield {
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {
                        **state.to_notification(),
                        "status": "error",
                        "error": state.error,
                    },
                }

        finally:
            state._subscribers -= 1

    def cleanup_old(self):
        """Remove completed/failed entries older than TTL."""
        now = time.time()
        expired = [
            token
            for token, state in self._states.items()
            if state.status in (ProgressStatus.COMPLETED, ProgressStatus.ERROR)
            and state._subscribers == 0
            and (now - state.updated_at) > self._ttl
        ]
        for token in expired:
            del self._states[token]
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired progress entries")

    def list_active(self) -> Dict[str, Dict[str, Any]]:
        """List all active progress states."""
        return {
            token: state.to_dict()
            for token, state in self._states.items()
            if state.status == ProgressStatus.RUNNING
        }


# Global instance
progress_service = ProgressService()
