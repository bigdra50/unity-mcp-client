#!/usr/bin/env python3
"""
Unity MCP Client Library
=========================

Complete Python client for Unity MCP TCP protocol.
Supports all tools via dedicated API classes.

Usage:
    from unity_mcp_client import UnityMCPClient, TestFilterOptions

    client = UnityMCPClient()

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
    client.tests.run("edit")
    client.tests.run("edit", filter_options=TestFilterOptions(category_names=["Unit"]))

    # Menu execution
    client.menu.execute("Assets/Refresh")

    # Script/Shader/Prefab
    client.script.create("MyScript", namespace="MyGame")
    client.shader.create("MyShader")
    client.prefab.create("MyPrefab", source_object="Player")

    # Batch execution
    result = client.batch.execute([
        {"tool": "read_console", "params": {"action": "clear"}},
        {"tool": "manage_editor", "params": {"action": "play"}},
    ], fail_fast=True)
"""

import json
import socket
import struct
import subprocess
import sys
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILE_NAME = ".unity-mcp.toml"


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
    def from_list(cls, v: list[float]) -> "Vector3":
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
    def from_list(cls, v: list[float]) -> "Color":
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
class UnityMCPConfig:
    """Configuration for Unity MCP Client"""

    port: int = 6400
    host: str = "localhost"
    timeout: float = 5.0
    connection_timeout: float = 30.0
    retry: int = 3
    log_types: list[str] = field(default_factory=lambda: ["error", "warning"])
    log_count: int = 20

    @classmethod
    def load(cls, config_path: Path | None = None) -> "UnityMCPConfig":
        """
        Load configuration from TOML file.

        Search order:
        1. Explicit config_path if provided
        2. .unity-mcp.toml in current directory
        3. .unity-mcp.toml in Unity project root (parent of Assets/)
        4. Default values + EditorPrefs port detection
        """
        config = cls()

        # Find config file
        toml_path = config_path if config_path and config_path.exists() else cls._find_config_file()

        # Load from TOML if found
        if toml_path:
            try:
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                config = cls._from_dict(data)
            except (tomllib.TOMLDecodeError, OSError):
                pass  # Fall back to defaults

        # If port not set in config, try EditorPrefs
        if config.port == 6400:
            detected = _detect_port_from_editor_prefs()
            if detected:
                config.port = detected

        return config

    @classmethod
    def _find_config_file(cls) -> Path | None:
        """Find config file in current directory or Unity project root"""
        cwd = Path.cwd()

        # Check current directory
        config_in_cwd = cwd / CONFIG_FILE_NAME
        if config_in_cwd.exists():
            return config_in_cwd

        # Check if we're in a Unity project (has Assets/ directory)
        # and look for config in project root
        for parent in [cwd] + list(cwd.parents):
            if (parent / "Assets").is_dir() and (parent / "ProjectSettings").is_dir():
                config_in_project = parent / CONFIG_FILE_NAME
                if config_in_project.exists():
                    return config_in_project
                break  # Found Unity project but no config

        return None

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "UnityMCPConfig":
        """Create config from dictionary (TOML data)"""
        return cls(
            port=data.get("port", 6400),
            host=data.get("host", "localhost"),
            timeout=float(data.get("timeout", 5.0)),
            connection_timeout=float(data.get("connection_timeout", 30.0)),
            retry=data.get("retry", 3),
            log_types=data.get("log_types", ["error", "warning"]),
            log_count=data.get("log_count", 20),
        )

    def to_toml(self) -> str:
        """Generate TOML string from config"""
        log_types_str = ", ".join(f'"{t}"' for t in self.log_types)
        return f'''# Unity MCP Client Configuration

port = {self.port}
host = "{self.host}"
timeout = {self.timeout}
connection_timeout = {self.connection_timeout}
retry = {self.retry}
log_types = [{log_types_str}]
log_count = {self.log_count}
'''


def _detect_port_from_editor_prefs() -> int | None:
    """
    Detect Unity MCP port from EditorPrefs (macOS only).

    Returns the port from Unity EditorPrefs if available,
    otherwise returns None.
    """
    if sys.platform != "darwin":
        return None

    try:
        result = subprocess.run(
            ["defaults", "read", "com.unity3d.UnityEditor5.x", "MCPForUnity.UnitySocketPort"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass

    return None


def detect_port() -> int:
    """
    Detect Unity MCP port.

    Search order:
    1. .unity-mcp.toml in current directory or Unity project root
    2. EditorPrefs (macOS only)
    3. Default port 6400
    """
    config = UnityMCPConfig.load()
    return config.port


class UnityMCPError(Exception):
    """Unity MCP operation error"""

    pass


class UnityMCPConnection:
    """Low-level Unity MCP connection handler"""

    def __init__(self, host="localhost", port=6400, timeout=5.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _write_frame(self, sock, payload_bytes: bytes):
        """Write framed message: 8-byte big-endian length + payload"""
        length = len(payload_bytes)
        header = struct.pack(">Q", length)
        sock.sendall(header + payload_bytes)

    def _read_frame(self, sock) -> str:
        """Read framed message: 8-byte header + payload"""
        sock.settimeout(self.timeout)

        # Read 8-byte header
        header = sock.recv(8)
        if len(header) != 8:
            raise UnityMCPError(f"Expected 8-byte header, got {len(header)} bytes")

        # Parse length (big-endian)
        length = struct.unpack(">Q", header)[0]

        # Read payload
        payload = b""
        remaining = length
        while remaining > 0:
            chunk = sock.recv(min(remaining, 4096))
            if not chunk:
                raise UnityMCPError("Connection closed while reading payload")
            payload += chunk
            remaining -= len(chunk)

        return payload.decode("utf-8")

    def send_command(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send command and return response"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            try:
                sock.connect((self.host, self.port))
            except ConnectionRefusedError as e:
                raise UnityMCPError(
                    f"Cannot connect to Unity Editor at {self.host}:{self.port}.\n"
                    "Please ensure:\n"
                    "  1. Unity Editor is open\n"
                    "  2. MCP For Unity bridge is running (Window > MCP For Unity)"
                ) from e
            except TimeoutError as e:
                raise UnityMCPError(
                    f"Connection timed out to {self.host}:{self.port} (timeout: {self.timeout}s).\n"
                    "Please ensure Unity Editor is responsive."
                ) from e

            # Read WELCOME
            try:
                welcome = sock.recv(1024).decode("utf-8")
            except TimeoutError as e:
                raise UnityMCPError(
                    f"Handshake timed out (timeout: {self.timeout}s).\nUnity Editor may be busy or unresponsive."
                ) from e
            if "WELCOME UNITY-MCP" not in welcome:
                raise UnityMCPError(f"Invalid handshake: {welcome}")

            # Build message
            message = {"type": tool_name, "params": params}

            # Send framed request
            payload = json.dumps(message).encode("utf-8")
            self._write_frame(sock, payload)

            # Read framed response
            try:
                response_text = self._read_frame(sock)
            except TimeoutError as e:
                raise UnityMCPError(
                    f"Response timed out for '{tool_name}' (timeout: {self.timeout}s).\n"
                    "The operation may still be running in Unity.\n"
                    "Try increasing --connection-timeout for long operations."
                ) from e
            response = json.loads(response_text)

            # Check status (support both old 'status' and new 'success' fields)
            if response.get("status") == "error":
                raise UnityMCPError(f"{tool_name} failed: {response.get('error', 'Unknown error')}")

            if response.get("success") is False:
                raise UnityMCPError(f"{tool_name} failed: {response.get('message', 'Unknown error')}")

            return response.get("result", response)

        finally:
            sock.close()

    def read_resource(self, resource_name: str, params: dict[str, Any] = None) -> dict[str, Any]:
        """Read resource and return response (uses same protocol as Tools)"""
        if params is None:
            params = {}
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            try:
                sock.connect((self.host, self.port))
            except ConnectionRefusedError as e:
                raise UnityMCPError(
                    f"Cannot connect to Unity Editor at {self.host}:{self.port}.\n"
                    "Please ensure:\n"
                    "  1. Unity Editor is open\n"
                    "  2. MCP For Unity bridge is running (Window > MCP For Unity)"
                ) from e
            except TimeoutError as e:
                raise UnityMCPError(
                    f"Connection timed out to {self.host}:{self.port} (timeout: {self.timeout}s).\n"
                    "Please ensure Unity Editor is responsive."
                ) from e

            # Read WELCOME
            try:
                welcome = sock.recv(1024).decode("utf-8")
            except TimeoutError as e:
                raise UnityMCPError(
                    f"Handshake timed out (timeout: {self.timeout}s).\nUnity Editor may be busy or unresponsive."
                ) from e
            if "WELCOME UNITY-MCP" not in welcome:
                raise UnityMCPError(f"Invalid handshake: {welcome}")

            # Build message - Resources use same format as Tools
            message = {"type": resource_name, "params": params}

            # Send framed request
            payload = json.dumps(message).encode("utf-8")
            self._write_frame(sock, payload)

            # Read framed response
            try:
                response_text = self._read_frame(sock)
            except TimeoutError as e:
                raise UnityMCPError(
                    f"Response timed out for resource '{resource_name}' (timeout: {self.timeout}s).\n"
                    "Unity Editor may be busy or unresponsive."
                ) from e
            response = json.loads(response_text)

            # Check status (support both old 'status' and new 'success' fields)
            if response.get("status") == "error":
                raise UnityMCPError(f"Resource {resource_name} failed: {response.get('error', 'Unknown error')}")

            if response.get("success") is False:
                raise UnityMCPError(f"Resource {resource_name} failed: {response.get('message', 'Unknown error')}")

            return response.get("result", response)

        finally:
            sock.close()


def _client_side_paginate(
    items: list[Any],
    page_size: int,
    base_message: str,
    *,
    use_int_cursor: bool = False,
    yield_on_empty: bool = False,
) -> Iterator[dict[str, Any]]:
    """
    Common client-side pagination for legacy server responses.

    Args:
        items: Flat list of items to paginate
        page_size: Items per page
        base_message: Message from original response
        use_int_cursor: Use int cursor (hierarchy) vs str cursor (find)
        yield_on_empty: Yield one page even if items is empty

    Yields:
        Paginated response dicts with consistent structure
    """
    total = len(items)

    # Handle empty case consistently
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


class ConsoleAPI:
    """Console log operations"""

    def __init__(self, conn: UnityMCPConnection):
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
        params = {"action": "get", "format": format, "include_stacktrace": include_stacktrace}
        if types:
            params["types"] = types
        if count:
            params["count"] = count
        if filter_text:
            params["filter_text"] = filter_text

        return self._conn.send_command("read_console", params)

    def clear(self) -> dict[str, Any]:
        """Clear console"""
        return self._conn.send_command("read_console", {"action": "clear"})


class EditorAPI:
    """Editor control operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def play(self) -> dict[str, Any]:
        """Enter play mode"""
        return self._conn.send_command("manage_editor", {"action": "play"})

    def pause(self) -> dict[str, Any]:
        """Pause/unpause game"""
        return self._conn.send_command("manage_editor", {"action": "pause"})

    def stop(self) -> dict[str, Any]:
        """Exit play mode"""
        return self._conn.send_command("manage_editor", {"action": "stop"})

    def get_state(self) -> dict[str, Any]:
        """Get editor state via Resource API"""
        return self._conn.read_resource("get_editor_state")

    def get_project_root(self) -> str:
        """Get project root path via Resource API"""
        result = self._conn.read_resource("get_project_info")
        data = result.get("data", {})
        return data.get("projectRoot", "")

    def add_tag(self, tag_name: str) -> dict[str, Any]:
        """Add tag"""
        return self._conn.send_command("manage_editor", {"action": "add_tag", "tagName": tag_name})

    def remove_tag(self, tag_name: str) -> dict[str, Any]:
        """Remove tag"""
        return self._conn.send_command("manage_editor", {"action": "remove_tag", "tagName": tag_name})

    def get_tags(self) -> dict[str, Any]:
        """Get all tags via Resource API"""
        return self._conn.read_resource("get_tags")

    def get_layers(self) -> dict[str, Any]:
        """Get all layers via Resource API"""
        return self._conn.read_resource("get_layers")


class TestAPI:
    """Test execution operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def run(
        self,
        mode: str = "edit",
        timeout_seconds: int = 600,
        *,
        filter_options: TestFilterOptions | None = None,
    ) -> dict[str, Any]:
        """
        Run Unity tests with optional filtering.

        Args:
            mode: Test mode ("edit" or "play")
            timeout_seconds: Maximum test run duration
            filter_options: Optional TestFilterOptions for filtering tests

        Note:
            When multiple filters are specified in filter_options,
            they combine with AND logic.
        """
        params: dict[str, Any] = {"mode": mode, "timeoutSeconds": timeout_seconds}

        if filter_options:
            if filter_options.test_names:
                params["testNames"] = list(filter_options.test_names)
            if filter_options.group_names:
                params["groupNames"] = list(filter_options.group_names)
            if filter_options.category_names:
                params["categoryNames"] = list(filter_options.category_names)
            if filter_options.assembly_names:
                params["assemblyNames"] = list(filter_options.assembly_names)

        return self._conn.send_command("run_tests", params)


class MenuAPI:
    """Menu operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def execute(self, menu_path: str) -> dict[str, Any]:
        """Execute Unity menu item"""
        return self._conn.send_command("execute_menu_item", {"menu_path": menu_path})


class ScriptAPI:
    """C# script operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(
        self,
        name: str,
        path: str = "Scripts",
        template: str | None = None,
        namespace: str | None = None,
        base_class: str | None = None,
        interfaces: list[str] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create a new C# script"""
        params: dict[str, Any] = {"action": "create", "name": name, "path": path}
        if template:
            params["template"] = template
        if namespace:
            params["namespace"] = namespace
        if base_class:
            params["baseClass"] = base_class
        if interfaces:
            params["interfaces"] = interfaces
        params.update(kwargs)
        return self._conn.send_command("manage_script", params)

    def modify(
        self,
        name: str,
        path: str = "Scripts",
        content: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Modify an existing C# script"""
        params: dict[str, Any] = {"action": "modify", "name": name, "path": path}
        if content:
            params["content"] = content
        params.update(kwargs)
        return self._conn.send_command("manage_script", params)

    def delete(self, name: str, path: str = "Scripts") -> dict[str, Any]:
        """Delete a C# script"""
        return self._conn.send_command(
            "manage_script",
            {
                "action": "delete",
                "name": name,
                "path": path,
            },
        )


class ShaderAPI:
    """Shader operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(
        self,
        name: str,
        path: str = "Shaders",
        shader_type: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create a new shader"""
        params: dict[str, Any] = {"action": "create", "name": name, "path": path}
        if shader_type:
            params["shaderType"] = shader_type
        params.update(kwargs)
        return self._conn.send_command("manage_shader", params)

    def modify(
        self,
        name: str,
        path: str = "Shaders",
        content: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Modify an existing shader"""
        params: dict[str, Any] = {"action": "modify", "name": name, "path": path}
        if content:
            params["content"] = content
        params.update(kwargs)
        return self._conn.send_command("manage_shader", params)

    def delete(self, name: str, path: str = "Shaders") -> dict[str, Any]:
        """Delete a shader"""
        return self._conn.send_command(
            "manage_shader",
            {
                "action": "delete",
                "name": name,
                "path": path,
            },
        )


class PrefabAPI:
    """Prefab operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(
        self,
        name: str,
        path: str = "Prefabs",
        source_object: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create a new prefab"""
        params: dict[str, Any] = {"action": "create", "name": name, "path": path}
        if source_object:
            params["sourceObject"] = source_object
        params.update(kwargs)
        return self._conn.send_command("manage_prefabs", params)

    def instantiate(
        self,
        path: str,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        parent: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Instantiate a prefab in the scene"""
        params: dict[str, Any] = {"action": "instantiate", "path": path}
        if position:
            params["position"] = position
        if rotation:
            params["rotation"] = rotation
        if parent:
            params["parent"] = parent
        params.update(kwargs)
        return self._conn.send_command("manage_prefabs", params)

    def apply(self, target: str, search_method: str = "by_name") -> dict[str, Any]:
        """Apply changes to prefab"""
        return self._conn.send_command(
            "manage_prefabs",
            {
                "action": "apply",
                "target": target,
                "searchMethod": search_method,
            },
        )

    def revert(self, target: str, search_method: str = "by_name") -> dict[str, Any]:
        """Revert prefab instance to original"""
        return self._conn.send_command(
            "manage_prefabs",
            {
                "action": "revert",
                "target": target,
                "searchMethod": search_method,
            },
        )


class GameObjectAPI:
    """GameObject operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(
        self,
        name: str,
        parent: str | None = None,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
        primitive_type: str | None = None,
        prefab_path: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Create GameObject"""
        params = {"action": "create", "name": name}
        if parent:
            params["parent"] = parent
        if position:
            params["position"] = position
        if rotation:
            params["rotation"] = rotation
        if scale:
            params["scale"] = scale
        if primitive_type:
            params["primitiveType"] = primitive_type
        if prefab_path:
            params["prefabPath"] = prefab_path
        params.update(kwargs)

        return self._conn.send_command("manage_gameobject", params)

    def modify(
        self,
        target: str,
        search_method: str = "by_name",
        name: str | None = None,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | None = None,
        component_properties: dict[str, dict] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Modify GameObject"""
        params = {"action": "modify", "target": target, "searchMethod": search_method}
        if name:
            params["name"] = name
        if position:
            params["position"] = position
        if rotation:
            params["rotation"] = rotation
        if scale:
            params["scale"] = scale
        if component_properties:
            params["componentProperties"] = component_properties
        params.update(kwargs)

        return self._conn.send_command("manage_gameobject", params)

    def delete(self, target: str, search_method: str = "by_name") -> dict[str, Any]:
        """Delete GameObject"""
        return self._conn.send_command(
            "manage_gameobject", {"action": "delete", "target": target, "searchMethod": search_method}
        )

    def find(
        self,
        search_method: str = "by_name",
        search_term: str | None = None,
        target: str | None = None,
        find_all: bool = False,
        search_inactive: bool = False,
        page_size: int | None = None,
        page: int | None = None,
        offset: int | None = None,
        cursor: int | str | None = None,
    ) -> dict[str, Any]:
        """
        Find GameObject(s) with pagination support

        Args:
            search_method: Search method (default: "by_name")
            search_term: Search keyword
            target: Target name (alternative to search_term)
            find_all: Find all matching objects
            search_inactive: Include inactive GameObjects
            page_size: Items per page (1-500, default: 50)
            page: Page number (for page-based pagination)
            offset: Offset value (for offset-based pagination)
            cursor: Cursor value (for cursor-based pagination). Accepts int or str.

        Returns:
            Dict containing:
                - instanceIDs: List of instance IDs
                - pageSize: Actual items returned
                - cursor: Current cursor
                - nextCursor: Next page cursor
                - totalCount: Total matching items
                - hasMore: Whether more items exist
        """
        params = {"action": "find", "searchMethod": search_method, "findAll": find_all}
        if search_term:
            params["searchTerm"] = search_term
        if target:
            params["target"] = target
        if search_inactive:
            params["searchInactive"] = search_inactive
        if page_size is not None:
            params["pageSize"] = page_size
        if page is not None:
            params["page"] = page
        if offset is not None:
            params["offset"] = offset
        if cursor is not None:
            params["cursor"] = cursor

        return self._conn.send_command("manage_gameobject", params)

    def iterate_find(
        self,
        search_method: str = "by_name",
        search_term: str | None = None,
        target: str | None = None,
        search_inactive: bool = False,
        page_size: int = 50,
    ):
        """
        Iterate through find results using pagination

        This is a generator that automatically fetches all pages until completion.
        Supports both:
        - Server v8.6.0+: Paged responses with pagination info
        - Server v8.3.0 and earlier: Full response (client-side paging)

        Args:
            search_method: Search method (default: "by_name")
            search_term: Search keyword
            target: Target name (alternative to search_term)
            search_inactive: Include inactive GameObjects
            page_size: Items per page (1-500, default: 50)

        Yields:
            Dict for each page containing find results
        """
        result = self.find(
            search_method=search_method,
            search_term=search_term,
            target=target,
            find_all=True,
            search_inactive=search_inactive,
            page_size=page_size,
            cursor="0",
        )

        data = result.get("data", [])

        # Detect server response format
        if isinstance(data, list):
            # Legacy server: data is a flat list, do client-side pagination
            yield from _client_side_paginate(
                items=data,
                page_size=page_size,
                base_message=result.get("message", ""),
                use_int_cursor=False,
                yield_on_empty=False,
            )
        else:
            # Modern server: data is a dict with pagination info
            yield result

            while data.get("hasMore") or data.get("nextCursor"):
                next_cursor = data.get("nextCursor")
                if next_cursor is None:
                    break

                result = self.find(
                    search_method=search_method,
                    search_term=search_term,
                    target=target,
                    find_all=True,
                    search_inactive=search_inactive,
                    page_size=page_size,
                    cursor=str(next_cursor),
                )
                data = result.get("data", {})
                yield result

    def add_component(
        self,
        target: str,
        components: list[str],
        search_method: str = "by_name",
        component_properties: dict[str, dict] | None = None,
    ) -> dict[str, Any]:
        """Add component(s)"""
        params = {
            "action": "add_component",
            "target": target,
            "componentsToAdd": components,
            "searchMethod": search_method,
        }
        if component_properties:
            params["componentProperties"] = component_properties

        return self._conn.send_command("manage_gameobject", params)

    def remove_component(self, target: str, components: list[str], search_method: str = "by_name") -> dict[str, Any]:
        """Remove component(s)"""
        return self._conn.send_command(
            "manage_gameobject",
            {
                "action": "remove_component",
                "target": target,
                "componentsToRemove": components,
                "searchMethod": search_method,
            },
        )


class SceneAPI:
    """Scene management operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(self, name: str, path: str = "Scenes") -> dict[str, Any]:
        """Create new scene"""
        return self._conn.send_command("manage_scene", {"action": "create", "name": name, "path": path})

    def load(self, name: str | None = None, path: str | None = None, build_index: int | None = None) -> dict[str, Any]:
        """Load scene"""
        params = {"action": "load"}
        if name:
            params["name"] = name
        if path:
            params["path"] = path
        if build_index is not None:
            params["buildIndex"] = build_index

        return self._conn.send_command("manage_scene", params)

    def save(self, name: str | None = None, path: str | None = None) -> dict[str, Any]:
        """Save current scene"""
        params = {"action": "save"}
        if name:
            params["name"] = name
        if path:
            params["path"] = path

        return self._conn.send_command("manage_scene", params)

    def get_hierarchy(
        self,
        page_size: int | None = None,
        cursor: int | str | None = None,
        max_nodes: int | None = None,
        max_depth: int | None = None,
        max_children_per_node: int | None = None,
        parent: Any | None = None,
        include_transform: bool | None = None,
    ) -> dict[str, Any]:
        """
        Get scene hierarchy with pagination support

        Args:
            page_size: Items per page (1-500, default: 50)
            cursor: Starting position (default: 0). Accepts int or str.
            max_nodes: Total node limit (1-5000, default: 1000)
            max_depth: Depth limit (for future compatibility)
            max_children_per_node: Children per node limit (0-2000, default: 200)
            parent: Parent object to query from (null = roots)
            include_transform: Include transform information

        Returns:
            Dict containing:
                - scope: "roots" or "children"
                - cursor: Current cursor position
                - pageSize: Actual items returned
                - next_cursor: Next page cursor (null if finished)
                - truncated: Whether more items exist
                - total: Total available items
                - items: List of GameObject summaries
        """
        params = {"action": "get_hierarchy"}

        if page_size is not None:
            params["page_size"] = page_size
        if cursor is not None:
            params["cursor"] = cursor
        if max_nodes is not None:
            params["max_nodes"] = max_nodes
        if max_depth is not None:
            params["max_depth"] = max_depth
        if max_children_per_node is not None:
            params["max_children_per_node"] = max_children_per_node
        if parent is not None:
            params["parent"] = parent
        if include_transform is not None:
            params["include_transform"] = include_transform

        return self._conn.send_command("manage_scene", params)

    def get_active(self) -> dict[str, Any]:
        """Get active scene info"""
        return self._conn.send_command("manage_scene", {"action": "get_active"})

    def get_build_settings(self) -> dict[str, Any]:
        """Get build settings (scenes in build)"""
        return self._conn.send_command("manage_scene", {"action": "get_build_settings"})

    def get_hierarchy_summary(self, depth: int = 0, include_transform: bool = False) -> dict[str, Any]:
        """
        Get scene hierarchy summary (safe default for large scenes)

        Args:
            depth: How deep to traverse (0 = root only, 1 = root + direct children, etc.)
            include_transform: Include transform information

        Returns:
            Dict with summary info and limited hierarchy data
        """
        result = self.get_hierarchy(include_transform=include_transform)

        if not result.get("success"):
            return result

        data = result.get("data", [])

        def count_descendants(items: list) -> int:
            """Count all descendants recursively"""
            total = 0
            for item in items:
                children = item.get("children", [])
                total += len(children) + count_descendants(children)
            return total

        def truncate_to_depth(items: list, current_depth: int, max_depth: int) -> list:
            """Truncate hierarchy to specified depth"""
            truncated = []
            for item in items:
                new_item = {k: v for k, v in item.items() if k != "children"}
                children = item.get("children", [])
                new_item["childCount"] = len(children)
                new_item["descendantCount"] = len(children) + count_descendants(children)

                if current_depth < max_depth and children:
                    new_item["children"] = truncate_to_depth(children, current_depth + 1, max_depth)
                elif children:
                    new_item["children"] = []  # Truncated

                truncated.append(new_item)
            return truncated

        if isinstance(data, list):
            total_objects = len(data) + count_descendants(data)
            truncated_data = truncate_to_depth(data, 0, depth)

            return {
                "success": True,
                "message": f"Hierarchy summary (depth={depth}, total={total_objects} objects)",
                "data": {
                    "summary": {
                        "rootCount": len(data),
                        "totalCount": total_objects,
                        "depth": depth,
                        "truncated": depth < 100,  # Always truncated unless very deep
                    },
                    "items": truncated_data,
                },
            }
        else:
            # Server v8.6.0+ with paging - return as-is for now
            return result

    def iterate_hierarchy(
        self,
        page_size: int = 50,
        max_nodes: int | None = None,
        max_children_per_node: int | None = None,
        parent: Any | None = None,
        include_transform: bool | None = None,
    ):
        """
        Iterate through entire scene hierarchy using cursor-based pagination

        This is a generator that automatically fetches all pages until completion.
        Supports both:
        - Server v8.6.0+: Paged responses with {"data": {"items": [...], "next_cursor": ...}}
        - Server v8.3.0 and earlier: Full response with {"data": [...]} (client-side paging)

        Args:
            page_size: Items per page (1-500, default: 50)
            max_nodes: Total node limit per request (1-5000, default: 1000)
            max_children_per_node: Children per node limit (0-2000, default: 200)
            parent: Parent object to query from (null = roots)
            include_transform: Include transform information

        Yields:
            Dict for each page. For paged servers: original response.
            For non-paged servers: synthetic paged response with 'items' key.

        Example:
            for page in client.scene.iterate_hierarchy(page_size=100):
                items = page['data']['items'] if 'items' in page.get('data', {}) else page['data']
                for item in items:
                    print(f"  - {item['name']}")
        """
        result = self.get_hierarchy(
            page_size=page_size,
            cursor=0,
            max_nodes=max_nodes,
            max_children_per_node=max_children_per_node,
            parent=parent,
            include_transform=include_transform,
        )

        data = result.get("data", {})

        # Detect server response format
        if isinstance(data, list):
            # Legacy server (v8.3.0 and earlier): data is a flat list
            # Perform client-side pagination
            all_items = self._flatten_hierarchy(data)
            yield from _client_side_paginate(
                items=all_items,
                page_size=page_size,
                base_message=result.get("message", ""),
                use_int_cursor=True,
                yield_on_empty=False,
            )
        else:
            # Modern server (v8.6.0+): data is a dict with pagination info
            yield result

            while True:
                next_cursor = data.get("next_cursor")
                if next_cursor is None:
                    break

                result = self.get_hierarchy(
                    page_size=page_size,
                    cursor=int(next_cursor),
                    max_nodes=max_nodes,
                    max_children_per_node=max_children_per_node,
                    parent=parent,
                    include_transform=include_transform,
                )
                data = result.get("data", {})
                yield result

    def _flatten_hierarchy(self, items: list, depth: int = 0) -> list:
        """Flatten nested hierarchy into a flat list with depth info"""
        result = []
        for item in items:
            flat_item = {k: v for k, v in item.items() if k != "children"}
            flat_item["_depth"] = depth
            result.append(flat_item)
            children = item.get("children", [])
            if children:
                result.extend(self._flatten_hierarchy(children, depth + 1))
        return result


class AssetAPI:
    """Asset management operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(self, path: str, asset_type: str, properties: dict | None = None) -> dict[str, Any]:
        """Create asset"""
        params = {"action": "create", "path": path, "assetType": asset_type}
        if properties:
            params["properties"] = properties

        return self._conn.send_command("manage_asset", params)

    def modify(self, path: str, properties: dict) -> dict[str, Any]:
        """Modify asset"""
        return self._conn.send_command("manage_asset", {"action": "modify", "path": path, "properties": properties})

    def delete(self, path: str) -> dict[str, Any]:
        """Delete asset"""
        return self._conn.send_command("manage_asset", {"action": "delete", "path": path})

    def search(
        self,
        search_pattern: str | None = None,
        filter_type: str | None = None,
        path: str | None = None,
        page_size: int = 50,
        page_number: int = 1,
        filter_date_after: str | None = None,
    ) -> dict[str, Any]:
        """
        Search assets with filtering and pagination.

        Args:
            search_pattern: Search pattern for asset names
            filter_type: Asset type filter (e.g., "Prefab", "Material", "Texture2D")
            path: Folder path to search in
            page_size: Items per page (default: 50)
            page_number: Page number (1-based, default: 1)
            filter_date_after: ISO 8601 date string to filter assets modified after this date
        """
        params: dict[str, Any] = {
            "action": "search",
            "pageSize": page_size,
            "pageNumber": page_number,
        }
        if search_pattern:
            params["searchPattern"] = search_pattern
        if filter_type:
            params["filterType"] = filter_type
        if path:
            params["path"] = path
        if filter_date_after:
            params["filterDateAfter"] = filter_date_after

        return self._conn.send_command("manage_asset", params)


class BatchAPI:
    """Batch execution operations"""

    MAX_COMMANDS_PER_BATCH = 25

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def execute(
        self,
        commands: list[dict[str, Any]],
        parallel: bool | None = None,
        fail_fast: bool | None = None,
        max_parallelism: int | None = None,
    ) -> dict[str, Any]:
        """
        Execute multiple commands as a batch.

        Args:
            commands: List of command specifications with 'tool' and 'params' keys.
                     Example: [{"tool": "read_console", "params": {"action": "get"}}, ...]
            parallel: Attempt to run read-only commands in parallel (Unity always runs sequentially)
            fail_fast: Stop processing after the first failure
            max_parallelism: Hint for maximum number of parallel workers

        Returns:
            Dict containing:
                - results: List of individual command results
                - callSuccessCount: Number of successful commands
                - callFailureCount: Number of failed commands
                - parallelRequested: Whether parallel execution was requested
                - parallelApplied: Whether parallel execution was applied (always False in Unity)

        Raises:
            UnityMCPError: If validation fails or batch execution fails
        """
        if not isinstance(commands, list) or not commands:
            raise UnityMCPError("'commands' must be a non-empty list of command specifications")

        if len(commands) > self.MAX_COMMANDS_PER_BATCH:
            raise UnityMCPError(
                f"batch_execute supports up to {self.MAX_COMMANDS_PER_BATCH} commands; received {len(commands)}"
            )

        # Validate command structure
        normalized_commands = []
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                raise UnityMCPError(f"Command at index {index} must be a dict with 'tool' and 'params' keys")

            tool_name = command.get("tool")
            params = command.get("params", {})

            if not tool_name or not isinstance(tool_name, str):
                raise UnityMCPError(f"Command at index {index} is missing a valid 'tool' name")

            if params is None:
                params = {}
            if not isinstance(params, dict):
                raise UnityMCPError(f"Command '{tool_name}' must specify parameters as a dict")

            normalized_commands.append(
                {
                    "tool": tool_name,
                    "params": params,
                }
            )

        # Build payload
        payload = {"commands": normalized_commands}

        if parallel is not None:
            payload["parallel"] = bool(parallel)
        if fail_fast is not None:
            payload["failFast"] = bool(fail_fast)
        if max_parallelism is not None:
            payload["maxParallelism"] = int(max_parallelism)

        return self._conn.send_command("batch_execute", payload)


class MaterialAPI:
    """Material management operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(self, material_path: str, shader: str = "Standard", properties: dict | None = None) -> dict[str, Any]:
        """Create material"""
        params = {"action": "create", "materialPath": material_path, "shader": shader}
        if properties:
            params["properties"] = properties

        return self._conn.send_command("manage_material", params)

    def set_shader_property(self, material_path: str, property: str, value: Any) -> dict[str, Any]:
        """Set shader property"""
        return self._conn.send_command(
            "manage_material",
            {"action": "set_shader_property", "materialPath": material_path, "property": property, "value": value},
        )

    def set_color(self, material_path: str, color: list[float], property: str = "_BaseColor") -> dict[str, Any]:
        """Set material color"""
        return self._conn.send_command(
            "manage_material",
            {"action": "set_color", "materialPath": material_path, "color": color, "property": property},
        )

    def assign_to_renderer(
        self, material_path: str, target: str, search_method: str = "by_name", slot: int = 0, mode: str = "shared"
    ) -> dict[str, Any]:
        """Assign material to renderer"""
        return self._conn.send_command(
            "manage_material",
            {
                "action": "assign_to_renderer",
                "materialPath": material_path,
                "target": target,
                "searchMethod": search_method,
                "slot": slot,
                "mode": mode,
            },
        )

    def set_renderer_color(
        self,
        target: str,
        color: list[float],
        search_method: str = "by_name",
        slot: int = 0,
        mode: str = "property_block",
    ) -> dict[str, Any]:
        """Set renderer color"""
        return self._conn.send_command(
            "manage_material",
            {
                "action": "set_renderer_color",
                "target": target,
                "color": color,
                "searchMethod": search_method,
                "slot": slot,
                "mode": mode,
            },
        )

    def get_info(self, material_path: str) -> dict[str, Any]:
        """Get material info"""
        return self._conn.send_command("manage_material", {"action": "get_info", "materialPath": material_path})


class UnityMCPClient:
    """
    Complete Unity MCP client with all tools

    Usage:
        client = UnityMCPClient()

        # Console
        client.console.get(types=["error"], count=10)
        client.console.clear()

        # Editor
        client.editor.play()
        client.editor.stop()

        # GameObject
        client.gameobject.create("Player", primitive_type="Cube")
        client.gameobject.find(search_term="Player")

        # Scene
        client.scene.load(path="Assets/Scenes/Main.unity")
        client.scene.get_hierarchy_summary()

        # Tests (with filtering)
        client.tests.run("edit")
        client.tests.run("edit", filter_options=TestFilterOptions(category_names=["Unit"]))

        # Menu
        client.menu.execute("Assets/Refresh")

        # Script/Shader/Prefab
        client.script.create("MyScript", namespace="MyGame")
        client.shader.create("MyShader")
        client.prefab.create("MyPrefab", source_object="Player")

        # Batch execution
        result = client.batch.execute([
            {"tool": "read_console", "params": {"action": "clear"}},
            {"tool": "manage_editor", "params": {"action": "play"}},
        ], fail_fast=True)
    """

    def __init__(self, host="localhost", port=6400, timeout=5.0):
        self._conn = UnityMCPConnection(host, port, timeout)

        # API objects
        self.console = ConsoleAPI(self._conn)
        self.editor = EditorAPI(self._conn)
        self.gameobject = GameObjectAPI(self._conn)
        self.scene = SceneAPI(self._conn)
        self.asset = AssetAPI(self._conn)
        self.batch = BatchAPI(self._conn)
        self.material = MaterialAPI(self._conn)
        self.tests = TestAPI(self._conn)
        self.menu = MenuAPI(self._conn)
        self.script = ScriptAPI(self._conn)
        self.shader = ShaderAPI(self._conn)
        self.prefab = PrefabAPI(self._conn)


def main():
    """CLI entry point for unity-mcp command"""
    import argparse
    import sys

    # Load config first to use as defaults
    config = UnityMCPConfig.load()

    parser = argparse.ArgumentParser(
        description="Unity MCP Client CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available commands:
  console                 Get console logs
  clear                   Clear console
  play                    Enter play mode
  stop                    Exit play mode
  state                   Get editor state
  refresh                 Refresh assets
  tests <mode>            Run tests (edit|play) with optional filtering
  verify                  Verify build (refresh → clear → compile wait → console)
  config                  Show current configuration
  config init             Generate default .unity-mcp.toml
  scene <action>          Scene operations (create|load|save|hierarchy|active|build-settings)
  gameobject <action>     GameObject operations (find|create|delete|modify)
  material <action>       Material operations (create|info|set-color|set-property|assign|set-renderer-color)

Examples:
  %(prog)s state
  %(prog)s refresh
  %(prog)s console --types error --count 50
  %(prog)s verify --timeout 120 --connection-timeout 60
  %(prog)s verify --types error warning log --retry 5
  %(prog)s tests edit
  %(prog)s tests edit --test-names "MyTests.SampleTest"
  %(prog)s tests edit --category-names "Unit" "Integration"
  %(prog)s tests play --assembly-names "MyGame.Tests"
  %(prog)s config
  %(prog)s config init
  %(prog)s config init --output my-config.toml
  %(prog)s scene active
  %(prog)s scene hierarchy                    # roots only (summary)
  %(prog)s scene hierarchy --depth 1          # roots + direct children
  %(prog)s scene hierarchy --full             # full nested hierarchy
  %(prog)s scene hierarchy --iterate-all      # full flattened (paged)
  %(prog)s scene load --name MainScene
  %(prog)s scene load --path Assets/Scenes/Level1.unity
  %(prog)s scene create --name NewScene --path Assets/Scenes
  %(prog)s scene save
  %(prog)s scene build-settings
  %(prog)s gameobject find "Main Camera"
  %(prog)s gameobject create --name "MyCube" --primitive Cube --position 0,0,0
  %(prog)s gameobject create --name "Player" --parent "GameManager" --position 1,2,3 --scale 2,2,2
  %(prog)s gameobject modify --name "MyCube" --position 5,0,0 --rotation 0,45,0
  %(prog)s gameobject delete --name "MyCube"
  %(prog)s material create --path Assets/Materials/New.mat --shader Standard
  %(prog)s material info --path Assets/Materials/Existing.mat
  %(prog)s material set-color --path Assets/Materials/Mat.mat --color 1,0,0,1

Configuration:
  Settings can be stored in .unity-mcp.toml in the current directory
  or Unity project root. Example:

    # .unity-mcp.toml
    port = 6401
    host = "localhost"
    timeout = 5.0
    connection_timeout = 30.0
    retry = 3
    log_types = ["error", "warning"]
    log_count = 20
        """,
    )
    parser.add_argument("command", help="Command to execute (see available commands below)")
    parser.add_argument("args", nargs="*", help="Command arguments")
    parser.add_argument(
        "--port", type=int, default=None, help=f"Server port (default: {config.port}, from config/EditorPrefs)"
    )
    parser.add_argument("--host", default=None, help=f"Server host (default: {config.host})")
    parser.add_argument(
        "--count", type=int, default=None, help=f"Number of console logs to retrieve (default: {config.log_count})"
    )
    parser.add_argument(
        "--types",
        nargs="+",
        default=None,
        help=f"Log types to retrieve (default: {' '.join(config.log_types)}). Options: error, warning, log",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help=f"Maximum wait time for compilation in seconds (default: {int(config.timeout)}, verify only)",
    )
    parser.add_argument(
        "--connection-timeout",
        type=float,
        default=None,
        help=f"TCP connection timeout in seconds (default: {config.connection_timeout}, verify only)",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=None,
        help=f"Maximum connection retry attempts (default: {config.retry}, verify only)",
    )
    # Scene command arguments
    parser.add_argument(
        "--name", default=None, help="Scene/GameObject name (for scene create/load, gameobject create/modify/delete)"
    )
    parser.add_argument(
        "--path", default=None, help="Scene path (for scene create/load/save) or Material path (for material commands)"
    )
    parser.add_argument("--build-index", type=int, default=None, help="Build index (for scene load)")
    # Material command arguments
    parser.add_argument("--shader", default="Standard", help="Shader name (for material create, default: Standard)")
    parser.add_argument("--color", default=None, help="Color as comma-separated RGBA (e.g., 1,0,0,1 for red)")
    parser.add_argument("--property", default="_BaseColor", help="Shader property name (default: _BaseColor)")
    parser.add_argument("--value", default=None, help="Property value (for material set-property)")
    parser.add_argument(
        "--target", default=None, help="Target GameObject name (for material assign/set-renderer-color)"
    )
    parser.add_argument("--search-method", default="by_name", help="Search method (default: by_name)")
    parser.add_argument("--slot", type=int, default=0, help="Material slot index (default: 0)")
    parser.add_argument(
        "--mode",
        default=None,
        help="Mode: 'shared' or 'instance' (for assign), 'property_block' or 'material' (for set-renderer-color)",
    )
    # GameObject command arguments
    parser.add_argument(
        "--primitive",
        default=None,
        help="Primitive type (for gameobject create). Options: Cube, Sphere, Capsule, Cylinder, Plane, Quad",
    )
    parser.add_argument("--position", default=None, help="Position as x,y,z (for gameobject create/modify)")
    parser.add_argument("--rotation", default=None, help="Rotation as x,y,z (for gameobject create/modify)")
    parser.add_argument("--scale", default=None, help="Scale as x,y,z (for gameobject create/modify)")
    parser.add_argument("--parent", default=None, help="Parent GameObject name (for gameobject create)")
    # Pagination arguments (for scene hierarchy and gameobject find)
    parser.add_argument("--page-size", type=int, default=None, help="Items per page (1-500, default: 50)")
    parser.add_argument("--cursor", type=int, default=None, help="Starting cursor position (default: 0)")
    parser.add_argument("--max-nodes", type=int, default=None, help="Total node limit (1-5000, default: 1000)")
    parser.add_argument(
        "--max-children-per-node", type=int, default=None, help="Children per node limit (0-2000, default: 200)"
    )
    parser.add_argument(
        "--include-transform", action="store_true", help="Include transform information (for scene hierarchy)"
    )
    parser.add_argument(
        "--depth", type=int, default=None, help="Hierarchy depth (0=roots only, 1=roots+children, etc. Default: 0)"
    )
    parser.add_argument("--full", action="store_true", help="Get full hierarchy (no depth limit, legacy behavior)")
    parser.add_argument(
        "--iterate-all", action="store_true", help="Iterate through all pages (for scene hierarchy, gameobject find)"
    )
    # Config init arguments
    parser.add_argument("--output", "-o", default=None, help="Output path for config init (default: ./.unity-mcp.toml)")
    parser.add_argument(
        "--force", "-f", action="store_true", help="Overwrite existing config file without confirmation"
    )
    # Test filter arguments
    parser.add_argument("--test-names", nargs="+", default=None, help="Test names to run (exact match)")
    parser.add_argument("--group-names", nargs="+", default=None, help="Test group names (regex patterns)")
    parser.add_argument("--category-names", nargs="+", default=None, help="NUnit category names ([Category] attribute)")
    parser.add_argument("--assembly-names", nargs="+", default=None, help="Assembly names to filter by")

    args = parser.parse_args()

    # Apply config defaults where CLI args not specified
    port = args.port if args.port is not None else config.port
    host = args.host if args.host is not None else config.host
    timeout = args.timeout if args.timeout is not None else int(config.timeout)
    connection_timeout = args.connection_timeout if args.connection_timeout is not None else config.connection_timeout
    retry = args.retry if args.retry is not None else config.retry
    log_types = args.types if args.types is not None else config.log_types
    log_count = args.count if args.count is not None else config.log_count

    client = UnityMCPClient(host=host, port=port, timeout=config.timeout)

    try:
        if args.command == "config":
            # Check for 'init' subcommand
            if args.args and args.args[0] == "init":
                output_path = Path(args.output) if args.output else Path(CONFIG_FILE_NAME)

                if output_path.exists() and not args.force:
                    print(f"Error: {output_path} already exists. Use --force to overwrite.")
                    sys.exit(1)

                default_config = UnityMCPConfig()
                output_path.write_text(default_config.to_toml())
                print(f"Created {output_path}")
            else:
                config_file = UnityMCPConfig._find_config_file()
                print("=== Unity MCP Configuration ===")
                print(f"Config file: {config_file or 'Not found (using defaults)'}")
                print(f"Port: {port}")
                print(f"Host: {host}")
                print(f"Timeout: {config.timeout}s")
                print(f"Connection timeout: {connection_timeout}s")
                print(f"Retry: {retry}")
                print(f"Log types: {', '.join(log_types)}")
                print(f"Log count: {log_count}")

        elif args.command == "console":
            result = client.console.get(types=log_types, count=log_count)
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "clear":
            result = client.console.clear()
            print("Console cleared")

        elif args.command == "play":
            client.editor.play()
            print("Entered play mode")

        elif args.command == "stop":
            client.editor.stop()
            print("Exited play mode")

        elif args.command == "state":
            result = client.editor.get_state()
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "refresh":
            print("Refreshing assets...")
            client.menu.execute("Assets/Refresh")
            print("✓ Asset refresh triggered")

        elif args.command == "find" and args.args:
            result = client.gameobject.find(search_method="by_name", search_term=args.args[0])
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "tests":
            mode = args.args[0] if args.args else "edit"

            # Build filter options if any filter is specified
            filter_options = None
            if any([args.test_names, args.group_names, args.category_names, args.assembly_names]):
                filter_options = TestFilterOptions(
                    test_names=args.test_names,
                    group_names=args.group_names,
                    category_names=args.category_names,
                    assembly_names=args.assembly_names,
                )

            result = client.tests.run(mode=mode, filter_options=filter_options)
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "verify":
            import time

            # Create a separate client with longer timeout for verify operations
            verify_client = UnityMCPClient(host=host, port=port, timeout=connection_timeout)

            # Step 1: Refresh assets
            print("=== Refreshing Assets ===")
            verify_client.menu.execute("Assets/Refresh")
            print("✓ Asset refresh triggered")

            # Step 2: Clear console (to capture only new errors)
            print("\n=== Clearing Console ===")
            verify_client.console.clear()
            print("✓ Console cleared")

            # Step 3: Wait for compilation using isCompiling state
            print("\n=== Waiting for Compilation ===")
            poll_interval = 1.0
            elapsed = 0.0
            connection_failures = 0

            while elapsed < timeout:
                time.sleep(poll_interval)
                elapsed += poll_interval

                try:
                    state = verify_client.editor.get_state()
                    is_compiling = state.get("data", {}).get("isCompiling", False)

                    if not is_compiling:
                        print(f"\n✓ Compilation complete ({elapsed:.1f}s)")
                        break

                    print(f"  Compiling... ({elapsed:.1f}s)", end="\r")
                    connection_failures = 0  # Reset on successful connection

                except UnityMCPError:
                    connection_failures += 1
                    if connection_failures <= retry:
                        print(f"  Connection lost, retrying ({connection_failures}/{retry})...", end="\r")
                        continue
                    print(f"\n⚠ Connection failed after {retry} retries")
                    sys.exit(1)
            else:
                print(f"\n⚠ Timeout after {timeout}s")
                sys.exit(1)

            # Step 4: Check console logs
            print("\n=== Console Logs ===")
            logs = verify_client.console.get(types=log_types, count=log_count)

            if logs["data"]:
                print(f"Found {len(logs['data'])} log entries (types: {', '.join(log_types)}, max: {log_count}):\n")
                for log in logs["data"]:
                    print(f"[{log['type']}] {log['message']}")
                    if log.get("file"):
                        print(f"  at {log['file']}:{log.get('line', '?')}")
            else:
                print(f"✓ No logs found (searched types: {', '.join(log_types)})")

        elif args.command == "scene":
            if not args.args:
                print("Usage: scene <action>")
                print("Actions: create, load, save, hierarchy, active, build-settings")
                sys.exit(1)

            action = args.args[0]

            if action == "active":
                result = client.scene.get_active()
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "hierarchy":
                if args.iterate_all:
                    # Iterate through all pages (flattened)
                    all_items = []
                    total_pages = 0

                    for page in client.scene.iterate_hierarchy(
                        page_size=args.page_size or 50,
                        max_nodes=args.max_nodes,
                        max_children_per_node=args.max_children_per_node,
                        include_transform=args.include_transform if args.include_transform else None,
                    ):
                        total_pages += 1
                        data = page.get("data", {})
                        items = data.get("items", [])
                        all_items.extend(items)
                        print(
                            f"Page {total_pages}: {len(items)} items (total so far: {len(all_items)})", file=sys.stderr
                        )

                    result = {
                        "success": True,
                        "message": f"Retrieved all {len(all_items)} items across {total_pages} pages",
                        "data": {"total": len(all_items), "pages": total_pages, "items": all_items},
                    }
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                elif args.full:
                    # Full hierarchy (legacy behavior, nested structure)
                    result = client.scene.get_hierarchy(
                        page_size=args.page_size,
                        cursor=args.cursor,
                        max_nodes=args.max_nodes,
                        max_children_per_node=args.max_children_per_node,
                        include_transform=args.include_transform if args.include_transform else None,
                    )
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    # Default: summary (safe for large scenes)
                    depth = args.depth if args.depth is not None else 0
                    result = client.scene.get_hierarchy_summary(depth=depth, include_transform=args.include_transform)
                    print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "build-settings":
                result = client.scene.get_build_settings()
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "load":
                if not args.name and not args.path and args.build_index is None:
                    print("Error: --name, --path, or --build-index required for load")
                    sys.exit(1)
                result = client.scene.load(name=args.name, path=args.path, build_index=args.build_index)
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "save":
                result = client.scene.save(name=args.name, path=args.path)
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "create":
                if not args.name:
                    print("Error: --name required for create")
                    sys.exit(1)
                path = args.path or "Scenes"
                result = client.scene.create(name=args.name, path=path)
                print(json.dumps(result, indent=2, ensure_ascii=False))

            else:
                print(f"Unknown scene action: {action}")
                print("Actions: create, load, save, hierarchy, active, build-settings")
                sys.exit(1)

        elif args.command == "material":
            if not args.args:
                print("Usage: material <action>")
                print("Actions: create, info, set-color, set-property, assign, set-renderer-color")
                sys.exit(1)

            action = args.args[0]

            # Helper function to parse color
            def parse_color(s: str) -> list[float]:
                parts = s.split(",")
                if len(parts) != 4:
                    raise ValueError(f"Invalid color format: {s} (expected r,g,b,a)")
                return [float(p.strip()) for p in parts]

            if action == "create":
                if not args.path:
                    print("Error: --path required for create")
                    sys.exit(1)
                result = client.material.create(material_path=args.path, shader=args.shader)
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "info":
                if not args.path:
                    print("Error: --path required for info")
                    sys.exit(1)
                result = client.material.get_info(material_path=args.path)
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "set-color":
                if not args.path:
                    print("Error: --path required for set-color")
                    sys.exit(1)
                if not args.color:
                    print("Error: --color required for set-color")
                    sys.exit(1)
                color = parse_color(args.color)
                result = client.material.set_color(material_path=args.path, color=color, property=args.property)
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "set-property":
                if not args.path:
                    print("Error: --path required for set-property")
                    sys.exit(1)
                if not args.property:
                    print("Error: --property required for set-property")
                    sys.exit(1)
                if args.value is None:
                    print("Error: --value required for set-property")
                    sys.exit(1)
                result = client.material.set_shader_property(
                    material_path=args.path, property=args.property, value=args.value
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "assign":
                if not args.path:
                    print("Error: --path required for assign")
                    sys.exit(1)
                if not args.target:
                    print("Error: --target required for assign")
                    sys.exit(1)
                mode = args.mode or "shared"
                result = client.material.assign_to_renderer(
                    material_path=args.path,
                    target=args.target,
                    search_method=args.search_method,
                    slot=args.slot,
                    mode=mode,
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "set-renderer-color":
                if not args.target:
                    print("Error: --target required for set-renderer-color")
                    sys.exit(1)
                if not args.color:
                    print("Error: --color required for set-renderer-color")
                    sys.exit(1)
                color = parse_color(args.color)
                mode = args.mode or "property_block"
                result = client.material.set_renderer_color(
                    target=args.target, color=color, search_method=args.search_method, slot=args.slot, mode=mode
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))

            else:
                print(f"Unknown material action: {action}")
                print("Actions: create, info, set-color, set-property, assign, set-renderer-color")
                sys.exit(1)

        elif args.command == "gameobject":
            if not args.args:
                print("Usage: gameobject <action>")
                print("Actions: find, create, delete, modify")
                sys.exit(1)

            action = args.args[0]

            # Helper function to parse x,y,z format
            def parse_vector3(s: str) -> list[float]:
                parts = s.split(",")
                if len(parts) != 3:
                    raise ValueError(f"Invalid vector format: {s} (expected x,y,z)")
                return [float(p.strip()) for p in parts]

            if action == "find":
                # gameobject find <name> [--iterate-all] [--page-size N]
                if len(args.args) < 2:
                    print("Error: GameObject name required for find")
                    sys.exit(1)
                search_term = args.args[1]

                if args.iterate_all:
                    # Iterate through all pages
                    all_items = []
                    total_pages = 0

                    for page in client.gameobject.iterate_find(
                        search_method="by_name", search_term=search_term, page_size=args.page_size or 50
                    ):
                        total_pages += 1
                        data = page.get("data", {})
                        items = data.get("items", [])
                        all_items.extend(items)
                        print(
                            f"Page {total_pages}: {len(items)} items (total so far: {len(all_items)})", file=sys.stderr
                        )

                    result = {
                        "success": True,
                        "message": f"Found {len(all_items)} GameObject(s) across {total_pages} pages",
                        "data": {"total": len(all_items), "pages": total_pages, "items": all_items},
                    }
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    result = client.gameobject.find(search_method="by_name", search_term=search_term)
                    print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "create":
                # gameobject create --name "..." [--primitive Cube] [--position x,y,z] [--rotation x,y,z] [--scale x,y,z] [--parent "..."]
                if not args.name:
                    print("Error: --name required for create")
                    sys.exit(1)

                kwargs = {}
                if args.primitive:
                    kwargs["primitive_type"] = args.primitive
                if args.position:
                    try:
                        kwargs["position"] = parse_vector3(args.position)
                    except ValueError as e:
                        print(f"Error: {e}")
                        sys.exit(1)
                if args.rotation:
                    try:
                        kwargs["rotation"] = parse_vector3(args.rotation)
                    except ValueError as e:
                        print(f"Error: {e}")
                        sys.exit(1)
                if args.scale:
                    try:
                        kwargs["scale"] = parse_vector3(args.scale)
                    except ValueError as e:
                        print(f"Error: {e}")
                        sys.exit(1)
                if args.parent:
                    kwargs["parent"] = args.parent

                result = client.gameobject.create(name=args.name, **kwargs)
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "delete":
                # gameobject delete --name "..."
                if not args.name:
                    print("Error: --name required for delete")
                    sys.exit(1)
                result = client.gameobject.delete(target=args.name, search_method="by_name")
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "modify":
                # gameobject modify --name "..." [--position x,y,z] [--rotation x,y,z] [--scale x,y,z]
                if not args.name:
                    print("Error: --name required for modify")
                    sys.exit(1)

                kwargs = {}
                if args.position:
                    try:
                        kwargs["position"] = parse_vector3(args.position)
                    except ValueError as e:
                        print(f"Error: {e}")
                        sys.exit(1)
                if args.rotation:
                    try:
                        kwargs["rotation"] = parse_vector3(args.rotation)
                    except ValueError as e:
                        print(f"Error: {e}")
                        sys.exit(1)
                if args.scale:
                    try:
                        kwargs["scale"] = parse_vector3(args.scale)
                    except ValueError as e:
                        print(f"Error: {e}")
                        sys.exit(1)

                if not kwargs:
                    print("Error: At least one of --position, --rotation, or --scale required for modify")
                    sys.exit(1)

                result = client.gameobject.modify(target=args.name, search_method="by_name", **kwargs)
                print(json.dumps(result, indent=2, ensure_ascii=False))

            else:
                print(f"Unknown gameobject action: {action}")
                print("Actions: find, create, delete, modify")
                sys.exit(1)

        else:
            print(f"Unknown command: {args.command}")
            print(
                "Available: config, console, clear, play, stop, state, refresh, tests, verify, scene, material, gameobject"
            )
            sys.exit(1)

    except UnityMCPError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# CLI Interface
if __name__ == "__main__":
    main()
