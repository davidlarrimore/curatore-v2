"""
Redis-based distributed locking service for Curatore v2.

This service provides distributed locking to prevent concurrent execution
of the same scheduled task across multiple workers. Uses Redis SET NX PX
for atomic lock acquisition with automatic expiration.

Key Features:
- Atomic lock acquisition with SET NX PX
- Automatic lock expiration (prevents deadlocks)
- Lock extension for long-running tasks
- Context manager support for safe lock release

Usage:
    from app.core.shared.lock_service import lock_service

    # Acquire lock (blocking)
    lock_id = await lock_service.acquire_lock("task_name", timeout=300)
    if lock_id:
        try:
            # Do work
            pass
        finally:
            await lock_service.release_lock("task_name", lock_id)

    # Or use context manager
    async with lock_service.lock("task_name", timeout=300) as acquired:
        if acquired:
            # Do work
            pass
"""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger("curatore.services.lock")


class LockService:
    """
    Distributed locking service using Redis.

    Provides lock acquisition, release, and extension for coordinating
    concurrent task execution across multiple workers.

    Attributes:
        _redis: Async Redis client
        _lock_prefix: Prefix for lock keys in Redis

    Lock Key Format:
        curatore:lock:{resource_name}

    Lock Value Format:
        {lock_id}:{acquired_at}

    Example:
        curatore:lock:cleanup_expired_jobs = abc123:2026-01-28T12:00:00
    """

    def __init__(self):
        """Initialize lock service with Redis connection from environment."""
        self._redis: Optional[redis.Redis] = None
        self._redis_loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock_prefix = "curatore:lock:"

    async def _get_redis(self) -> redis.Redis:
        """
        Get or create Redis connection.

        Returns:
            Async Redis client

        Note:
            Uses CELERY_BROKER_URL for connection (same Redis as Celery)
        """
        loop = asyncio.get_running_loop()
        if self._redis is None or self._redis_loop is None or self._redis_loop is not loop:
            # When event loop changes (e.g., between asyncio.run() calls in Celery),
            # we cannot close the old Redis client because it's bound to a closed loop.
            # Just abandon it and create a new one - the old resources are already gone.
            if self._redis is not None and self._redis_loop is loop:
                # Only close if we're in the same loop (e.g., explicit cleanup)
                await self._redis.close()
            self._redis_loop = loop
            broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
            self._redis = await redis.from_url(broker_url, decode_responses=True)
        return self._redis

    async def acquire_lock(
        self,
        resource_name: str,
        timeout: int = 300,
        retry_interval: float = 0.5,
        max_retries: int = 0,
    ) -> Optional[str]:
        """
        Attempt to acquire a distributed lock.

        Uses Redis SET NX PX for atomic lock acquisition with expiration.
        The lock automatically expires after timeout seconds to prevent deadlocks.

        Args:
            resource_name: Name of the resource to lock (e.g., "cleanup_expired_jobs")
            timeout: Lock expiration in seconds (default: 300 = 5 minutes)
            retry_interval: Seconds between retry attempts (default: 0.5)
            max_retries: Maximum retry attempts (0 = no retries, default)

        Returns:
            Lock ID string if acquired, None if lock not available

        Example:
            lock_id = await lock_service.acquire_lock("my_task", timeout=600)
            if lock_id:
                # Lock acquired, do work
                await lock_service.release_lock("my_task", lock_id)
            else:
                # Another worker holds the lock
                pass
        """
        r = await self._get_redis()
        lock_key = f"{self._lock_prefix}{resource_name}"
        lock_id = str(uuid.uuid4())
        lock_value = f"{lock_id}:{datetime.utcnow().isoformat()}"

        attempts = 0
        while True:
            # SET NX PX: Set only if not exists, with expiration in milliseconds
            acquired = await r.set(
                lock_key,
                lock_value,
                nx=True,
                px=timeout * 1000,
            )

            if acquired:
                logger.debug(f"Lock acquired: {resource_name} (id={lock_id[:8]}..., timeout={timeout}s)")
                return lock_id

            # Lock not acquired
            attempts += 1
            if attempts > max_retries:
                logger.debug(f"Lock not available: {resource_name} (attempts={attempts})")
                return None

            # Wait before retry
            await asyncio.sleep(retry_interval)

    async def release_lock(self, resource_name: str, lock_id: str) -> bool:
        """
        Release a distributed lock.

        Only releases the lock if the lock_id matches (prevents releasing
        locks held by other workers).

        Args:
            resource_name: Name of the resource to unlock
            lock_id: Lock ID returned from acquire_lock

        Returns:
            True if lock was released, False if lock not held or mismatch

        Example:
            success = await lock_service.release_lock("my_task", lock_id)
            if not success:
                logger.warning("Lock was not held or expired")
        """
        r = await self._get_redis()
        lock_key = f"{self._lock_prefix}{resource_name}"

        # Lua script for atomic check-and-delete
        # Only delete if the lock value starts with our lock_id
        release_script = """
        local current = redis.call('GET', KEYS[1])
        if current and string.find(current, ARGV[1], 1, true) == 1 then
            return redis.call('DEL', KEYS[1])
        end
        return 0
        """

        result = await r.eval(release_script, 1, lock_key, lock_id)
        released = result == 1

        if released:
            logger.debug(f"Lock released: {resource_name} (id={lock_id[:8]}...)")
        else:
            logger.debug(f"Lock not released (not held or mismatch): {resource_name}")

        return released

    async def extend_lock(
        self, resource_name: str, lock_id: str, additional_seconds: int = 300
    ) -> bool:
        """
        Extend the expiration of a held lock.

        Useful for long-running tasks that may exceed the initial timeout.
        Only extends if the lock_id matches.

        Args:
            resource_name: Name of the locked resource
            lock_id: Lock ID returned from acquire_lock
            additional_seconds: Additional time in seconds (default: 300)

        Returns:
            True if lock was extended, False if lock not held or mismatch

        Example:
            # Extend lock by another 5 minutes
            extended = await lock_service.extend_lock("my_task", lock_id, 300)
        """
        r = await self._get_redis()
        lock_key = f"{self._lock_prefix}{resource_name}"

        # Lua script for atomic check-and-extend
        extend_script = """
        local current = redis.call('GET', KEYS[1])
        if current and string.find(current, ARGV[1], 1, true) == 1 then
            return redis.call('PEXPIRE', KEYS[1], ARGV[2])
        end
        return 0
        """

        result = await r.eval(
            extend_script, 1, lock_key, lock_id, additional_seconds * 1000
        )
        extended = result == 1

        if extended:
            logger.debug(
                f"Lock extended: {resource_name} (id={lock_id[:8]}..., +{additional_seconds}s)"
            )
        else:
            logger.debug(f"Lock not extended (not held or mismatch): {resource_name}")

        return extended

    async def is_locked(self, resource_name: str) -> bool:
        """
        Check if a resource is currently locked.

        Args:
            resource_name: Name of the resource to check

        Returns:
            True if locked, False otherwise
        """
        r = await self._get_redis()
        lock_key = f"{self._lock_prefix}{resource_name}"
        return await r.exists(lock_key) == 1

    async def get_lock_info(self, resource_name: str) -> Optional[dict]:
        """
        Get information about a lock.

        Args:
            resource_name: Name of the resource

        Returns:
            Dict with lock_id and acquired_at, or None if not locked
        """
        r = await self._get_redis()
        lock_key = f"{self._lock_prefix}{resource_name}"
        value = await r.get(lock_key)

        if not value:
            return None

        parts = value.split(":", 1)
        if len(parts) == 2:
            return {
                "lock_id": parts[0],
                "acquired_at": parts[1],
            }
        return {"lock_id": value, "acquired_at": None}

    async def get_ttl(self, resource_name: str) -> Optional[int]:
        """
        Get remaining time-to-live for a lock in seconds.

        Args:
            resource_name: Name of the resource

        Returns:
            TTL in seconds, or None if not locked
        """
        r = await self._get_redis()
        lock_key = f"{self._lock_prefix}{resource_name}"
        ttl = await r.ttl(lock_key)
        return ttl if ttl > 0 else None

    @asynccontextmanager
    async def lock(
        self,
        resource_name: str,
        timeout: int = 300,
        retry_interval: float = 0.5,
        max_retries: int = 0,
    ):
        """
        Context manager for acquiring and releasing locks.

        Yields True if lock was acquired, False otherwise.
        Automatically releases lock on exit.

        Args:
            resource_name: Name of the resource to lock
            timeout: Lock expiration in seconds
            retry_interval: Seconds between retry attempts
            max_retries: Maximum retry attempts

        Yields:
            True if lock acquired, False otherwise

        Example:
            async with lock_service.lock("my_task", timeout=300) as acquired:
                if acquired:
                    # Do work while holding lock
                    pass
                else:
                    # Lock not available
                    pass
        """
        lock_id = await self.acquire_lock(
            resource_name, timeout, retry_interval, max_retries
        )
        try:
            yield lock_id is not None
        finally:
            if lock_id:
                await self.release_lock(resource_name, lock_id)

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._redis_loop = None


# Global singleton instance
lock_service = LockService()
