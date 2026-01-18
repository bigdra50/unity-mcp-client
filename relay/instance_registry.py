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

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

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
        """
        async with self._lock:
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

            # Set as default if first instance
            if self._default_instance_id is None:
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

    def get_instance_for_request(self, instance_id: str | None = None) -> UnityInstance | None:
        """
        Get the instance to handle a request.

        If instance_id is provided, returns that specific instance.
        Otherwise, returns the default instance.
        """
        if instance_id:
            return self.get(instance_id)
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
