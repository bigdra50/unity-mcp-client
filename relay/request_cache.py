"""
Request Cache for Idempotency

Caches successful responses to enable idempotent retries.
Only success responses are cached; errors are NOT cached.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached response entry"""

    response: dict[str, Any]
    created_at: float = field(default_factory=time.time)

    def is_expired(self, ttl_seconds: float) -> bool:
        return time.time() - self.created_at > ttl_seconds


class RequestCache:
    """
    Request cache for idempotency.

    Rules:
    - Only SUCCESS responses are cached
    - Errors (TIMEOUT, INSTANCE_RELOADING, etc.) are NOT cached
    - In-flight duplicate requests wait for the original to complete
    """

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._pending: dict[str, asyncio.Event] = {}
        self._pending_results: dict[str, dict[str, Any]] = {}
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background cleanup task"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop the background cleanup task"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired entries"""
        while True:
            await asyncio.sleep(self._ttl_seconds / 2)
            await self._cleanup_expired()

    async def _cleanup_expired(self) -> None:
        """Remove expired cache entries"""
        async with self._lock:
            expired_keys = [
                key
                for key, entry in self._cache.items()
                if entry.is_expired(self._ttl_seconds)
            ]
            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

    async def handle_request(
        self,
        request_id: str,
        execute_fn: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """
        Handle a request with idempotency support.

        1. If cached (success only) -> return cached response
        2. If in-flight -> wait for result
        3. Otherwise -> execute and cache if successful
        """
        # Check cache first
        async with self._lock:
            if request_id in self._cache:
                entry = self._cache[request_id]
                if not entry.is_expired(self._ttl_seconds):
                    logger.debug(f"Cache hit for request {request_id}")
                    return entry.response

            # Check if already in-flight
            if request_id in self._pending:
                logger.debug(f"Request {request_id} is in-flight, waiting...")
                event = self._pending[request_id]

        # If in-flight, wait outside the lock
        if request_id in self._pending:
            await event.wait()
            async with self._lock:
                if request_id in self._pending_results:
                    return self._pending_results.pop(request_id)
                # Fallback: check cache
                if request_id in self._cache:
                    return self._cache[request_id].response
            # If we get here, something went wrong
            raise RuntimeError(f"Request {request_id} completed but result not found")

        # Mark as in-flight
        async with self._lock:
            self._pending[request_id] = asyncio.Event()

        try:
            # Execute the request
            response = await execute_fn()

            # Only cache successful responses
            async with self._lock:
                if response.get("success", False):
                    self._cache[request_id] = CacheEntry(response=response)
                    logger.debug(f"Cached successful response for {request_id}")
                else:
                    logger.debug(
                        f"Not caching error response for {request_id}: "
                        f"{response.get('error', {}).get('code', 'unknown')}"
                    )

                # Store result for waiting requests
                self._pending_results[request_id] = response

            return response

        finally:
            # Signal waiting requests and clean up
            async with self._lock:
                if request_id in self._pending:
                    self._pending[request_id].set()
                    del self._pending[request_id]

    def get_cached(self, request_id: str) -> dict[str, Any] | None:
        """Get a cached response if it exists and is not expired"""
        entry = self._cache.get(request_id)
        if entry and not entry.is_expired(self._ttl_seconds):
            return entry.response
        return None

    def is_pending(self, request_id: str) -> bool:
        """Check if a request is currently in-flight"""
        return request_id in self._pending

    def clear(self) -> None:
        """Clear all cached entries"""
        self._cache.clear()
        self._pending_results.clear()
        logger.debug("Cache cleared")

    @property
    def size(self) -> int:
        """Number of cached entries"""
        return len(self._cache)

    @property
    def pending_count(self) -> int:
        """Number of in-flight requests"""
        return len(self._pending)
