"""Tests for relay/request_cache.py - Idempotency cache"""

from __future__ import annotations

import asyncio
import time

import pytest

from relay.request_cache import CacheEntry, RequestCache


class TestCacheEntry:
    """Test CacheEntry dataclass"""

    def test_default_created_at(self) -> None:
        entry = CacheEntry(response={"success": True})
        assert entry.created_at > 0
        assert entry.created_at <= time.time()

    def test_is_expired_false(self) -> None:
        entry = CacheEntry(response={"success": True})
        assert entry.is_expired(ttl_seconds=60.0) is False

    def test_is_expired_true(self) -> None:
        # Create entry with old timestamp
        entry = CacheEntry(response={"success": True}, created_at=time.time() - 120)
        assert entry.is_expired(ttl_seconds=60.0) is True


class TestRequestCache:
    """Test RequestCache"""

    @pytest.fixture
    def cache(self) -> RequestCache:
        return RequestCache(ttl_seconds=60.0)

    @pytest.mark.asyncio
    async def test_handle_request_success_cached(self, cache: RequestCache) -> None:
        """Successful responses should be cached"""
        call_count = 0

        async def execute_fn() -> dict:
            nonlocal call_count
            call_count += 1
            return {"success": True, "data": {"value": 42}}

        # First call
        result1 = await cache.handle_request("req-1", execute_fn)
        assert result1["success"] is True
        assert call_count == 1

        # Second call with same ID should use cache
        result2 = await cache.handle_request("req-1", execute_fn)
        assert result2["success"] is True
        assert call_count == 1  # Not called again

    @pytest.mark.asyncio
    async def test_handle_request_error_not_cached(self, cache: RequestCache) -> None:
        """Error responses should NOT be cached"""
        call_count = 0

        async def execute_fn() -> dict:
            nonlocal call_count
            call_count += 1
            return {"success": False, "error": {"code": "TIMEOUT", "message": "Timed out"}}

        # First call
        result1 = await cache.handle_request("req-2", execute_fn)
        assert result1["success"] is False
        assert call_count == 1

        # Second call should execute again (not cached)
        result2 = await cache.handle_request("req-2", execute_fn)
        assert result2["success"] is False
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_handle_request_different_ids(self, cache: RequestCache) -> None:
        """Different request IDs should execute independently"""
        call_count = 0

        async def execute_fn() -> dict:
            nonlocal call_count
            call_count += 1
            return {"success": True, "data": {"call": call_count}}

        result1 = await cache.handle_request("req-a", execute_fn)
        result2 = await cache.handle_request("req-b", execute_fn)

        assert result1["data"]["call"] == 1
        assert result2["data"]["call"] == 2
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_handle_request_in_flight_waits(self, cache: RequestCache) -> None:
        """Duplicate in-flight requests should wait for the original"""
        call_count = 0
        execution_started = asyncio.Event()
        can_complete = asyncio.Event()

        async def slow_execute_fn() -> dict:
            nonlocal call_count
            call_count += 1
            execution_started.set()
            await can_complete.wait()
            return {"success": True, "data": {"value": "done"}}

        # Start first request
        task1 = asyncio.create_task(cache.handle_request("req-slow", slow_execute_fn))

        # Wait for it to start executing
        await execution_started.wait()

        # Start second request with same ID (should wait)
        task2 = asyncio.create_task(cache.handle_request("req-slow", slow_execute_fn))

        # Allow some time for task2 to start waiting
        await asyncio.sleep(0.01)

        # Let the first request complete
        can_complete.set()

        result1 = await task1
        result2 = await task2

        assert result1["success"] is True
        assert result2["success"] is True
        assert call_count == 1  # Only called once

    def test_get_cached_existing(self, cache: RequestCache) -> None:
        """get_cached returns cached entry if exists and not expired"""
        cache._cache["req-cached"] = CacheEntry(response={"success": True, "data": "cached"})

        result = cache.get_cached("req-cached")

        assert result is not None
        assert result["data"] == "cached"

    def test_get_cached_nonexistent(self, cache: RequestCache) -> None:
        """get_cached returns None for nonexistent entries"""
        result = cache.get_cached("nonexistent")
        assert result is None

    def test_get_cached_expired(self, cache: RequestCache) -> None:
        """get_cached returns None for expired entries"""
        cache._cache["req-expired"] = CacheEntry(
            response={"success": True},
            created_at=time.time() - 120,  # 2 minutes ago
        )

        result = cache.get_cached("req-expired")
        assert result is None

    def test_is_pending(self, cache: RequestCache) -> None:
        """is_pending returns correct status"""
        assert cache.is_pending("req-1") is False

        cache._pending["req-1"] = asyncio.Event()
        assert cache.is_pending("req-1") is True

    def test_clear(self, cache: RequestCache) -> None:
        """clear removes all cached entries"""
        cache._cache["req-1"] = CacheEntry(response={"success": True})
        cache._cache["req-2"] = CacheEntry(response={"success": True})
        cache._pending_results["req-3"] = {"success": True}

        cache.clear()

        assert cache.size == 0
        assert len(cache._pending_results) == 0

    def test_size(self, cache: RequestCache) -> None:
        """size returns number of cached entries"""
        assert cache.size == 0

        cache._cache["req-1"] = CacheEntry(response={"success": True})
        assert cache.size == 1

        cache._cache["req-2"] = CacheEntry(response={"success": True})
        assert cache.size == 2

    def test_pending_count(self, cache: RequestCache) -> None:
        """pending_count returns number of in-flight requests"""
        assert cache.pending_count == 0

        cache._pending["req-1"] = asyncio.Event()
        assert cache.pending_count == 1

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, cache: RequestCache) -> None:
        """_cleanup_expired removes expired entries"""
        # Add fresh entry
        cache._cache["fresh"] = CacheEntry(response={"success": True})

        # Add expired entry
        cache._cache["expired"] = CacheEntry(response={"success": True}, created_at=time.time() - 120)

        await cache._cleanup_expired()

        assert "fresh" in cache._cache
        assert "expired" not in cache._cache

    @pytest.mark.asyncio
    async def test_start_stop(self, cache: RequestCache) -> None:
        """start and stop manage cleanup task"""
        await cache.start()
        assert cache._cleanup_task is not None

        await cache.stop()
        assert cache._cleanup_task is None

    @pytest.mark.asyncio
    async def test_exception_in_execute_fn(self, cache: RequestCache) -> None:
        """Exceptions in execute_fn should propagate and clean up pending state"""

        async def failing_fn() -> dict:
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await cache.handle_request("req-fail", failing_fn)

        # Should not be in pending anymore
        assert cache.is_pending("req-fail") is False
        # Should not be cached
        assert cache.get_cached("req-fail") is None
