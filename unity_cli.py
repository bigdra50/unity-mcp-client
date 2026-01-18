#!/usr/bin/env python3
"""
Unity CLI Client Library
=========================

Python client for Unity Bridge Relay Server.
Controls Unity Editor via TCP protocol through a relay server.

Usage:
    from unity_cli import UnityClient

    client = UnityClient()

    # Console operations
    logs = client.console.get(types=["error"], count=10)
    client.console.clear()

    # Editor control
    client.editor.play()
    state = client.editor.get_state()

    # GameObject operations
    client.gameobject.create("Player", primitive_type="Cube")
    client.gameobject.modify("Player", position=[0, 5, 0])

    # Scene management
    client.scene.load(path="Assets/Scenes/MainScene.unity")
    client.scene.get_hierarchy_summary()

    # Tests (with filtering)
    client.tests.list("edit")  # List available tests
    client.tests.run("edit")   # Run all edit mode tests
    client.tests.run("edit", categories=["Unit"])  # Filter by category
    client.tests.run("edit", test_names=["MyTests.TestMethod"])  # Run specific test
    client.tests.status()      # Check running test status

    # Menu execution
    client.menu.execute("Assets/Refresh")

    # Instance management
    instances = client.list_instances()
    client.set_default_instance("/path/to/project")
"""

from __future__ import annotations

import builtins
import json
import socket
import struct
import sys
import time
import tomllib
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# =============================================================================
# Protocol Constants
# =============================================================================

PROTOCOL_VERSION = "1.0"
DEFAULT_RELAY_HOST = "127.0.0.1"
DEFAULT_RELAY_PORT = 6500
HEADER_SIZE = 4
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024  # 16 MiB
DEFAULT_TIMEOUT_MS = 30000
CONFIG_FILE_NAME = ".unity-cli.toml"


# =============================================================================
# Domain Types
# =============================================================================


@dataclass(frozen=True)
class Vector3:
    """Immutable 3D vector for position, rotation, scale"""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z]

    @classmethod
    def from_list(cls, v: list[float]) -> Vector3:
        return cls(v[0], v[1], v[2]) if len(v) >= 3 else cls()


@dataclass(frozen=True)
class Color:
    """Immutable RGBA color"""

    r: float = 1.0
    g: float = 1.0
    b: float = 1.0
    a: float = 1.0

    def to_list(self) -> list[float]:
        return [self.r, self.g, self.b, self.a]

    @classmethod
    def from_list(cls, v: list[float]) -> Color:
        if len(v) >= 4:
            return cls(v[0], v[1], v[2], v[3])
        if len(v) >= 3:
            return cls(v[0], v[1], v[2])
        return cls()


# =============================================================================
# Options Classes
# =============================================================================


@dataclass(frozen=True)
class PaginationOptions:
    """Reusable pagination settings"""

    page_size: int = 50
    cursor: int | str | None = None
    max_nodes: int | None = None


@dataclass(frozen=True)
class TestFilterOptions:
    """Test filtering options.

    When multiple filters are specified, they combine with AND logic.
    Tests must match ALL specified filters to be included.

    Args:
        test_names: Full test names (exact match, e.g., "MyNamespace.MyTests.TestMethod")
        group_names: Regex patterns for test names
        category_names: NUnit category names ([Category] attribute)
        assembly_names: Assembly names to filter by
    """

    test_names: Sequence[str] | None = None
    group_names: Sequence[str] | None = None
    category_names: Sequence[str] | None = None
    assembly_names: Sequence[str] | None = None


@dataclass
class UnityCLIConfig:
    """Configuration for Unity CLI Client"""

    relay_host: str = DEFAULT_RELAY_HOST
    relay_port: int = DEFAULT_RELAY_PORT
    timeout: float = 5.0
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    instance: str | None = None
    log_types: list[str] = field(default_factory=lambda: ["error", "warning"])
    log_count: int = 20
    # Retry settings
    retry_initial_ms: int = 500
    retry_max_ms: int = 8000
    retry_max_time_ms: int = 30000

    @classmethod
    def load(cls, config_path: Path | None = None) -> UnityCLIConfig:
        """Load configuration from TOML file."""
        config = cls()

        toml_path = config_path if config_path and config_path.exists() else cls._find_config_file()

        if toml_path:
            try:
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                config = cls._from_dict(data)
            except (tomllib.TOMLDecodeError, OSError):
                pass

        return config

    @classmethod
    def _find_config_file(cls) -> Path | None:
        """Find config file in current directory or Unity project root"""
        cwd = Path.cwd()

        config_in_cwd = cwd / CONFIG_FILE_NAME
        if config_in_cwd.exists():
            return config_in_cwd

        for parent in [cwd, *list(cwd.parents)]:
            if (parent / "Assets").is_dir() and (parent / "ProjectSettings").is_dir():
                config_in_project = parent / CONFIG_FILE_NAME
                if config_in_project.exists():
                    return config_in_project
                break

        return None

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> UnityCLIConfig:
        """Create config from dictionary (TOML data)"""
        return cls(
            relay_host=data.get("relay_host", DEFAULT_RELAY_HOST),
            relay_port=data.get("relay_port", DEFAULT_RELAY_PORT),
            timeout=float(data.get("timeout", 5.0)),
            timeout_ms=data.get("timeout_ms", DEFAULT_TIMEOUT_MS),
            instance=data.get("instance"),
            log_types=data.get("log_types", ["error", "warning"]),
            log_count=data.get("log_count", 20),
            retry_initial_ms=data.get("retry_initial_ms", 500),
            retry_max_ms=data.get("retry_max_ms", 8000),
            retry_max_time_ms=data.get("retry_max_time_ms", 30000),
        )

    def to_toml(self) -> str:
        """Generate TOML string from config"""
        log_types_str = ", ".join(f'"{t}"' for t in self.log_types)
        instance_str = f'"{self.instance}"' if self.instance else "# not set"
        return f'''# Unity CLI Configuration

relay_host = "{self.relay_host}"
relay_port = {self.relay_port}
timeout = {self.timeout}
timeout_ms = {self.timeout_ms}
instance = {instance_str}
log_types = [{log_types_str}]
log_count = {self.log_count}

# Retry settings (exponential backoff)
retry_initial_ms = {self.retry_initial_ms}
retry_max_ms = {self.retry_max_ms}
retry_max_time_ms = {self.retry_max_time_ms}
'''


# =============================================================================
# Exceptions
# =============================================================================


class UnityCLIError(Exception):
    """Unity CLI operation error"""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class ConnectionError(UnityCLIError):
    """Connection to relay server failed"""

    pass


class ProtocolError(UnityCLIError):
    """Protocol error"""

    pass


class InstanceError(UnityCLIError):
    """Instance-related error"""

    pass


class TimeoutError(UnityCLIError):
    """Command timeout"""

    pass


# =============================================================================
# Output Formatting (gh-style)
# =============================================================================


def filter_json_fields(data: Any, fields: list[str] | None) -> Any:
    """Filter JSON output to include only specified fields.

    Args:
        data: The data to filter (dict, list of dicts, or other)
        fields: List of field names to include. If None or empty, return all.

    Returns:
        Filtered data with only the specified fields.
    """
    if not fields:
        return data

    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in fields}
    elif isinstance(data, list):
        return [filter_json_fields(item, fields) for item in data]
    else:
        return data


def format_output(data: Any, json_fields: list[str] | None, json_mode: bool = True) -> str:
    """Format output based on --json flag.

    Args:
        data: The data to format
        json_fields: List of fields to include (from --json args)
        json_mode: Whether --json flag was provided (default: True for backward compat)

    Returns:
        Formatted string for output
    """
    filtered = filter_json_fields(data, json_fields) if json_fields else data
    return json.dumps(filtered, indent=2, ensure_ascii=False)


# =============================================================================
# Relay Connection
# =============================================================================


def _generate_client_id() -> str:
    """Generate a client ID for request tracking"""
    return str(uuid.uuid4())[:12]


def _generate_request_id(client_id: str) -> str:
    """Generate a unique request ID"""
    return f"{client_id}:{uuid.uuid4()}"


class RelayConnection:
    """Connection to Unity Bridge Relay Server.

    Uses 4-byte big-endian framing with JSON payloads.
    Each request creates a new TCP connection.
    """

    def __init__(
        self,
        host: str = DEFAULT_RELAY_HOST,
        port: int = DEFAULT_RELAY_PORT,
        timeout: float = 5.0,
        instance: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.instance = instance
        self._client_id = _generate_client_id()

    def _write_frame(self, sock: socket.socket, payload: dict[str, Any]) -> None:
        """Write framed message: 4-byte big-endian length + JSON payload"""
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        length = len(payload_bytes)

        if length > MAX_PAYLOAD_BYTES:
            raise ProtocolError(f"Payload too large: {length} > {MAX_PAYLOAD_BYTES}", "PAYLOAD_TOO_LARGE")

        header = struct.pack(">I", length)
        sock.sendall(header + payload_bytes)

    def _read_frame(self, sock: socket.socket) -> dict[str, Any]:
        """Read framed message: 4-byte header + JSON payload"""
        sock.settimeout(self.timeout)

        header = sock.recv(HEADER_SIZE)
        if len(header) != HEADER_SIZE:
            raise ProtocolError(f"Expected {HEADER_SIZE}-byte header, got {len(header)} bytes", "PROTOCOL_ERROR")

        (length,) = struct.unpack(">I", header)

        if length > MAX_PAYLOAD_BYTES:
            raise ProtocolError(f"Payload too large: {length} > {MAX_PAYLOAD_BYTES}", "PAYLOAD_TOO_LARGE")

        payload = b""
        remaining = length
        while remaining > 0:
            chunk = sock.recv(min(remaining, 4096))
            if not chunk:
                raise ProtocolError("Connection closed while reading payload", "PROTOCOL_ERROR")
            payload += chunk
            remaining -= len(chunk)

        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ProtocolError(f"Invalid JSON response: {e}", "MALFORMED_JSON") from e

    def send_request(
        self,
        command: str,
        params: dict[str, Any],
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        retry_initial_ms: int = 500,
        retry_max_ms: int = 8000,
        retry_max_time_ms: int = 30000,
    ) -> dict[str, Any]:
        """
        Send a REQUEST message to the relay server and wait for RESPONSE.

        Implements exponential backoff retry for transient errors:
        - INSTANCE_RELOADING: Unity is reloading, will retry
        - INSTANCE_BUSY: Unity is busy, will retry
        - TIMEOUT: Command timed out, will retry

        Args:
            command: Command name
            params: Command parameters
            timeout_ms: Command timeout in milliseconds
            retry_initial_ms: Initial retry interval (default: 500ms)
            retry_max_ms: Maximum retry interval (default: 8000ms)
            retry_max_time_ms: Maximum total retry time (default: 30000ms)
        """
        request_id = _generate_request_id(self._client_id)
        start_time = time.time()
        attempt = 0

        # Retryable error codes
        retryable_codes = {"INSTANCE_RELOADING", "INSTANCE_BUSY", "TIMEOUT"}

        while True:
            elapsed_ms = (time.time() - start_time) * 1000

            # Check if we've exceeded max retry time
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

                # Calculate backoff: min(initial * 2^attempt, max)
                backoff_ms = min(retry_initial_ms * (2 ** attempt), retry_max_ms)

                # Check if retry would exceed max time
                if elapsed_ms + backoff_ms >= retry_max_time_ms:
                    raise TimeoutError(
                        f"Max retry time would be exceeded for '{command}' "
                        f"(elapsed: {elapsed_ms:.0f}ms, next backoff: {backoff_ms}ms)",
                        "RETRY_TIMEOUT",
                    ) from e

                # Log retry attempt
                print(
                    f"[Retry] {error_code}: {e.message} "
                    f"(attempt {attempt + 1}, waiting {backoff_ms}ms)",
                    file=sys.stderr,
                )

                time.sleep(backoff_ms / 1000)
                attempt += 1

    def _send_request_once(
        self,
        request_id: str,
        command: str,
        params: dict[str, Any],
        timeout_ms: int,
    ) -> dict[str, Any]:
        """Send a single REQUEST message (no retry)."""
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
        """Handle RESPONSE or ERROR message from relay server."""
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
                raise UnityCLIError(f"{command} failed", "COMMAND_FAILED")
            return response.get("data", {})

        if msg_type == "INSTANCES":
            return response.get("data", {})

        raise ProtocolError(f"Unexpected response type: {msg_type}", "PROTOCOL_ERROR")

    def list_instances(self) -> list[dict[str, Any]]:
        """List all connected Unity instances."""
        request_id = _generate_request_id(self._client_id)

        message = {
            "type": "LIST_INSTANCES",
            "id": request_id,
            "ts": int(time.time() * 1000),
        }

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
            response = self._read_frame(sock)

            if response.get("type") == "INSTANCES":
                data = response.get("data", {})
                return data.get("instances", [])

            raise ProtocolError(f"Unexpected response type: {response.get('type')}", "PROTOCOL_ERROR")

        finally:
            sock.close()

    def set_default_instance(self, instance_id: str) -> bool:
        """Set the default Unity instance."""
        request_id = _generate_request_id(self._client_id)

        message = {
            "type": "SET_DEFAULT",
            "id": request_id,
            "instance": instance_id,
            "ts": int(time.time() * 1000),
        }

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
            response = self._read_frame(sock)

            if response.get("type") == "RESPONSE":
                return response.get("success", False)
            if response.get("type") == "ERROR":
                error = response.get("error", {})
                raise InstanceError(
                    error.get("message", "Failed to set default instance"),
                    error.get("code", "UNKNOWN_ERROR"),
                )

            raise ProtocolError(f"Unexpected response type: {response.get('type')}", "PROTOCOL_ERROR")

        finally:
            sock.close()


# =============================================================================
# Client-side Pagination Helper
# =============================================================================


def _client_side_paginate(
    items: list[Any],
    page_size: int,
    base_message: str,
    *,
    use_int_cursor: bool = False,
    yield_on_empty: bool = False,
) -> Iterator[dict[str, Any]]:
    """Common client-side pagination for legacy server responses."""
    total = len(items)

    if total == 0 and not yield_on_empty:
        return

    for offset in range(0, max(total, 1), page_size):
        page_items = items[offset : offset + page_size]
        has_more = offset + page_size < total

        cursor_val = offset if use_int_cursor else str(offset)
        next_cursor_val: int | str | None = None
        if has_more:
            next_cursor_val = offset + page_size if use_int_cursor else str(offset + page_size)

        yield {
            "success": True,
            "message": base_message,
            "data": {
                "items": page_items,
                "cursor": cursor_val,
                "pageSize": len(page_items),
                "next_cursor": next_cursor_val,
                "totalCount": total,
                "hasMore": has_more,
                "_client_paged": True,
            },
        }

        if not page_items:
            break


# =============================================================================
# API Classes
# =============================================================================


class ConsoleAPI:
    """Console log operations"""

    def __init__(self, conn: RelayConnection):
        self._conn = conn

    def get(
        self,
        types: list[str] | None = None,
        count: int = 100,
        format: str = "detailed",
        include_stacktrace: bool = True,
        filter_text: str | None = None,
    ) -> dict[str, Any]:
        """Get console logs"""
        params: dict[str, Any] = {"action": "read", "format": format, "include_stacktrace": include_stacktrace}
        if types:
            params["types"] = types
        if count:
            params["count"] = count
        if filter_text:
            params["filter_text"] = filter_text

        return self._conn.send_request("console", params)

    def clear(self) -> dict[str, Any]:
        """Clear console"""
        return self._conn.send_request("console", {"action": "clear"})


class EditorAPI:
    """Editor control operations"""

    def __init__(self, conn: RelayConnection):
        self._conn = conn

    def play(self) -> dict[str, Any]:
        """Enter play mode"""
        return self._conn.send_request("playmode", {"action": "enter"})

    def pause(self) -> dict[str, Any]:
        """Pause/unpause game"""
        return self._conn.send_request("playmode", {"action": "pause"})

    def unpause(self) -> dict[str, Any]:
        """Unpause game"""
        return self._conn.send_request("playmode", {"action": "unpause"})

    def stop(self) -> dict[str, Any]:
        """Exit play mode"""
        return self._conn.send_request("playmode", {"action": "exit"})

    def step(self) -> dict[str, Any]:
        """Step one frame"""
        return self._conn.send_request("playmode", {"action": "step"})

    def get_state(self) -> dict[str, Any]:
        """Get editor state"""
        return self._conn.send_request("playmode", {"action": "state"})

    def get_tags(self) -> dict[str, Any]:
        """Get all tags"""
        return self._conn.send_request("get_tags", {})

    def get_layers(self) -> dict[str, Any]:
        """Get all layers"""
        return self._conn.send_request("get_layers", {})

    def refresh(self) -> dict[str, Any]:
        """Refresh asset database (triggers recompilation)"""
        return self._conn.send_request("refresh", {})


class TestAPI:
    """Test execution operations"""

    def __init__(self, conn: RelayConnection):
        self._conn = conn

    def run(
        self,
        mode: str = "edit",
        *,
        test_names: list[str] | None = None,
        categories: list[str] | None = None,
        assemblies: list[str] | None = None,
        group_pattern: str | None = None,
        synchronous: bool = False,
    ) -> dict[str, Any]:
        """Run Unity tests with optional filtering.

        Args:
            mode: Test mode - "edit" or "play"
            test_names: Specific test names to run (e.g., "MyTests.TestMethod")
            categories: Test categories to run
            assemblies: Assembly names to run tests from
            group_pattern: Regex pattern for test names/namespaces
            synchronous: Run synchronously (EditMode only)
        """
        params: dict[str, Any] = {"action": "run", "mode": mode}

        if test_names:
            params["testNames"] = test_names
        if categories:
            params["categories"] = categories
        if assemblies:
            params["assemblies"] = assemblies
        if group_pattern:
            params["groupPattern"] = group_pattern
        if synchronous:
            params["synchronous"] = synchronous

        return self._conn.send_request("tests", params)

    def list(self, mode: str = "edit") -> dict[str, Any]:
        """List available tests.

        Args:
            mode: Test mode - "edit" or "play"
        """
        return self._conn.send_request("tests", {"action": "list", "mode": mode})

    def status(self) -> dict[str, Any]:
        """Get status of running tests."""
        return self._conn.send_request("tests", {"action": "status"})


class MenuAPI:
    """Menu operations"""

    def __init__(self, conn: RelayConnection):
        self._conn = conn

    def execute(self, menu_path: str) -> dict[str, Any]:
        """Execute Unity menu item"""
        return self._conn.send_request("execute_menu_item", {"menu_path": menu_path})


class GameObjectAPI:
    """GameObject operations via 'gameobject' tool"""

    def __init__(self, conn: RelayConnection):
        self._conn = conn

    def find(
        self,
        name: str | None = None,
        instance_id: int | None = None,
    ) -> dict[str, Any]:
        """Find GameObject(s) by name or instance ID"""
        params: dict[str, Any] = {"action": "find"}
        if name:
            params["name"] = name
        if instance_id is not None:
            params["id"] = instance_id
        return self._conn.send_request("gameobject", params)

    def create(
        self,
        name: str,
        primitive_type: str | None = None,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> dict[str, Any]:
        """Create GameObject"""
        params: dict[str, Any] = {"action": "create", "name": name}
        if primitive_type:
            params["primitive"] = primitive_type
        if position:
            params["position"] = position
        if rotation:
            params["rotation"] = rotation
        if scale:
            params["scale"] = scale
        return self._conn.send_request("gameobject", params)

    def modify(
        self,
        name: str | None = None,
        instance_id: int | None = None,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> dict[str, Any]:
        """Modify GameObject transform"""
        params: dict[str, Any] = {"action": "modify"}
        if name:
            params["name"] = name
        if instance_id is not None:
            params["id"] = instance_id
        if position:
            params["position"] = position
        if rotation:
            params["rotation"] = rotation
        if scale:
            params["scale"] = scale
        return self._conn.send_request("gameobject", params)

    def delete(
        self,
        name: str | None = None,
        instance_id: int | None = None,
    ) -> dict[str, Any]:
        """Delete GameObject"""
        params: dict[str, Any] = {"action": "delete"}
        if name:
            params["name"] = name
        if instance_id is not None:
            params["id"] = instance_id
        return self._conn.send_request("gameobject", params)


class SceneAPI:
    """Scene management operations via 'scene' tool"""

    def __init__(self, conn: RelayConnection):
        self._conn = conn

    def get_active(self) -> dict[str, Any]:
        """Get active scene info"""
        return self._conn.send_request("scene", {"action": "active"})

    def get_hierarchy(
        self,
        depth: int = 1,
        page_size: int = 50,
        cursor: int = 0,
    ) -> dict[str, Any]:
        """Get scene hierarchy"""
        return self._conn.send_request(
            "scene",
            {
                "action": "hierarchy",
                "depth": depth,
                "page_size": page_size,
                "cursor": cursor,
            },
        )

    def load(
        self,
        name: str | None = None,
        path: str | None = None,
        additive: bool = False,
    ) -> dict[str, Any]:
        """Load scene"""
        params: dict[str, Any] = {"action": "load", "additive": additive}
        if name:
            params["name"] = name
        if path:
            params["path"] = path
        return self._conn.send_request("scene", params)

    def save(self, path: str | None = None) -> dict[str, Any]:
        """Save current scene"""
        params: dict[str, Any] = {"action": "save"}
        if path:
            params["path"] = path
        return self._conn.send_request("scene", params)


class ComponentAPI:
    """Component operations via 'component' tool"""

    def __init__(self, conn: RelayConnection):
        self._conn = conn

    def list(
        self,
        target: str | None = None,
        target_id: int | None = None,
    ) -> dict[str, Any]:
        """List components on a GameObject"""
        params: dict[str, Any] = {"action": "list"}
        if target:
            params["target"] = target
        if target_id is not None:
            params["targetId"] = target_id
        return self._conn.send_request("component", params)

    def inspect(
        self,
        component_type: str,
        target: str | None = None,
        target_id: int | None = None,
    ) -> dict[str, Any]:
        """Inspect component properties"""
        params: dict[str, Any] = {"action": "inspect", "type": component_type}
        if target:
            params["target"] = target
        if target_id is not None:
            params["targetId"] = target_id
        return self._conn.send_request("component", params)


class MaterialAPI:
    """Material management operations"""

    def __init__(self, conn: RelayConnection):
        self._conn = conn

    def create(
        self,
        material_path: str,
        shader: str = "Standard",
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create material"""
        params: dict[str, Any] = {
            "action": "create",
            "materialPath": material_path,
            "shader": shader,
        }
        if properties:
            params["properties"] = properties

        return self._conn.send_request("manage_material", params)

    def set_color(self, material_path: str, color: list[float], property: str = "_BaseColor") -> dict[str, Any]:
        """Set material color"""
        return self._conn.send_request(
            "manage_material",
            {"action": "set_color", "materialPath": material_path, "color": color, "property": property},
        )

    def get_info(self, material_path: str) -> dict[str, Any]:
        """Get material info"""
        return self._conn.send_request("manage_material", {"action": "get_info", "materialPath": material_path})


# =============================================================================
# Main Client
# =============================================================================


class UnityClient:
    """Unity CLI Client with all APIs.

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
    """

    def __init__(
        self,
        relay_host: str = DEFAULT_RELAY_HOST,
        relay_port: int = DEFAULT_RELAY_PORT,
        timeout: float = 5.0,
        instance: str | None = None,
    ) -> None:
        self._conn = RelayConnection(
            host=relay_host,
            port=relay_port,
            timeout=timeout,
            instance=instance,
        )

        # API objects
        self.console = ConsoleAPI(self._conn)
        self.editor = EditorAPI(self._conn)
        self.gameobject = GameObjectAPI(self._conn)
        self.scene = SceneAPI(self._conn)
        self.component = ComponentAPI(self._conn)
        self.material = MaterialAPI(self._conn)
        self.tests = TestAPI(self._conn)
        self.menu = MenuAPI(self._conn)

    def list_instances(self) -> list[dict[str, Any]]:
        """List all connected Unity instances."""
        return self._conn.list_instances()

    def set_default_instance(self, instance_id: str) -> bool:
        """Set the default Unity instance."""
        return self._conn.set_default_instance(instance_id)


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> None:
    """CLI entry point for unity-cli command"""
    import argparse

    config = UnityCLIConfig.load()

    parser = argparse.ArgumentParser(
        description="Unity CLI - Control Unity Editor via Relay Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available commands:
  instances               List connected Unity instances
  state                   Get editor state
  play                    Enter play mode
  stop                    Exit play mode
  pause                   Pause play mode
  console                 Get console logs
  clear                   Clear console
  refresh                 Refresh asset database (trigger recompilation)
  tests <action> [args]   Test commands:
                            run [mode]     - Run tests (edit|play)
                            list [mode]    - List available tests
                            status         - Check running test status
  scene <action> [args]   Scene commands:
                            active         - Get active scene info
                            hierarchy      - Get scene hierarchy
                            load           - Load a scene
                            save           - Save current scene
  gameobject <action>     GameObject commands:
                            find           - Find GameObjects by name
                            create         - Create a new GameObject
                            modify         - Modify transform
                            delete         - Delete a GameObject
  component <action>      Component commands:
                            list           - List components on a GameObject
                            inspect        - Inspect component properties
  config                  Show current configuration
  config init             Generate default .unity-cli.toml

Test filtering options (for 'tests run'):
  --test-names NAME [NAME ...]     Run specific tests by full name
  --categories CAT [CAT ...]       Filter by test categories
  --assemblies ASM [ASM ...]       Filter by assembly names
  --group-pattern REGEX            Filter by regex pattern
  --sync                           Run synchronously (EditMode only)

Examples:
  %(prog)s instances
  %(prog)s state
  %(prog)s play --instance /path/to/project
  %(prog)s console --types error --count 50
  %(prog)s tests run edit
  %(prog)s tests run edit --test-names "MyTests.TestMethod"
  %(prog)s scene active
  %(prog)s scene hierarchy --depth 2
  %(prog)s gameobject find --name "Player"
  %(prog)s gameobject create --name "Cube" --primitive Cube
  %(prog)s component list --target "Player"
  %(prog)s component inspect --target "Player" --type "Rigidbody"

  # JSON output with field filtering (gh-style)
  %(prog)s scene hierarchy --json name instanceID
  %(prog)s scene hierarchy --json name instanceID | jq '.[].name'
        """,
    )
    parser.add_argument("command", help="Command to execute")
    parser.add_argument("args", nargs="*", help="Command arguments")
    parser.add_argument("--relay-host", default=None, help=f"Relay server host (default: {config.relay_host})")
    parser.add_argument("--relay-port", type=int, default=None, help=f"Relay server port (default: {config.relay_port})")
    parser.add_argument("--instance", default=None, help="Target Unity instance (project path)")
    parser.add_argument("--timeout", type=float, default=None, help=f"Timeout in seconds (default: {config.timeout})")
    parser.add_argument("--count", type=int, default=None, help=f"Number of logs (default: {config.log_count})")
    parser.add_argument("--types", nargs="+", default=None, help=f"Log types (default: {' '.join(config.log_types)})")
    parser.add_argument("--output", "-o", default=None, help="Output path for config init")
    parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing config")
    # Test filtering options
    parser.add_argument("--test-names", nargs="+", default=None, help="Run specific tests by full name")
    parser.add_argument("--categories", nargs="+", default=None, help="Filter by test categories")
    parser.add_argument("--assemblies", nargs="+", default=None, help="Filter by assembly names")
    parser.add_argument("--group-pattern", default=None, help="Filter by regex pattern")
    parser.add_argument("--sync", action="store_true", help="Run tests synchronously (EditMode only)")
    # Scene/GameObject/Component options
    parser.add_argument("--name", default=None, help="Name for find/create/modify/delete")
    parser.add_argument("--id", type=int, default=None, help="Instance ID for targeting specific objects")
    parser.add_argument("--target", default=None, help="Target GameObject name (for component commands)")
    parser.add_argument("--target-id", type=int, default=None, help="Target GameObject instance ID")
    parser.add_argument("--depth", type=int, default=1, help="Hierarchy depth (default: 1)")
    parser.add_argument("--page-size", type=int, default=50, help="Page size for hierarchy (default: 50)")
    parser.add_argument("--cursor", type=int, default=0, help="Cursor for pagination")
    parser.add_argument("--path", default=None, help="Scene path for load/save")
    parser.add_argument("--primitive", default=None, help="Primitive type (Cube, Sphere, etc.)")
    parser.add_argument("--position", nargs=3, type=float, default=None, metavar=("X", "Y", "Z"), help="Position")
    parser.add_argument("--rotation", nargs=3, type=float, default=None, metavar=("X", "Y", "Z"), help="Rotation")
    parser.add_argument("--scale", nargs=3, type=float, default=None, metavar=("X", "Y", "Z"), help="Scale")
    parser.add_argument("--type", default=None, dest="component_type", help="Component type name for inspect")
    parser.add_argument("--additive", action="store_true", help="Load scene additively")
    # Output formatting (gh-style)
    parser.add_argument(
        "--json",
        nargs="*",
        metavar="FIELD",
        help="Output JSON with specified fields (e.g., --json name instanceID). Empty for all fields.",
    )

    args = parser.parse_args()

    relay_host = args.relay_host or config.relay_host
    relay_port = args.relay_port or config.relay_port
    timeout = args.timeout or config.timeout
    instance = args.instance or config.instance
    log_types = args.types or config.log_types
    log_count = args.count or config.log_count

    # --json flag handling: None means not specified, [] means --json without fields
    json_mode = args.json is not None
    json_fields = args.json if args.json else None

    client = UnityClient(
        relay_host=relay_host,
        relay_port=relay_port,
        timeout=timeout,
        instance=instance,
    )

    try:
        if args.command == "config":
            if args.args and args.args[0] == "init":
                output_path = Path(args.output) if args.output else Path(CONFIG_FILE_NAME)

                if output_path.exists() and not args.force:
                    print(f"Error: {output_path} already exists. Use --force to overwrite.")
                    sys.exit(1)

                default_config = UnityCLIConfig()
                output_path.write_text(default_config.to_toml())
                print(f"Created {output_path}")
            else:
                config_file = UnityCLIConfig._find_config_file()
                print("=== Unity CLI Configuration ===")
                print(f"Config file: {config_file or 'Not found (using defaults)'}")
                print(f"Relay host: {relay_host}")
                print(f"Relay port: {relay_port}")
                print(f"Timeout: {timeout}s")
                print(f"Instance: {instance or '(default)'}")
                print(f"Log types: {', '.join(log_types)}")
                print(f"Log count: {log_count}")

        elif args.command == "instances":
            instances = client.list_instances()
            if json_mode:
                print(format_output(instances, json_fields, json_mode))
            elif not instances:
                print("No Unity instances connected")
            else:
                print(f"Connected instances ({len(instances)}):")
                for inst in instances:
                    default_marker = " (default)" if inst.get("is_default") else ""
                    print(f"  {inst['instance_id']}{default_marker}")
                    print(f"    Project: {inst.get('project_name', 'Unknown')}")
                    print(f"    Unity: {inst.get('unity_version', 'Unknown')}")
                    print(f"    Status: {inst.get('status', 'unknown')}")

        elif args.command == "state":
            result = client.editor.get_state()
            print(format_output(result, json_fields, json_mode))

        elif args.command == "play":
            client.editor.play()
            print("Entered play mode")

        elif args.command == "stop":
            client.editor.stop()
            print("Exited play mode")

        elif args.command == "pause":
            client.editor.pause()
            print("Toggled pause")

        elif args.command == "console":
            result = client.console.get(types=log_types, count=log_count)
            print(format_output(result, json_fields, json_mode))

        elif args.command == "clear":
            client.console.clear()
            print("Console cleared")

        elif args.command == "refresh":
            client.editor.refresh()
            print("Asset database refreshed")

        elif args.command == "tests":
            action = args.args[0] if args.args else "run"
            mode = args.args[1] if len(args.args) > 1 else "edit"

            if action == "run":
                result = client.tests.run(
                    mode=mode,
                    test_names=args.test_names,
                    categories=args.categories,
                    assemblies=args.assemblies,
                    group_pattern=args.group_pattern,
                    synchronous=args.sync,
                )
                print(format_output(result, json_fields, json_mode))
            elif action == "list":
                result = client.tests.list(mode=mode)
                print(format_output(result, json_fields, json_mode))
            elif action == "status":
                result = client.tests.status()
                print(format_output(result, json_fields, json_mode))
            else:
                print(f"Unknown test action: {action}")
                print("Available: run, list, status")
                sys.exit(1)

        elif args.command == "scene":
            action = args.args[0] if args.args else "active"

            if action == "active":
                result = client.scene.get_active()
                print(format_output(result, json_fields, json_mode))
            elif action == "hierarchy":
                result = client.scene.get_hierarchy(
                    depth=args.depth,
                    page_size=args.page_size,
                    cursor=args.cursor,
                )
                # For --json with fields, output items array directly for easier jq processing
                if json_fields:
                    items = result.get("items", [])
                    print(format_output(items, json_fields, json_mode))
                else:
                    print(format_output(result, json_fields, json_mode))
            elif action == "load":
                if not args.path and not args.name:
                    print("Error: --path or --name required for scene load")
                    sys.exit(1)
                result = client.scene.load(path=args.path, name=args.name, additive=args.additive)
                print(format_output(result, json_fields, json_mode))
            elif action == "save":
                result = client.scene.save(path=args.path)
                print(format_output(result, json_fields, json_mode))
            else:
                print(f"Unknown scene action: {action}")
                print("Available: active, hierarchy, load, save")
                sys.exit(1)

        elif args.command == "gameobject":
            action = args.args[0] if args.args else "find"

            if action == "find":
                if not args.name and not args.id:
                    print("Error: --name or --id required for gameobject find")
                    sys.exit(1)
                result = client.gameobject.find(name=args.name, instance_id=args.id)
                # For --json with fields, output objects array directly
                if json_fields:
                    objects = result.get("objects", [])
                    print(format_output(objects, json_fields, json_mode))
                else:
                    print(format_output(result, json_fields, json_mode))
            elif action == "create":
                if not args.name:
                    print("Error: --name required for gameobject create")
                    sys.exit(1)
                result = client.gameobject.create(
                    name=args.name,
                    primitive_type=args.primitive,
                    position=args.position,
                    rotation=args.rotation,
                    scale=args.scale,
                )
                print(format_output(result, json_fields, json_mode))
            elif action == "modify":
                if not args.name and not args.id:
                    print("Error: --name or --id required for gameobject modify")
                    sys.exit(1)
                result = client.gameobject.modify(
                    name=args.name,
                    instance_id=args.id,
                    position=args.position,
                    rotation=args.rotation,
                    scale=args.scale,
                )
                print(format_output(result, json_fields, json_mode))
            elif action == "delete":
                if not args.name and not args.id:
                    print("Error: --name or --id required for gameobject delete")
                    sys.exit(1)
                result = client.gameobject.delete(name=args.name, instance_id=args.id)
                print(format_output(result, json_fields, json_mode))
            else:
                print(f"Unknown gameobject action: {action}")
                print("Available: find, create, modify, delete")
                sys.exit(1)

        elif args.command == "component":
            action = args.args[0] if args.args else "list"

            if action == "list":
                if not args.target and not args.target_id:
                    print("Error: --target or --target-id required for component list")
                    sys.exit(1)
                result = client.component.list(target=args.target, target_id=args.target_id)
                # For --json with fields, output components array directly
                if json_fields:
                    components = result.get("components", [])
                    print(format_output(components, json_fields, json_mode))
                else:
                    print(format_output(result, json_fields, json_mode))
            elif action == "inspect":
                if not args.target and not args.target_id:
                    print("Error: --target or --target-id required for component inspect")
                    sys.exit(1)
                if not args.component_type:
                    print("Error: --type required for component inspect")
                    sys.exit(1)
                result = client.component.inspect(
                    target=args.target,
                    target_id=args.target_id,
                    component_type=args.component_type,
                )
                print(format_output(result, json_fields, json_mode))
            else:
                print(f"Unknown component action: {action}")
                print("Available: list, inspect")
                sys.exit(1)

        else:
            print(f"Unknown command: {args.command}")
            print("Available: config, instances, state, play, stop, pause, console, clear, refresh, tests, scene, gameobject, component")
            sys.exit(1)

    except UnityCLIError as e:
        print(f"Error: {e}", file=sys.stderr)
        if e.code:
            print(f"Code: {e.code}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
