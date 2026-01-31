"""
Unity Instance Registry

Manages multiple Unity Editor instances connected to the Relay Server.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

from .protocol import InstanceStatus
from .status_file import is_instance_reloading

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AmbiguousInstanceError(Exception):
    """Raised when instance specification matches multiple instances."""

    def __init__(self, query: str, candidates: list[UnityInstance]) -> None:
        self.query = query
        self.candidates = candidates
        names = ", ".join(f"{c.project_name} ({c.instance_id})" for c in candidates)
        super().__init__(f"Ambiguous instance '{query}': matches {names}")


# Queue configuration
QUEUE_MAX_SIZE = 10
QUEUE_ENABLED = False  # Default: disabled for simplicity


class QueuedCommand(NamedTuple):
    """A command waiting in the queue"""

    request_id: str
    command: str
    params: dict[str, Any]
    timeout_ms: int
    future: asyncio.Future[dict[str, Any]]


@dataclass
class UnityInstance:
    """Represents a connected Unity Editor instance"""

    instance_id: str  # Project path (e.g., "/Users/dev/MyGame")
    project_name: str
    unity_version: str
    capabilities: list[str] = field(default_factory=list)
    status: InstanceStatus = InstanceStatus.DISCONNECTED
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    reloading_since: float | None = None
    # Command queue (FIFO)
    command_queue: deque[QueuedCommand] = field(default_factory=deque)
    queue_enabled: bool = QUEUE_ENABLED

    @property
    def is_connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing() and self.status != InstanceStatus.DISCONNECTED

    @property
    def is_available(self) -> bool:
        """Can accept commands"""
        return self.is_connected and self.status == InstanceStatus.READY

    @property
    def queue_size(self) -> int:
        """Current queue size"""
        return len(self.command_queue)

    @property
    def is_queue_full(self) -> bool:
        """Check if queue is full"""
        return len(self.command_queue) >= QUEUE_MAX_SIZE

    def to_dict(self, is_default: bool = False) -> dict:
        """Convert to dictionary for API response"""
        return {
            "instance_id": self.instance_id,
            "project_name": self.project_name,
            "unity_version": self.unity_version,
            "status": self.status.value,
            "is_default": is_default,
            "capabilities": self.capabilities,
            "queue_size": self.queue_size,
        }

    def update_heartbeat(self) -> None:
        """Update last heartbeat timestamp"""
        self.last_heartbeat = time.time()

    def set_status(self, status: InstanceStatus) -> None:
        """Update instance status"""
        old_status = self.status
        self.status = status

        if status == InstanceStatus.RELOADING:
            self.reloading_since = time.time()
        elif old_status == InstanceStatus.RELOADING:
            self.reloading_since = None

        logger.debug(f"Instance {self.instance_id}: {old_status.value} -> {status.value}")

    def enqueue_command(self, cmd: QueuedCommand) -> bool:
        """
        Add a command to the queue.
        Returns True if successful, False if queue is full or disabled.
        """
        if not self.queue_enabled:
            return False
        if self.is_queue_full:
            return False
        self.command_queue.append(cmd)
        logger.debug(f"Enqueued command {cmd.request_id} for {self.instance_id} (queue size: {self.queue_size})")
        return True

    def dequeue_command(self) -> QueuedCommand | None:
        """Get the next command from the queue (FIFO)."""
        if self.command_queue:
            cmd = self.command_queue.popleft()
            logger.debug(f"Dequeued command {cmd.request_id} for {self.instance_id} (queue size: {self.queue_size})")
            return cmd
        return None

    def flush_queue(self, error_code: str, error_message: str) -> None:
        """
        Flush all queued commands with an error.
        Called when instance goes to RELOADING or DISCONNECTED state.
        """
        from .protocol import ErrorCode, ErrorMessage

        while self.command_queue:
            cmd = self.command_queue.popleft()
            if not cmd.future.done():
                error_response = ErrorMessage.from_code(
                    cmd.request_id,
                    ErrorCode(error_code) if hasattr(ErrorCode, error_code) else ErrorCode.INTERNAL_ERROR,
                    error_message,
                ).to_dict()
                cmd.future.set_result(error_response)
                logger.debug(f"Flushed queued command {cmd.request_id}: {error_code}")

        logger.info(f"Flushed command queue for {self.instance_id}")

    async def close_connection(self) -> None:
        """Close the connection to this instance"""
        # Flush queue before closing
        if self.command_queue:
            self.flush_queue("INSTANCE_DISCONNECTED", "Instance disconnected")

        if self.writer and not self.writer.is_closing():
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
        self.writer = None
        self.reader = None
        self.status = InstanceStatus.DISCONNECTED


class InstanceRegistry:
    """Registry for managing Unity instances"""

    def __init__(self) -> None:
        self._instances: dict[str, UnityInstance] = {}
        self._default_instance_id: str | None = None
        self._lock = asyncio.Lock()
        # Track instances in grace period (instance_id -> cancel task)
        self._grace_period_tasks: dict[str, asyncio.Task[None]] = {}
        # Remember if instance was default before going into grace period
        self._was_default: dict[str, bool] = {}

    async def register(
        self,
        instance_id: str,
        project_name: str,
        unity_version: str,
        capabilities: list[str],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> UnityInstance:
        """
        Register a new Unity instance.

        If an instance with the same ID exists, forcefully close the old connection
        and replace it (takeover rule).

        If instance is reconnecting from grace period, restore default status if applicable.
        """
        async with self._lock:
            # Cancel grace period if reconnecting
            restore_default = False
            if instance_id in self._grace_period_tasks:
                self._grace_period_tasks[instance_id].cancel()
                del self._grace_period_tasks[instance_id]
                restore_default = self._was_default.pop(instance_id, False)
                logger.info(f"Instance {instance_id} reconnected during grace period (was_default={restore_default})")

            # Check for existing instance (takeover)
            if instance_id in self._instances:
                old_instance = self._instances[instance_id]
                logger.info(
                    f"Takeover: Replacing existing instance {instance_id} (old status: {old_instance.status.value})"
                )
                await old_instance.close_connection()

            # Create new instance
            instance = UnityInstance(
                instance_id=instance_id,
                project_name=project_name,
                unity_version=unity_version,
                capabilities=capabilities,
                status=InstanceStatus.READY,
                reader=reader,
                writer=writer,
            )
            self._instances[instance_id] = instance

            # Restore default if it was default before grace period
            if restore_default:
                self._default_instance_id = instance_id
                logger.info(f"Restored default instance: {instance_id}")
            # Set as default if first instance
            elif self._default_instance_id is None:
                self._default_instance_id = instance_id
                logger.info(f"Set default instance: {instance_id}")

            logger.info(f"Registered instance: {instance_id} (project: {project_name}, unity: {unity_version})")
            return instance

    async def unregister(self, instance_id: str) -> bool:
        """Unregister and close an instance"""
        async with self._lock:
            if instance_id not in self._instances:
                return False

            instance = self._instances.pop(instance_id)
            await instance.close_connection()

            # Update default if needed
            if self._default_instance_id == instance_id:
                if self._instances:
                    self._default_instance_id = next(iter(self._instances))
                    logger.info(f"New default instance: {self._default_instance_id}")
                else:
                    self._default_instance_id = None

            logger.info(f"Unregistered instance: {instance_id}")
            return True

    async def disconnect_with_grace_period(
        self,
        instance_id: str,
        grace_period_ms: int,
    ) -> None:
        """
        Disconnect an instance with grace period for RELOADING state.

        If the instance was RELOADING when disconnected, wait for grace_period_ms
        before fully unregistering. During this period:
        - The instance is removed from active instances
        - If it was default, default is NOT changed
        - If it reconnects within grace period, it resumes as default

        Args:
            instance_id: The instance to disconnect
            grace_period_ms: Time to wait before full unregister (milliseconds)
        """
        instance = self._instances.get(instance_id)
        if not instance:
            return

        was_reloading = instance.status == InstanceStatus.RELOADING
        if not was_reloading:
            was_reloading = is_instance_reloading(instance_id)
            if was_reloading:
                logger.info(f"Instance {instance_id} detected as reloading via status file")
        was_default = self._default_instance_id == instance_id

        # Close connection but keep tracking
        await instance.close_connection()

        if was_reloading and grace_period_ms > 0:
            # Enter grace period - remove from instances but track for reconnection
            async with self._lock:
                if instance_id in self._instances:
                    del self._instances[instance_id]

                # Remember default status for restoration
                self._was_default[instance_id] = was_default

                # Don't change default during grace period
                logger.info(
                    f"Instance {instance_id} entering grace period ({grace_period_ms}ms, was_default={was_default})"
                )

            # Start grace period timer
            async def grace_period_timeout() -> None:
                try:
                    await asyncio.sleep(grace_period_ms / 1000)
                    # Grace period expired - fully unregister
                    async with self._lock:
                        if instance_id in self._grace_period_tasks:
                            del self._grace_period_tasks[instance_id]
                        was_default_expired = self._was_default.pop(instance_id, False)

                        # Now update default if needed
                        if was_default_expired and self._default_instance_id == instance_id:
                            if self._instances:
                                self._default_instance_id = next(iter(self._instances))
                                logger.info(f"Grace period expired. New default: {self._default_instance_id}")
                            else:
                                self._default_instance_id = None
                                logger.info("Grace period expired. No instances remaining.")

                        logger.info(f"Instance {instance_id} grace period expired, fully unregistered")
                except asyncio.CancelledError:
                    # Reconnected during grace period
                    pass

            task = asyncio.create_task(grace_period_timeout())
            self._grace_period_tasks[instance_id] = task
        else:
            # Immediate unregister (not reloading or grace period disabled)
            await self.unregister(instance_id)

    def get(self, instance_id: str) -> UnityInstance | None:
        """Get an instance by ID"""
        return self._instances.get(instance_id)

    def get_default(self) -> UnityInstance | None:
        """Get the default instance"""
        if self._default_instance_id:
            return self._instances.get(self._default_instance_id)
        return None

    def set_default(self, instance_id: str) -> bool:
        """Set the default instance"""
        if instance_id not in self._instances:
            return False
        self._default_instance_id = instance_id
        logger.info(f"Set default instance: {instance_id}")
        return True

    def update_status(self, instance_id: str, status: InstanceStatus) -> bool:
        """Update instance status"""
        instance = self._instances.get(instance_id)
        if not instance:
            return False
        instance.set_status(status)
        return True

    def list_all(self) -> list[dict]:
        """List all instances as dictionaries"""
        return [
            instance.to_dict(is_default=(instance.instance_id == self._default_instance_id))
            for instance in self._instances.values()
        ]

    def _resolve_instance(self, query: str) -> UnityInstance | None:
        """Resolve an instance by 4-stage matching.

        Priority:
            1. instance_id exact match
            2. project_name exact match
            3. instance_id suffix match (path ends with query)
            4. project_name prefix match

        Each stage: 1 match → return, multiple → AmbiguousInstanceError, 0 → next stage.

        Raises:
            AmbiguousInstanceError: When multiple instances match at the same priority level.
        """
        # Stage 1: instance_id exact match
        exact = self._instances.get(query)
        if exact:
            return exact

        # Stage 2: project_name exact match
        name_matches = [i for i in self._instances.values() if i.project_name == query]
        if len(name_matches) == 1:
            return name_matches[0]
        if len(name_matches) > 1:
            raise AmbiguousInstanceError(query, name_matches)

        # Stage 3: instance_id suffix match (path ending)
        suffix_matches = [
            i
            for i in self._instances.values()
            if i.instance_id.endswith("/" + query) or i.instance_id.endswith("\\" + query)
        ]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        if len(suffix_matches) > 1:
            raise AmbiguousInstanceError(query, suffix_matches)

        # Stage 4: project_name prefix match
        prefix_matches = [i for i in self._instances.values() if i.project_name.startswith(query)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        if len(prefix_matches) > 1:
            raise AmbiguousInstanceError(query, prefix_matches)

        return None

    def get_instance_for_request(self, instance_id: str | None = None) -> UnityInstance | None:
        """Get the instance to handle a request.

        If instance_id is provided, resolves via 4-stage matching.
        Otherwise, returns the default instance.

        Raises:
            AmbiguousInstanceError: When instance_id matches multiple instances.
        """
        if instance_id:
            return self._resolve_instance(instance_id)
        return self.get_default()

    @property
    def count(self) -> int:
        """Number of registered instances"""
        return len(self._instances)

    @property
    def connected_count(self) -> int:
        """Number of connected instances"""
        return sum(1 for i in self._instances.values() if i.is_connected)

    async def close_all(self) -> None:
        """Close all instance connections"""
        async with self._lock:
            for instance in self._instances.values():
                await instance.close_connection()
            self._instances.clear()
            self._default_instance_id = None
            logger.info("Closed all instances")

    def get_instances_by_status(self, status: InstanceStatus) -> list[UnityInstance]:
        """Get all instances with a specific status"""
        return [i for i in self._instances.values() if i.status == status]

    async def handle_heartbeat_timeout(self, instance_id: str, timeout_ms: int = 15000) -> bool:
        """
        Check if an instance has timed out on heartbeat.
        Returns True if the instance was disconnected due to timeout.
        """
        instance = self._instances.get(instance_id)
        if not instance:
            return False

        elapsed = (time.time() - instance.last_heartbeat) * 1000

        # Use reload_timeout for reloading instances
        if instance.status == InstanceStatus.RELOADING:
            timeout_ms = 30000  # reload_timeout_ms

        if elapsed > timeout_ms:
            logger.warning(
                f"Instance {instance_id} heartbeat timeout (elapsed: {elapsed:.0f}ms, timeout: {timeout_ms}ms)"
            )
            instance.set_status(InstanceStatus.DISCONNECTED)
            return True

        return False
