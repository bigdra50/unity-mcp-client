"""
Unity Bridge Relay Server

Main server that relays commands between CLI and Unity Editor instances.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from typing import Any

from .instance_registry import InstanceRegistry, QueuedCommand, UnityInstance
from .protocol import (
    PROTOCOL_VERSION,
    CommandMessage,
    ErrorCode,
    ErrorMessage,
    InstancesMessage,
    InstanceStatus,
    MessageType,
    PingMessage,
    RegisteredMessage,
    ResponseMessage,
    read_frame,
    write_frame,
)
from .request_cache import RequestCache

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6500
HEARTBEAT_INTERVAL_MS = 5000
HEARTBEAT_TIMEOUT_MS = 15000
HEARTBEAT_MAX_RETRIES = 3  # Disconnect after 3 consecutive failures
RELOAD_TIMEOUT_MS = 30000  # Extended timeout during RELOADING
COMMAND_TIMEOUT_MS = 30000


class RelayServer:
    """
    Relay Server for Unity Bridge Protocol.

    Handles connections from:
    - Unity Editor instances (register, status updates, command results)
    - CLI clients (requests, instance queries)
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self.registry = InstanceRegistry()
        self.request_cache = RequestCache(ttl_seconds=60.0)
        self._server: asyncio.Server | None = None
        self._running = False
        self._pending_commands: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task] = {}
        # Single Outstanding PING: track pending PONG per instance
        self._pending_pongs: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        """Start the relay server"""
        await self.request_cache.start()

        self._server = await asyncio.start_server(
            self._handle_connection,
            self.host,
            self.port,
        )
        self._running = True

        addrs = ", ".join(str(sock.getsockname()) for sock in self._server.sockets)
        logger.info(f"Relay Server listening on {addrs}")

        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop the relay server"""
        logger.info("Stopping Relay Server...")
        self._running = False

        # Cancel all heartbeat tasks
        for task in self._heartbeat_tasks.values():
            task.cancel()
        self._heartbeat_tasks.clear()

        # Cancel pending commands
        for future in self._pending_commands.values():
            if not future.done():
                future.cancel()
        self._pending_commands.clear()

        # Close all instances
        await self.registry.close_all()

        # Stop cache cleanup
        await self.request_cache.stop()

        # Close server
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        logger.info("Relay Server stopped")

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a new connection (Unity or CLI)"""
        peername = writer.get_extra_info("peername")
        logger.debug(f"New connection from {peername}")

        try:
            # Read first message to determine connection type
            first_msg = await asyncio.wait_for(read_frame(reader), timeout=10.0)
            msg_type = first_msg.get("type")

            if msg_type == MessageType.REGISTER.value:
                await self._handle_unity_connection(reader, writer, first_msg)
            elif msg_type in (
                MessageType.REQUEST.value,
                MessageType.LIST_INSTANCES.value,
                MessageType.SET_DEFAULT.value,
            ):
                await self._handle_cli_message(writer, first_msg)
                # CLI connections are one-shot
            else:
                logger.warning(f"Unknown message type: {msg_type}")

        except TimeoutError:
            logger.warning(f"Connection timeout from {peername}")
        except asyncio.IncompleteReadError:
            logger.debug(f"Connection closed by {peername}")
        except Exception as e:
            logger.error(f"Error handling connection from {peername}: {e}")
        finally:
            if not writer.is_closing():
                writer.close()
                await writer.wait_closed()

    # ===== Unity Connection Handling =====

    async def _handle_unity_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        register_msg: dict[str, Any],
    ) -> None:
        """Handle a Unity Editor connection"""
        # Validate protocol version
        protocol_version = register_msg.get("protocol_version", "")
        if protocol_version != PROTOCOL_VERSION:
            response = RegisteredMessage(
                success=False,
                error={
                    "code": ErrorCode.PROTOCOL_VERSION_MISMATCH.value,
                    "message": f"Unsupported protocol version: {protocol_version}. Expected: {PROTOCOL_VERSION}",
                },
            )
            await write_frame(writer, response.to_dict())
            return

        # Register instance
        instance_id = register_msg.get("instance_id", "")
        instance = await self.registry.register(
            instance_id=instance_id,
            project_name=register_msg.get("project_name", ""),
            unity_version=register_msg.get("unity_version", ""),
            capabilities=register_msg.get("capabilities", []),
            reader=reader,
            writer=writer,
        )

        # Send registration response
        response = RegisteredMessage(
            success=True,
            heartbeat_interval_ms=HEARTBEAT_INTERVAL_MS,
        )
        await write_frame(writer, response.to_dict())

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(instance_id))
        self._heartbeat_tasks[instance_id] = heartbeat_task

        # Handle messages from Unity
        try:
            while self._running and instance.is_connected:
                try:
                    msg = await asyncio.wait_for(
                        read_frame(reader),
                        timeout=HEARTBEAT_TIMEOUT_MS / 1000,
                    )
                    await self._handle_unity_message(instance, msg)
                except TimeoutError:
                    # Check heartbeat timeout
                    if await self.registry.handle_heartbeat_timeout(instance_id, HEARTBEAT_TIMEOUT_MS):
                        break
        finally:
            # Cleanup
            if instance_id in self._heartbeat_tasks:
                self._heartbeat_tasks[instance_id].cancel()
                del self._heartbeat_tasks[instance_id]

            await self.registry.unregister(instance_id)

    async def _handle_unity_message(
        self,
        instance: UnityInstance,
        msg: dict[str, Any],
    ) -> None:
        """Handle a message from Unity"""
        msg_type = msg.get("type")
        instance.update_heartbeat()

        if msg_type == MessageType.STATUS.value:
            status_str = msg.get("status", "")
            try:
                status = InstanceStatus(status_str)
                self.registry.update_status(instance.instance_id, status)
            except ValueError:
                logger.warning(f"Unknown status: {status_str}")

        elif msg_type == MessageType.COMMAND_RESULT.value:
            request_id = msg.get("id", "")
            logger.info(f"COMMAND_RESULT received: id={request_id}")
            logger.info(f"Pending commands: {list(self._pending_commands.keys())}")
            if request_id in self._pending_commands:
                future = self._pending_commands.pop(request_id)
                if not future.done():
                    logger.info(f"Resolving command result for {request_id}")
                    future.set_result(msg)
            else:
                # Late result (already timed out)
                logger.warning(f"Ignoring late COMMAND_RESULT for {request_id} (not in pending)")

        elif msg_type == MessageType.PONG.value:
            # Heartbeat response - signal the waiting heartbeat loop
            if instance.instance_id in self._pending_pongs:
                self._pending_pongs[instance.instance_id].set()
                logger.debug(f"PONG received from {instance.instance_id}")

        else:
            logger.warning(f"Unknown Unity message type: {msg_type}")

    async def _heartbeat_loop(self, instance_id: str) -> None:
        """
        Send periodic heartbeats to Unity instance.

        Implements:
        - Single Outstanding PING: Wait for PONG before sending next PING
        - 3 consecutive failures → DISCONNECTED
        - Extended timeout during RELOADING state
        """
        consecutive_failures = 0

        try:
            while self._running:
                # Wait before sending next PING
                await asyncio.sleep(HEARTBEAT_INTERVAL_MS / 1000)

                instance = self.registry.get(instance_id)
                if not instance or not instance.is_connected:
                    break

                # Determine timeout based on instance state
                if instance.status == InstanceStatus.RELOADING:
                    timeout_ms = RELOAD_TIMEOUT_MS
                else:
                    timeout_ms = HEARTBEAT_TIMEOUT_MS

                # Create event for PONG response (Single Outstanding PING)
                pong_event = asyncio.Event()
                self._pending_pongs[instance_id] = pong_event

                try:
                    # Send PING
                    ping = PingMessage()
                    await write_frame(instance.writer, ping.to_dict())
                    logger.debug(f"PING sent to {instance_id}")

                    # Wait for PONG with timeout
                    try:
                        await asyncio.wait_for(pong_event.wait(), timeout=timeout_ms / 1000)
                        # PONG received - reset failure counter
                        consecutive_failures = 0
                        logger.debug(f"Heartbeat OK for {instance_id}")

                    except TimeoutError:
                        consecutive_failures += 1
                        logger.warning(
                            f"Heartbeat timeout for {instance_id} ({consecutive_failures}/{HEARTBEAT_MAX_RETRIES})"
                        )

                        if consecutive_failures >= HEARTBEAT_MAX_RETRIES:
                            logger.error(f"Heartbeat failed {HEARTBEAT_MAX_RETRIES} times, disconnecting {instance_id}")
                            break

                except Exception as e:
                    logger.warning(f"Failed to send heartbeat to {instance_id}: {e}")
                    consecutive_failures += 1
                    if consecutive_failures >= HEARTBEAT_MAX_RETRIES:
                        break

                finally:
                    # Cleanup pending pong
                    self._pending_pongs.pop(instance_id, None)

        except asyncio.CancelledError:
            pass
        finally:
            # Cleanup on exit
            self._pending_pongs.pop(instance_id, None)

    async def _process_queue(self, instance: UnityInstance) -> None:
        """
        Process the next command in the instance's queue.
        Called after a command completes.
        """
        if not instance.queue_enabled or not instance.command_queue:
            return

        # Get next command from queue
        queued_cmd = instance.dequeue_command()
        if not queued_cmd:
            return

        # Check if the future is still valid (not cancelled/timed out)
        if queued_cmd.future.done():
            logger.debug(f"Skipping already-done queued command: {queued_cmd.request_id}")
            # Recursively process next in queue
            await self._process_queue(instance)
            return

        logger.info(f"Processing queued command: {queued_cmd.request_id}")

        # Execute the queued command
        result = await self._execute_command(
            request_id=queued_cmd.request_id,
            instance_id=instance.instance_id,
            command=queued_cmd.command,
            params=queued_cmd.params,
            timeout_ms=queued_cmd.timeout_ms,
        )

        # Set the result on the future
        if not queued_cmd.future.done():
            queued_cmd.future.set_result(result)

    # ===== CLI Message Handling =====

    async def _handle_cli_message(
        self,
        writer: asyncio.StreamWriter,
        msg: dict[str, Any],
    ) -> None:
        """Handle a CLI message"""
        msg_type = msg.get("type")
        request_id = msg.get("id", "")

        if msg_type == MessageType.LIST_INSTANCES.value:
            response = InstancesMessage(
                id=request_id,
                success=True,
                data={"instances": self.registry.list_all()},
            )
            await write_frame(writer, response.to_dict())

        elif msg_type == MessageType.SET_DEFAULT.value:
            instance_id = msg.get("instance", "")
            success = self.registry.set_default(instance_id)
            if success:
                response = ResponseMessage(
                    id=request_id,
                    success=True,
                    data={"message": f"Default instance set to {instance_id}"},
                )
            else:
                response = ErrorMessage.from_code(
                    request_id,
                    ErrorCode.INSTANCE_NOT_FOUND,
                    f"Instance not found: {instance_id}",
                )
            await write_frame(writer, response.to_dict())

        elif msg_type == MessageType.REQUEST.value:
            response = await self._handle_request(msg)
            await write_frame(writer, response)

        else:
            response = ErrorMessage.from_code(
                request_id,
                ErrorCode.PROTOCOL_ERROR,
                f"Unknown message type: {msg_type}",
            )
            await write_frame(writer, response.to_dict())

    async def _handle_request(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Handle a REQUEST message from CLI"""
        request_id = msg.get("id", "")
        instance_id = msg.get("instance")
        command = msg.get("command", "")
        params = msg.get("params", {})
        timeout_ms = msg.get("timeout_ms", COMMAND_TIMEOUT_MS)

        # Use request cache for idempotency
        return await self.request_cache.handle_request(
            request_id,
            lambda: self._execute_command(request_id, instance_id, command, params, timeout_ms),
        )

    async def _execute_command(
        self,
        request_id: str,
        instance_id: str | None,
        command: str,
        params: dict[str, Any],
        timeout_ms: int,
    ) -> dict[str, Any]:
        """Execute a command on a Unity instance"""
        # Coplay-style: wait for instance to become ready (max 10 seconds)
        max_wait_ms = 10000
        poll_interval_ms = 250
        waited_ms = 0

        while waited_ms < max_wait_ms:
            # Get target instance
            instance = self.registry.get_instance_for_request(instance_id)

            if not instance:
                if instance_id:
                    return ErrorMessage.from_code(
                        request_id,
                        ErrorCode.INSTANCE_NOT_FOUND,
                        f"Instance not found: {instance_id}",
                    ).to_dict()
                else:
                    # No instances - wait and retry (Unity might be restarting)
                    if waited_ms == 0:
                        logger.info(f"[{request_id}] No instances, waiting for reconnection...")
                    await asyncio.sleep(poll_interval_ms / 1000)
                    waited_ms += poll_interval_ms
                    continue

            # Check instance status
            if instance.status == InstanceStatus.RELOADING:
                if waited_ms == 0:
                    logger.info(f"[{request_id}] Instance is reloading, waiting...")
                await asyncio.sleep(poll_interval_ms / 1000)
                waited_ms += poll_interval_ms
                continue

            if instance.status == InstanceStatus.DISCONNECTED or not instance.is_connected:
                if waited_ms == 0:
                    logger.info(f"[{request_id}] Instance disconnected, waiting for reconnection...")
                await asyncio.sleep(poll_interval_ms / 1000)
                waited_ms += poll_interval_ms
                continue

            # Instance is ready or busy - break out of wait loop
            break

        # Re-check after waiting
        instance = self.registry.get_instance_for_request(instance_id)
        if not instance:
            return ErrorMessage.from_code(
                request_id,
                ErrorCode.INSTANCE_NOT_FOUND,
                f"Instance not found after waiting {waited_ms}ms",
            ).to_dict()

        # Check capability support
        if instance.capabilities and command not in instance.capabilities:
            return ErrorMessage.from_code(
                request_id,
                ErrorCode.CAPABILITY_NOT_SUPPORTED,
                f"Command '{command}' not supported by instance. Available: {', '.join(instance.capabilities)}",
            ).to_dict()

        if instance.status == InstanceStatus.RELOADING:
            return ErrorMessage.from_code(
                request_id,
                ErrorCode.INSTANCE_RELOADING,
                f"Instance still reloading after {waited_ms}ms: {instance.instance_id}",
            ).to_dict()

        if waited_ms > 0:
            logger.info(f"[{request_id}] Instance ready after {waited_ms}ms wait")

        # Handle BUSY state with queue support
        if instance.status == InstanceStatus.BUSY:
            # Try to enqueue if queue is enabled
            if instance.queue_enabled:
                future: asyncio.Future[dict[str, Any]] = asyncio.Future()
                queued_cmd = QueuedCommand(
                    request_id=request_id,
                    command=command,
                    params=params,
                    timeout_ms=timeout_ms,
                    future=future,
                )

                if instance.enqueue_command(queued_cmd):
                    logger.info(
                        f"[{request_id}] Command queued for {instance.instance_id} (queue size: {instance.queue_size})"
                    )
                    # Wait for result from queue processing
                    try:
                        result = await asyncio.wait_for(
                            future,
                            timeout=timeout_ms / 1000,
                        )
                        return result
                    except TimeoutError:
                        return ErrorMessage.from_code(
                            request_id,
                            ErrorCode.TIMEOUT,
                            f"Queued command timed out after {timeout_ms}ms",
                        ).to_dict()

                # Queue full
                return ErrorMessage.from_code(
                    request_id,
                    ErrorCode.QUEUE_FULL,
                    f"Command queue is full (max: {instance.queue_size}): {instance.instance_id}",
                ).to_dict()

            # Queue disabled - return BUSY error
            return ErrorMessage.from_code(
                request_id,
                ErrorCode.INSTANCE_BUSY,
                f"Instance is busy: {instance.instance_id}",
            ).to_dict()

        # Send command to Unity
        cmd_msg = CommandMessage(
            id=request_id,
            command=command,
            params=params,
            timeout_ms=timeout_ms,
        )

        # Create future for response
        future: asyncio.Future[dict[str, Any]] = asyncio.Future()
        self._pending_commands[request_id] = future
        logger.info(f"Registered pending command: {request_id}")

        # Set instance to BUSY
        instance.set_status(InstanceStatus.BUSY)

        try:
            await write_frame(instance.writer, cmd_msg.to_dict())

            # Wait for response
            result = await asyncio.wait_for(
                future,
                timeout=timeout_ms / 1000,
            )

            # Convert COMMAND_RESULT to RESPONSE
            return ResponseMessage(
                id=request_id,
                success=result.get("success", False),
                data=result.get("data"),
            ).to_dict()

        except TimeoutError:
            return ErrorMessage.from_code(
                request_id,
                ErrorCode.TIMEOUT,
                f"Command timed out after {timeout_ms}ms",
            ).to_dict()

        except Exception as e:
            return ErrorMessage.from_code(
                request_id,
                ErrorCode.INTERNAL_ERROR,
                str(e),
            ).to_dict()

        finally:
            # Reset instance status
            if instance.status == InstanceStatus.BUSY:
                instance.set_status(InstanceStatus.READY)

            # Cleanup pending command
            self._pending_commands.pop(request_id, None)

            # Process queued commands
            await self._process_queue(instance)


async def run_server(host: str, port: int) -> None:
    """Run the relay server with graceful shutdown"""
    server = RelayServer(host=host, port=port)

    loop = asyncio.get_event_loop()

    # Setup signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(server.stop()))

    try:
        await server.start()
    except asyncio.CancelledError:
        pass


def main() -> None:
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="Unity Bridge Relay Server")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to bind to (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Run server
    try:
        asyncio.run(run_server(args.host, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
