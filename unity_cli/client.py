"""
Unity CLI Client Module
========================

RelayConnection and UnityClient classes for communicating
with Unity Bridge Relay Server via TCP.

Protocol: 4-byte big-endian framing with JSON payloads.
"""

from __future__ import annotations

import builtins
import json
import socket
import struct
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from unity_cli.config import (
    DEFAULT_RELAY_HOST,
    DEFAULT_RELAY_PORT,
    DEFAULT_TIMEOUT_MS,
    HEADER_SIZE,
    MAX_PAYLOAD_BYTES,
)
from unity_cli.exceptions import (
    ConnectionError,
    InstanceError,
    ProtocolError,
    TimeoutError,
    UnityCLIError,
)

if TYPE_CHECKING:
    from unity_cli.api import (
        AssetAPI,
        ComponentAPI,
        ConsoleAPI,
        EditorAPI,
        GameObjectAPI,
        MaterialAPI,
        MenuAPI,
        PackageAPI,
        SceneAPI,
        ScreenshotAPI,
        SelectionAPI,
        TestAPI,
        UITreeAPI,
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _generate_client_id() -> str:
    """Generate a client ID for request tracking.

    Returns:
        12-character UUID prefix string.
    """
    return str(uuid.uuid4())[:12]


def _generate_request_id(client_id: str) -> str:
    """Generate a unique request ID.

    Args:
        client_id: Client identifier prefix.

    Returns:
        Request ID in format "{client_id}:{uuid}".
    """
    return f"{client_id}:{uuid.uuid4()}"


# =============================================================================
# Relay Connection
# =============================================================================


# Type alias for retry callback
RetryCallback = Callable[[str, str, int, int], None]


class RelayConnection:
    """Connection to Unity Bridge Relay Server.

    Uses 4-byte big-endian framing with JSON payloads.
    Each request creates a new TCP connection.

    Attributes:
        host: Relay server hostname.
        port: Relay server port.
        timeout: Socket timeout in seconds.
        instance: Target Unity instance path (optional).
        timeout_ms: Default command timeout in milliseconds.
        retry_initial_ms: Initial retry interval in milliseconds.
        retry_max_ms: Maximum retry interval in milliseconds.
        retry_max_time_ms: Maximum total retry time in milliseconds.
        on_retry: Optional callback for retry events.
    """

    def __init__(
        self,
        host: str = DEFAULT_RELAY_HOST,
        port: int = DEFAULT_RELAY_PORT,
        timeout: float = 5.0,
        instance: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retry_initial_ms: int = 500,
        retry_max_ms: int = 8000,
        retry_max_time_ms: int = 30000,
        on_retry: RetryCallback | None = None,
    ) -> None:
        """Initialize relay connection.

        Args:
            host: Relay server hostname (default: 127.0.0.1).
            port: Relay server port (default: 6500).
            timeout: Socket timeout in seconds (default: 5.0).
            instance: Target Unity instance path (optional).
            timeout_ms: Default command timeout in milliseconds (default: 30000).
            retry_initial_ms: Initial retry interval in milliseconds (default: 500).
            retry_max_ms: Maximum retry interval in milliseconds (default: 8000).
            retry_max_time_ms: Maximum total retry time in milliseconds (default: 30000).
            on_retry: Optional callback(code, message, attempt, backoff_ms) for retry events.
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.instance = instance
        self.timeout_ms = timeout_ms
        self.retry_initial_ms = retry_initial_ms
        self.retry_max_ms = retry_max_ms
        self.retry_max_time_ms = retry_max_time_ms
        self.on_retry = on_retry
        self._client_id = _generate_client_id()

    def _write_frame(self, sock: socket.socket, payload: dict[str, Any]) -> None:
        """Write framed message: 4-byte big-endian length + JSON payload.

        Args:
            sock: Connected socket.
            payload: Message payload dictionary.

        Raises:
            ProtocolError: If payload exceeds maximum size.
        """
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        length = len(payload_bytes)

        if length > MAX_PAYLOAD_BYTES:
            raise ProtocolError(
                f"Payload too large: {length} > {MAX_PAYLOAD_BYTES}",
                "PAYLOAD_TOO_LARGE",
            )

        header = struct.pack(">I", length)
        sock.sendall(header + payload_bytes)

    def _read_frame(self, sock: socket.socket) -> dict[str, Any]:
        """Read framed message: 4-byte header + JSON payload.

        Args:
            sock: Connected socket.

        Returns:
            Parsed JSON payload as dictionary.

        Raises:
            ProtocolError: If header is incomplete, payload too large, or invalid JSON.
        """
        sock.settimeout(self.timeout)

        header = sock.recv(HEADER_SIZE)
        if len(header) != HEADER_SIZE:
            raise ProtocolError(
                f"Expected {HEADER_SIZE}-byte header, got {len(header)} bytes",
                "PROTOCOL_ERROR",
            )

        (length,) = struct.unpack(">I", header)

        if length > MAX_PAYLOAD_BYTES:
            raise ProtocolError(
                f"Payload too large: {length} > {MAX_PAYLOAD_BYTES}",
                "PAYLOAD_TOO_LARGE",
            )

        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk_size = min(remaining, 65536)  # 64KB buffer
            chunk = sock.recv(chunk_size)
            if not chunk:
                raise ProtocolError(
                    "Connection closed while reading payload",
                    "PROTOCOL_ERROR",
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)  # O(n) concatenation

        try:
            result: dict[str, Any] = json.loads(payload.decode("utf-8"))
            return result
        except json.JSONDecodeError as e:
            raise ProtocolError(f"Invalid JSON response: {e}", "MALFORMED_JSON") from e

    def send_request(
        self,
        command: str,
        params: dict[str, Any],
        timeout_ms: int | None = None,
        retry_initial_ms: int | None = None,
        retry_max_ms: int | None = None,
        retry_max_time_ms: int | None = None,
    ) -> dict[str, Any]:
        """Send REQUEST message with exponential backoff retry.

        Implements retry for transient errors:
        - INSTANCE_RELOADING: Unity is reloading
        - INSTANCE_BUSY: Unity is processing another command
        - TIMEOUT: Command timed out

        Args:
            command: Command name.
            params: Command parameters.
            timeout_ms: Command timeout in milliseconds (default: instance setting).
            retry_initial_ms: Initial retry interval (default: instance setting).
            retry_max_ms: Maximum retry interval (default: instance setting).
            retry_max_time_ms: Maximum total retry time (default: instance setting).

        Returns:
            Response data dictionary.

        Raises:
            TimeoutError: If max retry time exceeded.
            ConnectionError: If cannot connect to relay server.
            ProtocolError: If protocol error occurs.
            InstanceError: If instance error (non-retryable).
            UnityCLIError: If command fails.
        """
        # Use instance defaults if not specified
        timeout_ms = timeout_ms if timeout_ms is not None else self.timeout_ms
        retry_initial_ms = retry_initial_ms if retry_initial_ms is not None else self.retry_initial_ms
        retry_max_ms = retry_max_ms if retry_max_ms is not None else self.retry_max_ms
        retry_max_time_ms = retry_max_time_ms if retry_max_time_ms is not None else self.retry_max_time_ms

        request_id = _generate_request_id(self._client_id)
        start_time = time.time()
        attempt = 0

        retryable_codes = {"INSTANCE_RELOADING", "INSTANCE_BUSY", "TIMEOUT"}

        while True:
            elapsed_ms = (time.time() - start_time) * 1000

            if attempt > 0 and elapsed_ms >= retry_max_time_ms:
                raise TimeoutError(
                    f"Max retry time exceeded ({retry_max_time_ms}ms) for '{command}'",
                    "RETRY_TIMEOUT",
                )

            try:
                return self._send_request_once(request_id, command, params, timeout_ms)

            except (InstanceError, TimeoutError) as e:
                error_code = getattr(e, "code", "UNKNOWN")

                if error_code not in retryable_codes:
                    raise

                backoff_ms = min(retry_initial_ms * (2**attempt), retry_max_ms)

                if elapsed_ms + backoff_ms >= retry_max_time_ms:
                    raise TimeoutError(
                        f"Max retry time would be exceeded for '{command}' "
                        f"(elapsed: {elapsed_ms:.0f}ms, next backoff: {backoff_ms}ms)",
                        "RETRY_TIMEOUT",
                    ) from e

                # Notify via callback if provided (no direct stderr output)
                if self.on_retry:
                    self.on_retry(error_code, e.message, attempt + 1, backoff_ms)

                time.sleep(backoff_ms / 1000)
                attempt += 1

    def _send_request_once(
        self,
        request_id: str,
        command: str,
        params: dict[str, Any],
        timeout_ms: int,
    ) -> dict[str, Any]:
        """Send a single REQUEST message (no retry).

        Args:
            request_id: Unique request identifier.
            command: Command name.
            params: Command parameters.
            timeout_ms: Command timeout in milliseconds.

        Returns:
            Response data dictionary.
        """
        message: dict[str, Any] = {
            "type": "REQUEST",
            "id": request_id,
            "command": command,
            "params": params,
            "timeout_ms": timeout_ms,
            "ts": int(time.time() * 1000),
        }

        if self.instance:
            message["instance"] = self.instance

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            try:
                sock.settimeout(self.timeout)
                sock.connect((self.host, self.port))
            except OSError as e:
                raise ConnectionError(
                    f"Cannot connect to Relay Server at {self.host}:{self.port}.\n"
                    "Please ensure the relay server is running:\n"
                    "  $ python -m relay.server --port 6500",
                    "CONNECTION_FAILED",
                ) from e

            self._write_frame(sock, message)

            try:
                response = self._read_frame(sock)
            except builtins.TimeoutError as e:
                raise TimeoutError(
                    f"Response timed out for '{command}' (timeout: {self.timeout}s)",
                    "TIMEOUT",
                ) from e

            return self._handle_response(response, command)

        finally:
            sock.close()

    def _handle_response(self, response: dict[str, Any], command: str) -> dict[str, Any]:
        """Handle RESPONSE or ERROR message from relay server.

        Args:
            response: Response message dictionary.
            command: Original command name (for error messages).

        Returns:
            Response data dictionary.

        Raises:
            InstanceError: For instance-related errors.
            TimeoutError: For timeout errors.
            ProtocolError: For unexpected message types.
            UnityCLIError: For other errors.
        """
        msg_type = response.get("type")

        if msg_type == "ERROR":
            error = response.get("error", {})
            code = error.get("code", "UNKNOWN_ERROR")
            message = error.get("message", "Unknown error")

            if code == "INSTANCE_NOT_FOUND":
                raise InstanceError(message, code)
            if code == "INSTANCE_RELOADING":
                raise InstanceError(message, code)
            if code == "INSTANCE_BUSY":
                raise InstanceError(message, code)
            if code == "TIMEOUT":
                raise TimeoutError(message, code)
            raise UnityCLIError(message, code)

        if msg_type == "RESPONSE":
            if not response.get("success", False):
                error_info = response.get("error", {})
                error_msg = error_info.get("message", f"{command} failed") if error_info else f"{command} failed"
                error_code = error_info.get("code", "COMMAND_FAILED") if error_info else "COMMAND_FAILED"
                raise UnityCLIError(error_msg, error_code)
            data: dict[str, Any] = response.get("data", {})
            return data

        if msg_type == "INSTANCES":
            data = response.get("data", {})
            return data

        raise ProtocolError(f"Unexpected response type: {msg_type}", "PROTOCOL_ERROR")

    def _send_admin_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send an admin message (LIST_INSTANCES, SET_DEFAULT) without retry.

        Args:
            message: Message dict to send.

        Returns:
            Response dict from relay server.

        Raises:
            ConnectionError: If cannot connect to relay server.
            ProtocolError: For protocol errors.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            try:
                sock.settimeout(self.timeout)
                sock.connect((self.host, self.port))
            except OSError as e:
                raise ConnectionError(
                    f"Cannot connect to Relay Server at {self.host}:{self.port}",
                    "CONNECTION_FAILED",
                ) from e

            self._write_frame(sock, message)
            return self._read_frame(sock)

        finally:
            sock.close()

    def list_instances(self) -> list[dict[str, Any]]:
        """List all connected Unity instances.

        Returns:
            List of instance info dictionaries with keys:
            - instance_id: Project path
            - project_name: Project name
            - unity_version: Unity version
            - status: Connection status
            - is_default: Whether this is the default instance
        """
        message = {
            "type": "LIST_INSTANCES",
            "id": _generate_request_id(self._client_id),
            "ts": int(time.time() * 1000),
        }

        response = self._send_admin_message(message)

        if response.get("type") == "INSTANCES":
            data: dict[str, Any] = response.get("data", {})
            instances: list[dict[str, Any]] = data.get("instances", [])
            return instances

        raise ProtocolError(
            f"Unexpected response type: {response.get('type')}",
            "PROTOCOL_ERROR",
        )

    def set_default_instance(self, instance_id: str) -> bool:
        """Set the default Unity instance.

        Args:
            instance_id: Project path to set as default.

        Returns:
            True if successfully set.

        Raises:
            InstanceError: If instance not found.
            ConnectionError: If cannot connect to relay server.
            ProtocolError: For unexpected message types.
        """
        message = {
            "type": "SET_DEFAULT",
            "id": _generate_request_id(self._client_id),
            "instance": instance_id,
            "ts": int(time.time() * 1000),
        }

        response = self._send_admin_message(message)

        if response.get("type") == "RESPONSE":
            success: bool = response.get("success", False)
            return success
        if response.get("type") == "ERROR":
            error: dict[str, str] = response.get("error", {})
            raise InstanceError(
                error.get("message", "Failed to set default instance"),
                error.get("code", "UNKNOWN_ERROR"),
            )

        raise ProtocolError(
            f"Unexpected response type: {response.get('type')}",
            "PROTOCOL_ERROR",
        )


# =============================================================================
# Unity Client
# =============================================================================


class UnityClient:
    """Unity CLI Client with all APIs.

    Provides access to Unity Editor functionality via relay server.
    APIs are lazily imported to avoid circular dependencies.

    Usage:
        client = UnityClient()

        # Check connected instances
        instances = client.list_instances()

        # Use specific instance
        client = UnityClient(instance="/path/to/project")

        # Console
        client.console.get(types=["error"], count=10)

        # Editor
        client.editor.play()
        client.editor.stop()

        # GameObject
        client.gameobject.create("Player", primitive_type="Cube")

        # Scene
        client.scene.load(path="Assets/Scenes/Main.unity")

    Attributes:
        console: Console log operations.
        editor: Editor control (play/pause/stop).
        gameobject: GameObject CRUD operations.
        scene: Scene management.
        component: Component inspection.
        material: Material management.
        tests: Test execution.
        menu: Menu item execution.
    """

    def __init__(
        self,
        relay_host: str = DEFAULT_RELAY_HOST,
        relay_port: int = DEFAULT_RELAY_PORT,
        timeout: float = 5.0,
        instance: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retry_initial_ms: int = 500,
        retry_max_ms: int = 8000,
        retry_max_time_ms: int = 30000,
        on_retry: RetryCallback | None = None,
    ) -> None:
        """Initialize Unity client.

        Args:
            relay_host: Relay server hostname (default: 127.0.0.1).
            relay_port: Relay server port (default: 6500).
            timeout: Socket timeout in seconds (default: 5.0).
            instance: Target Unity instance path (optional).
            timeout_ms: Default command timeout in milliseconds (default: 30000).
            retry_initial_ms: Initial retry interval in milliseconds (default: 500).
            retry_max_ms: Maximum retry interval in milliseconds (default: 8000).
            retry_max_time_ms: Maximum total retry time in milliseconds (default: 30000).
            on_retry: Optional callback(code, message, attempt, backoff_ms) for retry events.
        """
        self._conn = RelayConnection(
            host=relay_host,
            port=relay_port,
            timeout=timeout,
            instance=instance,
            timeout_ms=timeout_ms,
            retry_initial_ms=retry_initial_ms,
            retry_max_ms=retry_max_ms,
            retry_max_time_ms=retry_max_time_ms,
            on_retry=on_retry,
        )

        # Lazy import to avoid circular dependencies
        from unity_cli.api import (
            AssetAPI,
            ComponentAPI,
            ConsoleAPI,
            EditorAPI,
            GameObjectAPI,
            MaterialAPI,
            MenuAPI,
            PackageAPI,
            SceneAPI,
            ScreenshotAPI,
            SelectionAPI,
            TestAPI,
            UITreeAPI,
        )

        # API objects
        self.asset: AssetAPI = AssetAPI(self._conn)
        self.console: ConsoleAPI = ConsoleAPI(self._conn)
        self.editor: EditorAPI = EditorAPI(self._conn)
        self.gameobject: GameObjectAPI = GameObjectAPI(self._conn)
        self.scene: SceneAPI = SceneAPI(self._conn)
        self.component: ComponentAPI = ComponentAPI(self._conn)
        self.material: MaterialAPI = MaterialAPI(self._conn)
        self.package: PackageAPI = PackageAPI(self._conn)
        self.tests: TestAPI = TestAPI(self._conn)
        self.menu: MenuAPI = MenuAPI(self._conn)
        self.selection: SelectionAPI = SelectionAPI(self._conn)
        self.screenshot: ScreenshotAPI = ScreenshotAPI(self._conn)
        self.uitree: UITreeAPI = UITreeAPI(self._conn)

    def list_instances(self) -> list[dict[str, Any]]:
        """List all connected Unity instances.

        Returns:
            List of instance info dictionaries.
        """
        return self._conn.list_instances()

    def set_default_instance(self, instance_id: str) -> bool:
        """Set the default Unity instance.

        Args:
            instance_id: Project path to set as default.

        Returns:
            True if successfully set.
        """
        return self._conn.set_default_instance(instance_id)
