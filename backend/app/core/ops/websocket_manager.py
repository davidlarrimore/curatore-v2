"""
WebSocket Connection Manager for Real-Time Job Updates.

Manages WebSocket connections per organization for broadcasting real-time
job status updates to connected clients.

Usage:
    from app.core.ops.websocket_manager import websocket_manager

    # Connect a client
    await websocket_manager.connect(websocket, organization_id, user_id)

    # Broadcast to all clients in an organization
    await websocket_manager.broadcast_to_org(organization_id, message)

    # Disconnect a client
    await websocket_manager.disconnect(websocket, organization_id)

Architecture:
    - Maintains connection pools per organization for multi-tenant isolation
    - Thread-safe connection management with asyncio locks
    - Integrates with Redis pub/sub for distributed message handling
    - Supports graceful connection lifecycle management
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Set
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("curatore.websocket_manager")


@dataclass
class ConnectionInfo:
    """Information about a WebSocket connection."""

    websocket: WebSocket
    user_id: UUID
    organization_id: UUID
    connected_at: datetime = field(default_factory=datetime.utcnow)


class WebSocketManager:
    """
    Manages WebSocket connections for real-time updates.

    Tracks active connections per organization and provides methods for
    broadcasting messages to specific organizations or all connected clients.

    Attributes:
        _connections: Mapping of organization_id -> set of WebSocket connections
        _connection_info: Mapping of WebSocket -> ConnectionInfo
        _lock: Async lock for thread-safe connection management
    """

    def __init__(self):
        """Initialize the WebSocket manager."""
        # org_id -> set of websocket connections
        self._connections: Dict[UUID, Set[WebSocket]] = {}
        # websocket -> connection info
        self._connection_info: Dict[WebSocket, ConnectionInfo] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        organization_id: UUID,
        user_id: UUID,
    ) -> None:
        """
        Register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to register
            organization_id: The organization this connection belongs to
            user_id: The user who owns this connection

        Note:
            The WebSocket should already be accepted before calling this method.
        """
        async with self._lock:
            # Initialize org connection set if needed
            if organization_id not in self._connections:
                self._connections[organization_id] = set()

            # Add connection to org's set
            self._connections[organization_id].add(websocket)

            # Store connection info
            self._connection_info[websocket] = ConnectionInfo(
                websocket=websocket,
                user_id=user_id,
                organization_id=organization_id,
            )

            logger.info(
                f"WebSocket connected: user={user_id}, org={organization_id}, "
                f"total_org_connections={len(self._connections[organization_id])}"
            )

    async def disconnect(
        self,
        websocket: WebSocket,
        organization_id: Optional[UUID] = None,
    ) -> None:
        """
        Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove
            organization_id: The organization this connection belongs to
                           (optional, will be looked up if not provided)
        """
        async with self._lock:
            # Get connection info if org_id not provided
            if organization_id is None:
                info = self._connection_info.get(websocket)
                if info:
                    organization_id = info.organization_id

            # Remove from connection info
            info = self._connection_info.pop(websocket, None)

            # Remove from org's connection set
            if organization_id and organization_id in self._connections:
                self._connections[organization_id].discard(websocket)

                # Clean up empty org sets
                if not self._connections[organization_id]:
                    del self._connections[organization_id]

            if info:
                logger.info(
                    f"WebSocket disconnected: user={info.user_id}, org={info.organization_id}"
                )

    async def broadcast_to_org(
        self,
        organization_id: UUID,
        message: Dict[str, Any],
    ) -> int:
        """
        Broadcast a message to all connections in an organization.

        Args:
            organization_id: The organization to broadcast to
            message: The message to send (will be JSON encoded)

        Returns:
            Number of connections the message was sent to
        """
        async with self._lock:
            connections = self._connections.get(organization_id, set()).copy()

        if not connections:
            return 0

        message_json = json.dumps(message)
        sent_count = 0
        failed_connections: Set[WebSocket] = set()

        for websocket in connections:
            try:
                await websocket.send_text(message_json)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send message to WebSocket: {e}")
                failed_connections.add(websocket)

        # Clean up failed connections
        for websocket in failed_connections:
            await self.disconnect(websocket, organization_id)

        return sent_count

    async def send_to_connection(
        self,
        websocket: WebSocket,
        message: Dict[str, Any],
    ) -> bool:
        """
        Send a message to a specific connection.

        Args:
            websocket: The WebSocket connection to send to
            message: The message to send (will be JSON encoded)

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            message_json = json.dumps(message)
            await websocket.send_text(message_json)
            return True
        except Exception as e:
            logger.warning(f"Failed to send message to WebSocket: {e}")
            return False

    def get_org_connection_count(self, organization_id: UUID) -> int:
        """
        Get the number of connections for an organization.

        Args:
            organization_id: The organization to check

        Returns:
            Number of active connections
        """
        return len(self._connections.get(organization_id, set()))

    def get_total_connection_count(self) -> int:
        """
        Get the total number of active connections.

        Returns:
            Total number of connections across all organizations
        """
        return len(self._connection_info)

    def get_connected_orgs(self) -> Set[UUID]:
        """
        Get the set of organizations with active connections.

        Returns:
            Set of organization UUIDs with active WebSocket connections
        """
        return set(self._connections.keys())

    async def close_all(self) -> None:
        """
        Close all active WebSocket connections.

        Used during shutdown to gracefully close all connections.
        """
        async with self._lock:
            all_connections = list(self._connection_info.keys())

        for websocket in all_connections:
            try:
                await websocket.close(code=1001, reason="Server shutdown")
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")

            await self.disconnect(websocket)

        logger.info("All WebSocket connections closed")


# Singleton instance
websocket_manager = WebSocketManager()
