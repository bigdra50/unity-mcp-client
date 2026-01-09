#!/usr/bin/env python3
"""
Unity MCP Client Library
=========================

Complete Python client for Unity MCP TCP protocol.
Supports all 10 tools with 60+ actions.

Usage:
    from unity_mcp_client import UnityMCPClient

    client = UnityMCPClient()

    # Console operations
    logs = client.read_console(types=["error"], count=10)
    client.clear_console()

    # Editor control
    client.editor.play()
    state = client.editor.get_state()

    # GameObject operations
    obj = client.gameobject.create("Player", primitive_type="Cube")
    client.gameobject.modify("Player", position=[0, 5, 0])

    # Scene management
    client.scene.load(path="Assets/Scenes/MainScene.unity")

    # Asset operations
    client.asset.create("Assets/Materials/New.mat", "Material")

    # Run tests
    results = client.run_tests(mode="edit")

    # Batch execution
    result = client.batch.execute([
        {"tool": "read_console", "params": {"action": "clear"}},
        {"tool": "manage_editor", "params": {"action": "play"}},
        {"tool": "read_console", "params": {"action": "get", "types": ["error"]}}
    ], fail_fast=True)
"""

import socket
import json
import struct
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Union


CONFIG_FILE_NAME = ".unity-mcp.toml"


@dataclass
class UnityMCPConfig:
    """Configuration for Unity MCP Client"""
    port: int = 6400
    host: str = "localhost"
    timeout: float = 5.0
    connection_timeout: float = 30.0
    retry: int = 3
    log_types: List[str] = field(default_factory=lambda: ["error", "warning"])
    log_count: int = 20

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "UnityMCPConfig":
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
        if config_path and config_path.exists():
            toml_path = config_path
        else:
            toml_path = cls._find_config_file()

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
    def _find_config_file(cls) -> Optional[Path]:
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
    def _from_dict(cls, data: Dict[str, Any]) -> "UnityMCPConfig":
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


def _detect_port_from_editor_prefs() -> Optional[int]:
    """
    Detect Unity MCP port from EditorPrefs (macOS only).

    Returns the port from Unity EditorPrefs if available,
    otherwise returns None.
    """
    if sys.platform != 'darwin':
        return None

    try:
        result = subprocess.run(
            ["defaults", "read", "com.unity3d.UnityEditor5.x", "MCPForUnity.UnitySocketPort"],
            capture_output=True,
            text=True,
            timeout=5
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

    def __init__(self, host='localhost', port=6400, timeout=5.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _write_frame(self, sock, payload_bytes: bytes):
        """Write framed message: 8-byte big-endian length + payload"""
        length = len(payload_bytes)
        header = struct.pack('>Q', length)
        sock.sendall(header + payload_bytes)

    def _read_frame(self, sock) -> str:
        """Read framed message: 8-byte header + payload"""
        sock.settimeout(self.timeout)

        # Read 8-byte header
        header = sock.recv(8)
        if len(header) != 8:
            raise UnityMCPError(f"Expected 8-byte header, got {len(header)} bytes")

        # Parse length (big-endian)
        length = struct.unpack('>Q', header)[0]

        # Read payload
        payload = b""
        remaining = length
        while remaining > 0:
            chunk = sock.recv(min(remaining, 4096))
            if not chunk:
                raise UnityMCPError("Connection closed while reading payload")
            payload += chunk
            remaining -= len(chunk)

        return payload.decode('utf-8')

    def send_command(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send command and return response"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            try:
                sock.connect((self.host, self.port))
            except ConnectionRefusedError:
                raise UnityMCPError(
                    f"Cannot connect to Unity Editor at {self.host}:{self.port}.\n"
                    "Please ensure:\n"
                    "  1. Unity Editor is open\n"
                    "  2. MCP For Unity bridge is running (Window > MCP For Unity)"
                )
            except (socket.timeout, TimeoutError):
                raise UnityMCPError(
                    f"Connection timed out to {self.host}:{self.port} (timeout: {self.timeout}s).\n"
                    "Please ensure Unity Editor is responsive."
                )

            # Read WELCOME
            try:
                welcome = sock.recv(1024).decode('utf-8')
            except (socket.timeout, TimeoutError):
                raise UnityMCPError(
                    f"Handshake timed out (timeout: {self.timeout}s).\n"
                    "Unity Editor may be busy or unresponsive."
                )
            if 'WELCOME UNITY-MCP' not in welcome:
                raise UnityMCPError(f"Invalid handshake: {welcome}")

            # Build message
            message = {
                "type": tool_name,
                "params": params
            }

            # Send framed request
            payload = json.dumps(message).encode('utf-8')
            self._write_frame(sock, payload)

            # Read framed response
            try:
                response_text = self._read_frame(sock)
            except (socket.timeout, TimeoutError):
                raise UnityMCPError(
                    f"Response timed out for '{tool_name}' (timeout: {self.timeout}s).\n"
                    "The operation may still be running in Unity.\n"
                    "Try increasing --connection-timeout for long operations."
                )
            response = json.loads(response_text)

            # Check status (support both old 'status' and new 'success' fields)
            if response.get("status") == "error":
                raise UnityMCPError(f"{tool_name} failed: {response.get('error', 'Unknown error')}")

            if response.get("success") is False:
                raise UnityMCPError(f"{tool_name} failed: {response.get('message', 'Unknown error')}")

            return response.get("result", response)

        finally:
            sock.close()

    def read_resource(self, resource_name: str, params: Dict[str, Any] = {}) -> Dict[str, Any]:
        """Read resource and return response (uses same protocol as Tools)"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            try:
                sock.connect((self.host, self.port))
            except ConnectionRefusedError:
                raise UnityMCPError(
                    f"Cannot connect to Unity Editor at {self.host}:{self.port}.\n"
                    "Please ensure:\n"
                    "  1. Unity Editor is open\n"
                    "  2. MCP For Unity bridge is running (Window > MCP For Unity)"
                )
            except (socket.timeout, TimeoutError):
                raise UnityMCPError(
                    f"Connection timed out to {self.host}:{self.port} (timeout: {self.timeout}s).\n"
                    "Please ensure Unity Editor is responsive."
                )

            # Read WELCOME
            try:
                welcome = sock.recv(1024).decode('utf-8')
            except (socket.timeout, TimeoutError):
                raise UnityMCPError(
                    f"Handshake timed out (timeout: {self.timeout}s).\n"
                    "Unity Editor may be busy or unresponsive."
                )
            if 'WELCOME UNITY-MCP' not in welcome:
                raise UnityMCPError(f"Invalid handshake: {welcome}")

            # Build message - Resources use same format as Tools
            message = {
                "type": resource_name,
                "params": params
            }

            # Send framed request
            payload = json.dumps(message).encode('utf-8')
            self._write_frame(sock, payload)

            # Read framed response
            try:
                response_text = self._read_frame(sock)
            except (socket.timeout, TimeoutError):
                raise UnityMCPError(
                    f"Response timed out for resource '{resource_name}' (timeout: {self.timeout}s).\n"
                    "Unity Editor may be busy or unresponsive."
                )
            response = json.loads(response_text)

            # Check status (support both old 'status' and new 'success' fields)
            if response.get("status") == "error":
                raise UnityMCPError(f"Resource {resource_name} failed: {response.get('error', 'Unknown error')}")

            if response.get("success") is False:
                raise UnityMCPError(f"Resource {resource_name} failed: {response.get('message', 'Unknown error')}")

            return response.get("result", response)

        finally:
            sock.close()


class ConsoleAPI:
    """Console log operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def get(self, types: Optional[List[str]] = None, count: int = 100,
            format: str = "detailed", include_stacktrace: bool = True,
            filter_text: Optional[str] = None) -> Dict[str, Any]:
        """Get console logs"""
        params = {
            "action": "get",
            "format": format,
            "include_stacktrace": include_stacktrace
        }
        if types:
            params["types"] = types
        if count:
            params["count"] = count
        if filter_text:
            params["filter_text"] = filter_text

        return self._conn.send_command("read_console", params)

    def clear(self) -> Dict[str, Any]:
        """Clear console"""
        return self._conn.send_command("read_console", {"action": "clear"})


class EditorAPI:
    """Editor control operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def play(self) -> Dict[str, Any]:
        """Enter play mode"""
        return self._conn.send_command("manage_editor", {"action": "play"})

    def pause(self) -> Dict[str, Any]:
        """Pause/unpause game"""
        return self._conn.send_command("manage_editor", {"action": "pause"})

    def stop(self) -> Dict[str, Any]:
        """Exit play mode"""
        return self._conn.send_command("manage_editor", {"action": "stop"})

    def get_state(self) -> Dict[str, Any]:
        """Get editor state via Resource API"""
        return self._conn.read_resource("get_editor_state")

    def get_project_root(self) -> str:
        """Get project root path via Resource API"""
        result = self._conn.read_resource("get_project_info")
        data = result.get("data", {})
        return data.get("projectRoot", "")

    def add_tag(self, tag_name: str) -> Dict[str, Any]:
        """Add tag"""
        return self._conn.send_command("manage_editor", {"action": "add_tag", "tagName": tag_name})

    def remove_tag(self, tag_name: str) -> Dict[str, Any]:
        """Remove tag"""
        return self._conn.send_command("manage_editor", {"action": "remove_tag", "tagName": tag_name})

    def get_tags(self) -> Dict[str, Any]:
        """Get all tags via Resource API"""
        return self._conn.read_resource("get_tags")

    def get_layers(self) -> Dict[str, Any]:
        """Get all layers via Resource API"""
        return self._conn.read_resource("get_layers")


class GameObjectAPI:
    """GameObject operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(self, name: str, parent: Optional[str] = None,
               position: Optional[List[float]] = None,
               rotation: Optional[List[float]] = None,
               scale: Optional[List[float]] = None,
               primitive_type: Optional[str] = None,
               prefab_path: Optional[str] = None,
               **kwargs) -> Dict[str, Any]:
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

    def modify(self, target: str, search_method: str = "by_name",
               name: Optional[str] = None,
               position: Optional[List[float]] = None,
               rotation: Optional[List[float]] = None,
               scale: Optional[List[float]] = None,
               component_properties: Optional[Dict[str, Dict]] = None,
               **kwargs) -> Dict[str, Any]:
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

    def delete(self, target: str, search_method: str = "by_name") -> Dict[str, Any]:
        """Delete GameObject"""
        return self._conn.send_command("manage_gameobject", {
            "action": "delete",
            "target": target,
            "searchMethod": search_method
        })

    def find(self, search_method: str = "by_name", search_term: Optional[str] = None,
             target: Optional[str] = None, find_all: bool = False,
             search_inactive: bool = False,
             page_size: Optional[int] = None,
             page: Optional[int] = None,
             offset: Optional[int] = None,
             cursor: Optional[str] = None) -> Dict[str, Any]:
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
            cursor: Cursor value (for cursor-based pagination)

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

    def add_component(self, target: str, components: List[str],
                      search_method: str = "by_name",
                      component_properties: Optional[Dict[str, Dict]] = None) -> Dict[str, Any]:
        """Add component(s)"""
        params = {
            "action": "add_component",
            "target": target,
            "componentsToAdd": components,
            "searchMethod": search_method
        }
        if component_properties:
            params["componentProperties"] = component_properties

        return self._conn.send_command("manage_gameobject", params)

    def remove_component(self, target: str, components: List[str],
                         search_method: str = "by_name") -> Dict[str, Any]:
        """Remove component(s)"""
        return self._conn.send_command("manage_gameobject", {
            "action": "remove_component",
            "target": target,
            "componentsToRemove": components,
            "searchMethod": search_method
        })


class SceneAPI:
    """Scene management operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(self, name: str, path: str = "Scenes") -> Dict[str, Any]:
        """Create new scene"""
        return self._conn.send_command("manage_scene", {
            "action": "create",
            "name": name,
            "path": path
        })

    def load(self, name: Optional[str] = None, path: Optional[str] = None,
             build_index: Optional[int] = None) -> Dict[str, Any]:
        """Load scene"""
        params = {"action": "load"}
        if name:
            params["name"] = name
        if path:
            params["path"] = path
        if build_index is not None:
            params["buildIndex"] = build_index

        return self._conn.send_command("manage_scene", params)

    def save(self, name: Optional[str] = None, path: Optional[str] = None) -> Dict[str, Any]:
        """Save current scene"""
        params = {"action": "save"}
        if name:
            params["name"] = name
        if path:
            params["path"] = path

        return self._conn.send_command("manage_scene", params)

    def get_hierarchy(self,
                      page_size: Optional[int] = None,
                      cursor: Optional[int] = None,
                      max_nodes: Optional[int] = None,
                      max_depth: Optional[int] = None,
                      max_children_per_node: Optional[int] = None,
                      parent: Optional[Any] = None,
                      include_transform: Optional[bool] = None) -> Dict[str, Any]:
        """
        Get scene hierarchy with pagination support

        Args:
            page_size: Items per page (1-500, default: 50)
            cursor: Starting position (default: 0)
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

    def get_active(self) -> Dict[str, Any]:
        """Get active scene info"""
        return self._conn.send_command("manage_scene", {"action": "get_active"})

    def get_build_settings(self) -> Dict[str, Any]:
        """Get build settings (scenes in build)"""
        return self._conn.send_command("manage_scene", {"action": "get_build_settings"})

    def iterate_hierarchy(self,
                         page_size: int = 50,
                         max_nodes: Optional[int] = None,
                         max_children_per_node: Optional[int] = None,
                         parent: Optional[Any] = None,
                         include_transform: Optional[bool] = None):
        """
        Iterate through entire scene hierarchy using cursor-based pagination

        This is a generator that automatically fetches all pages until completion.

        Args:
            page_size: Items per page (1-500, default: 50)
            max_nodes: Total node limit per request (1-5000, default: 1000)
            max_children_per_node: Children per node limit (0-2000, default: 200)
            parent: Parent object to query from (null = roots)
            include_transform: Include transform information

        Yields:
            Dict for each page containing the response from get_hierarchy()

        Example:
            for page in client.scene.iterate_hierarchy(page_size=100):
                print(f"Page has {len(page['data']['items'])} items")
                print(f"Total: {page['data']['total']}")
                for item in page['data']['items']:
                    print(f"  - {item['name']}")
        """
        cursor = 0

        while True:
            result = self.get_hierarchy(
                page_size=page_size,
                cursor=cursor,
                max_nodes=max_nodes,
                max_children_per_node=max_children_per_node,
                parent=parent,
                include_transform=include_transform
            )

            yield result

            # Check if there's a next page
            data = result.get('data', {})
            next_cursor = data.get('next_cursor')

            if next_cursor is None:
                break

            cursor = int(next_cursor)


class AssetAPI:
    """Asset management operations"""

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def create(self, path: str, asset_type: str, properties: Optional[Dict] = None) -> Dict[str, Any]:
        """Create asset"""
        params = {"action": "create", "path": path, "assetType": asset_type}
        if properties:
            params["properties"] = properties

        return self._conn.send_command("manage_asset", params)

    def modify(self, path: str, properties: Dict) -> Dict[str, Any]:
        """Modify asset"""
        return self._conn.send_command("manage_asset", {
            "action": "modify",
            "path": path,
            "properties": properties
        })

    def delete(self, path: str) -> Dict[str, Any]:
        """Delete asset"""
        return self._conn.send_command("manage_asset", {"action": "delete", "path": path})

    def search(self, search_pattern: Optional[str] = None,
               filter_type: Optional[str] = None,
               path: Optional[str] = None,
               page_size: int = 50) -> Dict[str, Any]:
        """Search assets"""
        params = {"action": "search", "pageSize": page_size}
        if search_pattern:
            params["searchPattern"] = search_pattern
        if filter_type:
            params["filterType"] = filter_type
        if path:
            params["path"] = path

        return self._conn.send_command("manage_asset", params)


class BatchAPI:
    """Batch execution operations"""

    MAX_COMMANDS_PER_BATCH = 25

    def __init__(self, conn: UnityMCPConnection):
        self._conn = conn

    def execute(self, commands: List[Dict[str, Any]],
                parallel: Optional[bool] = None,
                fail_fast: Optional[bool] = None,
                max_parallelism: Optional[int] = None) -> Dict[str, Any]:
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

            normalized_commands.append({
                "tool": tool_name,
                "params": params,
            })

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

    def create(self, material_path: str, shader: str = "Standard",
               properties: Optional[Dict] = None) -> Dict[str, Any]:
        """Create material"""
        params = {
            "action": "create",
            "materialPath": material_path,
            "shader": shader
        }
        if properties:
            params["properties"] = properties

        return self._conn.send_command("manage_material", params)

    def set_shader_property(self, material_path: str, property: str,
                           value: Any) -> Dict[str, Any]:
        """Set shader property"""
        return self._conn.send_command("manage_material", {
            "action": "set_shader_property",
            "materialPath": material_path,
            "property": property,
            "value": value
        })

    def set_color(self, material_path: str, color: List[float],
                  property: str = "_BaseColor") -> Dict[str, Any]:
        """Set material color"""
        return self._conn.send_command("manage_material", {
            "action": "set_color",
            "materialPath": material_path,
            "color": color,
            "property": property
        })

    def assign_to_renderer(self, material_path: str, target: str,
                          search_method: str = "by_name",
                          slot: int = 0,
                          mode: str = "shared") -> Dict[str, Any]:
        """Assign material to renderer"""
        return self._conn.send_command("manage_material", {
            "action": "assign_to_renderer",
            "materialPath": material_path,
            "target": target,
            "searchMethod": search_method,
            "slot": slot,
            "mode": mode
        })

    def set_renderer_color(self, target: str, color: List[float],
                          search_method: str = "by_name",
                          slot: int = 0,
                          mode: str = "property_block") -> Dict[str, Any]:
        """Set renderer color"""
        return self._conn.send_command("manage_material", {
            "action": "set_renderer_color",
            "target": target,
            "color": color,
            "searchMethod": search_method,
            "slot": slot,
            "mode": mode
        })

    def get_info(self, material_path: str) -> Dict[str, Any]:
        """Get material info"""
        return self._conn.send_command("manage_material", {
            "action": "get_info",
            "materialPath": material_path
        })


class UnityMCPClient:
    """
    Complete Unity MCP client with all tools

    Usage:
        client = UnityMCPClient()

        # Direct console access
        logs = client.read_console(types=["error"])
        client.clear_console()

        # Via API objects
        client.editor.play()
        client.gameobject.create("Player", primitive_type="Cube")
        client.scene.load(path="Assets/Scenes/Main.unity")

        # Batch execution
        result = client.batch.execute([
            {"tool": "read_console", "params": {"action": "clear"}},
            {"tool": "manage_editor", "params": {"action": "play"}},
            {"tool": "read_console", "params": {"action": "get", "types": ["error"]}}
        ], fail_fast=True)
    """

    def __init__(self, host='localhost', port=6400, timeout=5.0):
        self._conn = UnityMCPConnection(host, port, timeout)

        # API objects
        self.console = ConsoleAPI(self._conn)
        self.editor = EditorAPI(self._conn)
        self.gameobject = GameObjectAPI(self._conn)
        self.scene = SceneAPI(self._conn)
        self.asset = AssetAPI(self._conn)
        self.batch = BatchAPI(self._conn)
        self.material = MaterialAPI(self._conn)

    # Convenience methods
    def read_console(self, **kwargs) -> Dict[str, Any]:
        """Get console logs (convenience method)"""
        return self.console.get(**kwargs)

    def clear_console(self) -> Dict[str, Any]:
        """Clear console (convenience method)"""
        return self.console.clear()

    def execute_menu_item(self, menu_path: str) -> Dict[str, Any]:
        """Execute Unity menu item"""
        return self._conn.send_command("execute_menu_item", {"menu_path": menu_path})

    def run_tests(self, mode: str = "edit", timeout_seconds: int = 600) -> Dict[str, Any]:
        """Run Unity tests"""
        return self._conn.send_command("run_tests", {
            "mode": mode,
            "timeoutSeconds": timeout_seconds
        })

    def manage_script(self, action: str, name: str, path: str = "Scripts", **kwargs) -> Dict[str, Any]:
        """Manage C# scripts"""
        params = {"action": action, "name": name, "path": path}
        params.update(kwargs)
        return self._conn.send_command("manage_script", params)

    def manage_shader(self, action: str, name: str, path: str = "Shaders", **kwargs) -> Dict[str, Any]:
        """Manage shaders"""
        params = {"action": action, "name": name, "path": path}
        params.update(kwargs)
        return self._conn.send_command("manage_shader", params)

    def manage_prefabs(self, action: str, **kwargs) -> Dict[str, Any]:
        """Manage prefabs"""
        params = {"action": action}
        params.update(kwargs)
        return self._conn.send_command("manage_prefabs", params)


def main():
    """CLI entry point for unity-mcp command"""
    import sys
    import argparse

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
  tests <mode>            Run tests (edit|play)
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
  %(prog)s config
  %(prog)s config init
  %(prog)s config init --output my-config.toml
  %(prog)s scene active
  %(prog)s scene hierarchy
  %(prog)s scene hierarchy --page-size 100 --cursor 0
  %(prog)s scene hierarchy --iterate-all --page-size 200
  %(prog)s scene hierarchy --max-nodes 500 --include-transform
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
        """
    )
    parser.add_argument("command", help="Command to execute (see available commands below)")
    parser.add_argument("args", nargs="*", help="Command arguments")
    parser.add_argument("--port", type=int, default=None,
                        help=f"Server port (default: {config.port}, from config/EditorPrefs)")
    parser.add_argument("--host", default=None,
                        help=f"Server host (default: {config.host})")
    parser.add_argument("--count", type=int, default=None,
                        help=f"Number of console logs to retrieve (default: {config.log_count})")
    parser.add_argument("--types", nargs="+", default=None,
                        help=f"Log types to retrieve (default: {' '.join(config.log_types)}). Options: error, warning, log")
    parser.add_argument("--timeout", type=int, default=None,
                        help=f"Maximum wait time for compilation in seconds (default: {int(config.timeout)}, verify only)")
    parser.add_argument("--connection-timeout", type=float, default=None,
                        help=f"TCP connection timeout in seconds (default: {config.connection_timeout}, verify only)")
    parser.add_argument("--retry", type=int, default=None,
                        help=f"Maximum connection retry attempts (default: {config.retry}, verify only)")
    # Scene command arguments
    parser.add_argument("--name", default=None,
                        help="Scene/GameObject name (for scene create/load, gameobject create/modify/delete)")
    parser.add_argument("--path", default=None,
                        help="Scene path (for scene create/load/save) or Material path (for material commands)")
    parser.add_argument("--build-index", type=int, default=None,
                        help="Build index (for scene load)")
    # Material command arguments
    parser.add_argument("--shader", default="Standard",
                        help="Shader name (for material create, default: Standard)")
    parser.add_argument("--color", default=None,
                        help="Color as comma-separated RGBA (e.g., 1,0,0,1 for red)")
    parser.add_argument("--property", default="_BaseColor",
                        help="Shader property name (default: _BaseColor)")
    parser.add_argument("--value", default=None,
                        help="Property value (for material set-property)")
    parser.add_argument("--target", default=None,
                        help="Target GameObject name (for material assign/set-renderer-color)")
    parser.add_argument("--search-method", default="by_name",
                        help="Search method (default: by_name)")
    parser.add_argument("--slot", type=int, default=0,
                        help="Material slot index (default: 0)")
    parser.add_argument("--mode", default=None,
                        help="Mode: 'shared' or 'instance' (for assign), 'property_block' or 'material' (for set-renderer-color)")
    # GameObject command arguments
    parser.add_argument("--primitive", default=None,
                        help="Primitive type (for gameobject create). Options: Cube, Sphere, Capsule, Cylinder, Plane, Quad")
    parser.add_argument("--position", default=None,
                        help="Position as x,y,z (for gameobject create/modify)")
    parser.add_argument("--rotation", default=None,
                        help="Rotation as x,y,z (for gameobject create/modify)")
    parser.add_argument("--scale", default=None,
                        help="Scale as x,y,z (for gameobject create/modify)")
    parser.add_argument("--parent", default=None,
                        help="Parent GameObject name (for gameobject create)")
    # Pagination arguments (for scene hierarchy and gameobject find)
    parser.add_argument("--page-size", type=int, default=None,
                        help="Items per page (1-500, default: 50)")
    parser.add_argument("--cursor", type=int, default=None,
                        help="Starting cursor position (default: 0)")
    parser.add_argument("--max-nodes", type=int, default=None,
                        help="Total node limit (1-5000, default: 1000)")
    parser.add_argument("--max-children-per-node", type=int, default=None,
                        help="Children per node limit (0-2000, default: 200)")
    parser.add_argument("--include-transform", action="store_true",
                        help="Include transform information (for scene hierarchy)")
    parser.add_argument("--iterate-all", action="store_true",
                        help="Iterate through all pages (for scene hierarchy)")
    # Config init arguments
    parser.add_argument("--output", "-o", default=None,
                        help="Output path for config init (default: ./.unity-mcp.toml)")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Overwrite existing config file without confirmation")

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
            result = client.read_console(types=log_types, count=log_count)
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "clear":
            result = client.clear_console()
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
            client.execute_menu_item("Assets/Refresh")
            print("✓ Asset refresh triggered")

        elif args.command == "find" and args.args:
            result = client.gameobject.find(search_method="by_name", search_term=args.args[0])
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "tests":
            mode = args.args[0] if args.args else "edit"
            result = client.run_tests(mode=mode)
            print(json.dumps(result, indent=2, ensure_ascii=False))

        elif args.command == "verify":
            import time

            # Create a separate client with longer timeout for verify operations
            verify_client = UnityMCPClient(
                host=host,
                port=port,
                timeout=connection_timeout
            )

            # Step 1: Refresh assets
            print("=== Refreshing Assets ===")
            verify_client.execute_menu_item("Assets/Refresh")
            print("✓ Asset refresh triggered")

            # Step 2: Clear console (to capture only new errors)
            print("\n=== Clearing Console ===")
            verify_client.clear_console()
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
                    is_compiling = state.get('data', {}).get('isCompiling', False)

                    if not is_compiling:
                        print(f"\n✓ Compilation complete ({elapsed:.1f}s)")
                        break

                    print(f"  Compiling... ({elapsed:.1f}s)", end='\r')
                    connection_failures = 0  # Reset on successful connection

                except UnityMCPError as e:
                    connection_failures += 1
                    if connection_failures <= retry:
                        print(f"  Connection lost, retrying ({connection_failures}/{retry})...", end='\r')
                        continue
                    print(f"\n⚠ Connection failed after {retry} retries")
                    sys.exit(1)
            else:
                print(f"\n⚠ Timeout after {timeout}s")
                sys.exit(1)

            # Step 4: Check console logs
            print("\n=== Console Logs ===")
            logs = verify_client.read_console(types=log_types, count=log_count)

            if logs['data']:
                print(f"Found {len(logs['data'])} log entries (types: {', '.join(log_types)}, max: {log_count}):\n")
                for log in logs['data']:
                    print(f"[{log['type']}] {log['message']}")
                    if log.get('file'):
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
                    # Iterate through all pages
                    all_items = []
                    total_pages = 0

                    for page in client.scene.iterate_hierarchy(
                        page_size=args.page_size or 50,
                        max_nodes=args.max_nodes,
                        max_children_per_node=args.max_children_per_node,
                        include_transform=args.include_transform or None
                    ):
                        total_pages += 1
                        data = page.get('data', {})
                        items = data.get('items', [])
                        all_items.extend(items)
                        print(f"Page {total_pages}: {len(items)} items (total so far: {len(all_items)})", file=sys.stderr)

                    # Print combined result
                    result = {
                        "success": True,
                        "message": f"Retrieved all {len(all_items)} items across {total_pages} pages",
                        "data": {
                            "total": len(all_items),
                            "pages": total_pages,
                            "items": all_items
                        }
                    }
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    # Single page request
                    result = client.scene.get_hierarchy(
                        page_size=args.page_size,
                        cursor=args.cursor,
                        max_nodes=args.max_nodes,
                        max_children_per_node=args.max_children_per_node,
                        include_transform=args.include_transform or None
                    )
                    print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "build-settings":
                result = client.scene.get_build_settings()
                print(json.dumps(result, indent=2, ensure_ascii=False))

            elif action == "load":
                if not args.name and not args.path and args.build_index is None:
                    print("Error: --name, --path, or --build-index required for load")
                    sys.exit(1)
                result = client.scene.load(
                    name=args.name,
                    path=args.path,
                    build_index=args.build_index
                )
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
            def parse_color(s: str) -> List[float]:
                parts = s.split(',')
                if len(parts) != 4:
                    raise ValueError(f"Invalid color format: {s} (expected r,g,b,a)")
                return [float(p.strip()) for p in parts]

            if action == "create":
                if not args.path:
                    print("Error: --path required for create")
                    sys.exit(1)
                result = client.material.create(
                    material_path=args.path,
                    shader=args.shader
                )
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
                result = client.material.set_color(
                    material_path=args.path,
                    color=color,
                    property=args.property
                )
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
                    material_path=args.path,
                    property=args.property,
                    value=args.value
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
                    mode=mode
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
                    target=args.target,
                    color=color,
                    search_method=args.search_method,
                    slot=args.slot,
                    mode=mode
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
            def parse_vector3(s: str) -> List[float]:
                parts = s.split(',')
                if len(parts) != 3:
                    raise ValueError(f"Invalid vector format: {s} (expected x,y,z)")
                return [float(p.strip()) for p in parts]

            if action == "find":
                # gameobject find <name>
                if len(args.args) < 2:
                    print("Error: GameObject name required for find")
                    sys.exit(1)
                search_term = args.args[1]
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
            print("Available: config, console, clear, play, stop, state, refresh, tests, verify, scene, material, gameobject")
            sys.exit(1)

    except UnityMCPError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# CLI Interface
if __name__ == "__main__":
    main()
