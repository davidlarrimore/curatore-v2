"""
Redis Pub/Sub Service for Real-Time Job Updates.

Provides publish/subscribe functionality for broadcasting job status updates
to WebSocket clients via Redis channels.

Usage:
    from app.services.pubsub_service import pubsub_service

    # Publish a job update
    await pubsub_service.publish_job_update(
        organization_id=org_id,
        event_type="run_status",
        payload={"run_id": "...", "status": "completed", ...}
    )

    # Subscribe to job updates for an organization
    async for message in pubsub_service.subscribe_org_channel(org_id):
        print(f"Received: {message}")

Architecture:
    - Uses Redis DB 2 for pub/sub (separate from Celery broker on DB 0/1)
    - Channel pattern: curatore:org:{organization_id}:jobs
    - Multi-tenant isolation enforced at channel level
    - Each organization gets its own channel for job updates
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional
from uuid import UUID

import redis.asyncio as redis

logger = logging.getLogger("curatore.pubsub_service")


def _serialize_uuid(obj: Any) -> Any:
    """Convert UUIDs to strings for JSON serialization."""
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize_uuid(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_uuid(item) for item in obj]
    return obj


class PubSubService:
    """
    Service for Redis pub/sub operations for real-time job updates.

    Manages Redis connections for publishing and subscribing to job update
    channels. Each organization has its own channel for multi-tenant isolation.

    Attributes:
        _redis_url: Redis connection URL for pub/sub (uses DB 2)
        _publisher: Redis client for publishing messages
        _connected: Whether the publisher is connected
    """

    def __init__(self):
        """Initialize the pub/sub service."""
        # Parse Redis URL and use DB 2 for pub/sub
        base_redis_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
        # Replace the database number with 2 for pub/sub
        if base_redis_url.endswith("/0"):
            self._redis_url = base_redis_url[:-1] + "2"
        elif base_redis_url.endswith("/1"):
            self._redis_url = base_redis_url[:-1] + "2"
        else:
            # Just append /2 if no db specified
            self._redis_url = base_redis_url.rstrip("/") + "/2"

        self._publisher: Optional[redis.Redis] = None
        self._connected = False
        self._lock = asyncio.Lock()

    def _get_channel_name(self, organization_id: UUID) -> str:
        """
        Generate the Redis channel name for an organization.

        Args:
            organization_id: The organization's UUID

        Returns:
            Channel name in format: curatore:org:{org_id}:jobs
        """
        return f"curatore:org:{organization_id}:jobs"

    async def _ensure_connected(self) -> redis.Redis:
        """
        Ensure we have a connected Redis publisher.

        Returns:
            Connected Redis client

        Raises:
            ConnectionError: If unable to connect to Redis
        """
        async with self._lock:
            if self._publisher is None or not self._connected:
                try:
                    self._publisher = redis.from_url(
                        self._redis_url,
                        encoding="utf-8",
                        decode_responses=True,
                    )
                    # Test connection
                    await self._publisher.ping()
                    self._connected = True
                    logger.info(f"Connected to Redis pub/sub at {self._redis_url}")
                except Exception as e:
                    self._connected = False
                    logger.error(f"Failed to connect to Redis pub/sub: {e}")
                    raise ConnectionError(f"Failed to connect to Redis: {e}") from e

            return self._publisher

    async def publish_job_update(
        self,
        organization_id: UUID,
        event_type: str,
        payload: Dict[str, Any],
    ) -> bool:
        """
        Publish a job update to the organization's channel.

        Args:
            organization_id: The organization UUID to publish to
            event_type: Type of event ('run_status', 'run_progress', 'queue_stats')
            payload: Event data to publish

        Returns:
            True if published successfully, False otherwise

        Message format:
            {
                "type": "run_status",
                "timestamp": "2024-01-15T12:00:00Z",
                "data": { ... payload ... }
            }
        """
        try:
            publisher = await self._ensure_connected()

            channel = self._get_channel_name(organization_id)

            # Build message with timestamp
            message = {
                "type": event_type,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data": _serialize_uuid(payload),
            }

            message_json = json.dumps(message)

            # Publish to channel
            num_subscribers = await publisher.publish(channel, message_json)

            logger.debug(
                f"Published {event_type} to {channel} "
                f"({num_subscribers} subscribers)"
            )

            return True

        except Exception as e:
            logger.warning(f"Failed to publish job update: {e}")
            self._connected = False
            return False

    async def subscribe_org_channel(
        self,
        organization_id: UUID,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Subscribe to job updates for an organization.

        Yields messages as they are received on the organization's channel.
        This is an async generator that should be used in an async for loop.

        Args:
            organization_id: The organization UUID to subscribe to

        Yields:
            Parsed message dictionaries with type, timestamp, and data fields

        Example:
            async for message in pubsub_service.subscribe_org_channel(org_id):
                if message["type"] == "run_status":
                    handle_status_update(message["data"])
        """
        channel = self._get_channel_name(organization_id)

        # Create a new Redis connection for this subscriber
        subscriber = redis.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

        try:
            pubsub = subscriber.pubsub()
            await pubsub.subscribe(channel)

            logger.info(f"Subscribed to channel: {channel}")

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        yield data
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse message: {e}")
                        continue

        except asyncio.CancelledError:
            logger.info(f"Subscription cancelled for channel: {channel}")
            raise
        finally:
            await pubsub.unsubscribe(channel)
            await subscriber.close()
            logger.info(f"Unsubscribed from channel: {channel}")

    async def close(self) -> None:
        """Close the publisher connection."""
        async with self._lock:
            if self._publisher:
                await self._publisher.close()
                self._publisher = None
                self._connected = False
                logger.info("Closed Redis pub/sub publisher connection")


# Singleton instance
pubsub_service = PubSubService()
