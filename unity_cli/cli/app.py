"""
Unity CLI - Typer Application
==============================

Main Typer application definition with basic commands
and sub-command groups for scene, tests, gameobject, component, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Annotated

import typer

from unity_cli.cli.output import (
    console,
    err_console,
    print_error,
    print_instances_table,
    print_json,
    print_success,
)
from unity_cli.client import UnityClient
from unity_cli.config import CONFIG_FILE_NAME, UnityCLIConfig
from unity_cli.exceptions import UnityCLIError

# =============================================================================
# Retry Callback
# =============================================================================


def _on_retry_callback(code: str, message: str, attempt: int, backoff_ms: int) -> None:
    """Callback for retry events - outputs to stderr via Rich."""
    err_console.print(
        f"[dim][Retry][/dim] {code}: {message} (attempt {attempt}, waiting {backoff_ms}ms)",
        style="yellow",
    )


# =============================================================================
# Context Object
# =============================================================================


@dataclass
class CLIContext:
    """Context object shared across commands via ctx.obj."""

    config: UnityCLIConfig
    client: UnityClient
    json_mode: bool = False


# =============================================================================
# Main Application
# =============================================================================

app = typer.Typer(
    name="unity-cli",
    help="Unity CLI - Control Unity Editor via Relay Server",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


# =============================================================================
# Global Options Callback
# =============================================================================


@app.callback()
def main(
    ctx: typer.Context,
    relay_host: Annotated[
        str | None,
        typer.Option(
            "--relay-host",
            help="Relay server host",
            envvar="UNITY_RELAY_HOST",
        ),
    ] = None,
    relay_port: Annotated[
        int | None,
        typer.Option(
            "--relay-port",
            help="Relay server port",
            envvar="UNITY_RELAY_PORT",
        ),
    ] = None,
    instance: Annotated[
        str | None,
        typer.Option(
            "--instance",
            "-i",
            help="Target Unity instance (project path)",
            envvar="UNITY_INSTANCE",
        ),
    ] = None,
    timeout: Annotated[
        float | None,
        typer.Option(
            "--timeout",
            "-t",
            help="Timeout in seconds",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            "-j",
            help="Output JSON format",
        ),
    ] = False,
) -> None:
    """Unity CLI - Control Unity Editor via Relay Server."""
    # Load config from file
    config = UnityCLIConfig.load()

    # Override with CLI options
    if relay_host is not None:
        config.relay_host = relay_host
    if relay_port is not None:
        config.relay_port = relay_port
    if timeout is not None:
        config.timeout = timeout
    if instance is not None:
        config.instance = instance

    # Create client with retry callback for CLI feedback
    client = UnityClient(
        relay_host=config.relay_host,
        relay_port=config.relay_port,
        timeout=config.timeout,
        instance=config.instance,
        timeout_ms=config.timeout_ms,
        retry_initial_ms=config.retry_initial_ms,
        retry_max_ms=config.retry_max_ms,
        retry_max_time_ms=config.retry_max_time_ms,
        on_retry=_on_retry_callback,
    )

    # Store in context for sub-commands
    ctx.obj = CLIContext(
        config=config,
        client=client,
        json_mode=json_output,
    )


# =============================================================================
# Basic Commands
# =============================================================================


@app.command()
def version() -> None:
    """Show CLI version."""
    try:
        ver = pkg_version("unity-cli")
    except Exception:
        ver = "unknown"
    console.print(f"unity-cli {ver}")


@app.command()
def instances(ctx: typer.Context) -> None:
    """List connected Unity instances."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.list_instances()

        if context.json_mode:
            # JSON mode (--json with or without fields)
            print_json(result, None)
        else:
            print_instances_table(result)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@app.command()
def state(ctx: typer.Context) -> None:
    """Get editor state."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.editor.get_state()
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@app.command()
def play(ctx: typer.Context) -> None:
    """Enter play mode."""
    context: CLIContext = ctx.obj
    try:
        context.client.editor.play()
        if context.json_mode:
            print_json({"success": True, "action": "play"})
        else:
            print_success("Entered play mode")
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@app.command()
def stop(ctx: typer.Context) -> None:
    """Exit play mode."""
    context: CLIContext = ctx.obj
    try:
        context.client.editor.stop()
        if context.json_mode:
            print_json({"success": True, "action": "stop"})
        else:
            print_success("Exited play mode")
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@app.command()
def pause(ctx: typer.Context) -> None:
    """Toggle pause."""
    context: CLIContext = ctx.obj
    try:
        context.client.editor.pause()
        if context.json_mode:
            print_json({"success": True, "action": "pause"})
        else:
            print_success("Toggled pause")
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@app.command()
def refresh(ctx: typer.Context) -> None:
    """Refresh asset database (trigger recompilation)."""
    context: CLIContext = ctx.obj
    try:
        context.client.editor.refresh()
        if context.json_mode:
            print_json({"success": True, "action": "refresh"})
        else:
            print_success("Asset database refreshed")
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Console Commands
# =============================================================================

console_app = typer.Typer(help="Console log commands")
app.add_typer(console_app, name="console")


def _parse_level(level: str) -> list[str]:
    """Parse level option like adb logcat style.

    Levels (ascending severity): L (log) < W (warning) < E (error) < X (exception)
    Assert (A) is treated as same level as error.

    Examples:
        "E"   -> ["error", "exception"] (error and above)
        "W"   -> ["warning", "error", "assert", "exception"] (warning and above)
        "+W"  -> ["warning"] (warning only)
        "+E+X" -> ["error", "exception"] (specific types only)
    """
    level = level.upper().strip()

    # Hierarchy mapping (level -> types at that level and above)
    hierarchy = {
        "L": ["log", "warning", "error", "assert", "exception"],
        "W": ["warning", "error", "assert", "exception"],
        "E": ["error", "assert", "exception"],
        "A": ["error", "assert", "exception"],  # Assert same as Error level
        "X": ["exception"],
    }

    # Type mapping for specific selection
    type_map = {
        "L": "log",
        "W": "warning",
        "E": "error",
        "A": "assert",
        "X": "exception",
    }

    # Specific types mode: +E+W or +E
    if level.startswith("+"):
        types = []
        for char in level.replace("+", " ").split():
            if char in type_map:
                types.append(type_map[char])
        return types if types else ["log", "warning", "error", "assert", "exception"]

    # Hierarchy mode: E -> error and above
    if level in hierarchy:
        return hierarchy[level]

    # Invalid level, return all
    return ["log", "warning", "error", "assert", "exception"]


@console_app.command("get")
def console_get(
    ctx: typer.Context,
    level: Annotated[
        str | None,
        typer.Option(
            "--level",
            "-l",
            help="Log level filter: L(log), W(warning), E(error), X(exception). "
            "E.g., '-l W' for warning+, '-l +E' for error only",
        ),
    ] = None,
    count: Annotated[
        int | None,
        typer.Option("--count", "-c", help="Number of logs to retrieve (default: all)"),
    ] = None,
    filter_text: Annotated[
        str | None,
        typer.Option("--filter", "-f", help="Text to filter logs"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Include stack traces in output"),
    ] = False,
) -> None:
    """Get console logs.

    Level hierarchy: L (log) < W (warning) < E (error) < X (exception)

    Examples:
        u console get              # All logs (no stack traces)
        u console get -v           # All logs with stack traces
        u console get -l E         # Error and above (error + exception)
        u console get -l W         # Warning and above
        u console get -l +W        # Warning only
        u console get -l +E+X      # Error and exception only
    """
    context: CLIContext = ctx.obj
    try:
        # Parse level option to types list
        types = _parse_level(level) if level else None
        result = context.client.console.get(
            types=types,
            count=count,
            filter_text=filter_text,
            include_stacktrace=verbose,
        )
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@console_app.command("clear")
def console_clear(ctx: typer.Context) -> None:
    """Clear console logs."""
    context: CLIContext = ctx.obj
    try:
        context.client.console.clear()
        if context.json_mode:
            print_json({"success": True, "action": "clear"})
        else:
            print_success("Console cleared")
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Scene Commands
# =============================================================================

scene_app = typer.Typer(help="Scene management commands")
app.add_typer(scene_app, name="scene")


@scene_app.command("active")
def scene_active(ctx: typer.Context) -> None:
    """Get active scene info."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.scene.get_active()
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@scene_app.command("hierarchy")
def scene_hierarchy(
    ctx: typer.Context,
    depth: Annotated[int, typer.Option("--depth", "-d", help="Hierarchy depth")] = 1,
    page_size: Annotated[int, typer.Option("--page-size", help="Page size")] = 50,
    cursor: Annotated[int, typer.Option("--cursor", help="Pagination cursor")] = 0,
) -> None:
    """Get scene hierarchy."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.scene.get_hierarchy(
            depth=depth,
            page_size=page_size,
            cursor=cursor,
        )
        # For --json mode, output items array directly
        if context.json_mode:
            items = result.get("items", [])
            print_json(items)
        else:
            print_json(result)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@scene_app.command("load")
def scene_load(
    ctx: typer.Context,
    path: Annotated[str | None, typer.Option("--path", "-p", help="Scene path")] = None,
    name: Annotated[str | None, typer.Option("--name", "-n", help="Scene name")] = None,
    additive: Annotated[bool, typer.Option("--additive", "-a", help="Load additively")] = False,
) -> None:
    """Load a scene."""
    context: CLIContext = ctx.obj

    if not path and not name:
        print_error("--path or --name required")
        raise typer.Exit(1) from None

    try:
        result = context.client.scene.load(path=path, name=name, additive=additive)
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@scene_app.command("save")
def scene_save(
    ctx: typer.Context,
    path: Annotated[str | None, typer.Option("--path", "-p", help="Save path")] = None,
) -> None:
    """Save current scene."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.scene.save(path=path)
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Tests Commands
# =============================================================================

tests_app = typer.Typer(help="Test execution commands")
app.add_typer(tests_app, name="tests")


def _complete_test_mode(incomplete: str) -> list[tuple[str, str]]:
    """Autocompletion for test mode argument."""
    modes = [
        ("edit", "Run EditMode tests"),
        ("play", "Run PlayMode tests"),
    ]
    return [(m, h) for m, h in modes if m.startswith(incomplete)]


@tests_app.command("run")
def tests_run(
    ctx: typer.Context,
    mode: Annotated[str, typer.Argument(help="Test mode (edit or play)", autocompletion=_complete_test_mode)] = "edit",
    test_names: Annotated[
        list[str] | None,
        typer.Option("--test-names", "-n", help="Specific test names"),
    ] = None,
    categories: Annotated[
        list[str] | None,
        typer.Option("--categories", "-c", help="Test categories"),
    ] = None,
    assemblies: Annotated[
        list[str] | None,
        typer.Option("--assemblies", "-a", help="Assembly names"),
    ] = None,
    group_pattern: Annotated[
        str | None,
        typer.Option("--group-pattern", "-g", help="Regex pattern for test names"),
    ] = None,
    sync: Annotated[
        bool,
        typer.Option("--sync", "-s", help="Run synchronously (EditMode only)"),
    ] = False,
) -> None:
    """Run Unity tests."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.tests.run(
            mode=mode,
            test_names=test_names,
            categories=categories,
            assemblies=assemblies,
            group_pattern=group_pattern,
            synchronous=sync,
        )
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@tests_app.command("list")
def tests_list(
    ctx: typer.Context,
    mode: Annotated[str, typer.Argument(help="Test mode (edit or play)", autocompletion=_complete_test_mode)] = "edit",
) -> None:
    """List available tests."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.tests.list(mode=mode)
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@tests_app.command("status")
def tests_status(ctx: typer.Context) -> None:
    """Check running test status."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.tests.status()
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# GameObject Commands
# =============================================================================

gameobject_app = typer.Typer(help="GameObject commands")
app.add_typer(gameobject_app, name="gameobject")


@gameobject_app.command("find")
def gameobject_find(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Option("--name", "-n", help="GameObject name")] = None,
    id: Annotated[int | None, typer.Option("--id", help="Instance ID")] = None,
) -> None:
    """Find GameObjects by name or ID."""
    context: CLIContext = ctx.obj

    if not name and id is None:
        print_error("--name or --id required")
        raise typer.Exit(1) from None

    try:
        result = context.client.gameobject.find(name=name, instance_id=id)
        # For --json mode, output objects array directly
        if context.json_mode:
            objects = result.get("objects", [])
            print_json(objects)
        else:
            print_json(result)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@gameobject_app.command("create")
def gameobject_create(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", "-n", help="GameObject name")],
    primitive: Annotated[
        str | None,
        typer.Option("--primitive", "-p", help="Primitive type (Cube, Sphere, etc.)"),
    ] = None,
    position: Annotated[
        tuple[float, float, float] | None,
        typer.Option("--position", help="Position (X Y Z)"),
    ] = None,
    rotation: Annotated[
        tuple[float, float, float] | None,
        typer.Option("--rotation", help="Rotation (X Y Z)"),
    ] = None,
    scale: Annotated[
        tuple[float, float, float] | None,
        typer.Option("--scale", help="Scale (X Y Z)"),
    ] = None,
) -> None:
    """Create a new GameObject."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.gameobject.create(
            name=name,
            primitive_type=primitive,
            position=list(position) if position else None,
            rotation=list(rotation) if rotation else None,
            scale=list(scale) if scale else None,
        )
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@gameobject_app.command("modify")
def gameobject_modify(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Option("--name", "-n", help="GameObject name")] = None,
    id: Annotated[int | None, typer.Option("--id", help="Instance ID")] = None,
    position: Annotated[
        tuple[float, float, float] | None,
        typer.Option("--position", help="Position (X Y Z)"),
    ] = None,
    rotation: Annotated[
        tuple[float, float, float] | None,
        typer.Option("--rotation", help="Rotation (X Y Z)"),
    ] = None,
    scale: Annotated[
        tuple[float, float, float] | None,
        typer.Option("--scale", help="Scale (X Y Z)"),
    ] = None,
) -> None:
    """Modify GameObject transform."""
    context: CLIContext = ctx.obj

    if not name and id is None:
        print_error("--name or --id required")
        raise typer.Exit(1) from None

    try:
        result = context.client.gameobject.modify(
            name=name,
            instance_id=id,
            position=list(position) if position else None,
            rotation=list(rotation) if rotation else None,
            scale=list(scale) if scale else None,
        )
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@gameobject_app.command("delete")
def gameobject_delete(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Option("--name", "-n", help="GameObject name")] = None,
    id: Annotated[int | None, typer.Option("--id", help="Instance ID")] = None,
) -> None:
    """Delete a GameObject."""
    context: CLIContext = ctx.obj

    if not name and id is None:
        print_error("--name or --id required")
        raise typer.Exit(1) from None

    try:
        result = context.client.gameobject.delete(name=name, instance_id=id)
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Component Commands
# =============================================================================

component_app = typer.Typer(help="Component commands")
app.add_typer(component_app, name="component")


@component_app.command("list")
def component_list(
    ctx: typer.Context,
    target: Annotated[str | None, typer.Option("--target", "-t", help="Target GameObject name")] = None,
    target_id: Annotated[int | None, typer.Option("--target-id", help="Target GameObject ID")] = None,
) -> None:
    """List components on a GameObject."""
    context: CLIContext = ctx.obj

    if not target and target_id is None:
        print_error("--target or --target-id required")
        raise typer.Exit(1) from None

    try:
        result = context.client.component.list(target=target, target_id=target_id)
        # For --json mode, output components array directly
        if context.json_mode:
            components = result.get("components", [])
            print_json(components)
        else:
            print_json(result)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@component_app.command("inspect")
def component_inspect(
    ctx: typer.Context,
    component_type: Annotated[str, typer.Option("--type", "-T", help="Component type name")],
    target: Annotated[str | None, typer.Option("--target", "-t", help="Target GameObject name")] = None,
    target_id: Annotated[int | None, typer.Option("--target-id", help="Target GameObject ID")] = None,
) -> None:
    """Inspect component properties."""
    context: CLIContext = ctx.obj

    if not target and target_id is None:
        print_error("--target or --target-id required")
        raise typer.Exit(1) from None

    try:
        result = context.client.component.inspect(
            target=target,
            target_id=target_id,
            component_type=component_type,
        )
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@component_app.command("add")
def component_add(
    ctx: typer.Context,
    component_type: Annotated[str, typer.Option("--type", "-T", help="Component type name to add")],
    target: Annotated[str | None, typer.Option("--target", "-t", help="Target GameObject name")] = None,
    target_id: Annotated[int | None, typer.Option("--target-id", help="Target GameObject ID")] = None,
) -> None:
    """Add a component to a GameObject."""
    context: CLIContext = ctx.obj

    if not target and target_id is None:
        print_error("--target or --target-id required")
        raise typer.Exit(1) from None

    try:
        result = context.client.component.add(
            target=target,
            target_id=target_id,
            component_type=component_type,
        )
        if context.json_mode:
            print_json(result)
        else:
            print_success(result.get("message", "Component added"))
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@component_app.command("remove")
def component_remove(
    ctx: typer.Context,
    component_type: Annotated[str, typer.Option("--type", "-T", help="Component type name to remove")],
    target: Annotated[str | None, typer.Option("--target", "-t", help="Target GameObject name")] = None,
    target_id: Annotated[int | None, typer.Option("--target-id", help="Target GameObject ID")] = None,
) -> None:
    """Remove a component from a GameObject."""
    context: CLIContext = ctx.obj

    if not target and target_id is None:
        print_error("--target or --target-id required")
        raise typer.Exit(1) from None

    try:
        result = context.client.component.remove(
            target=target,
            target_id=target_id,
            component_type=component_type,
        )
        if context.json_mode:
            print_json(result)
        else:
            print_success(result.get("message", "Component removed"))
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Menu Commands
# =============================================================================

menu_app = typer.Typer(help="Menu item commands")
app.add_typer(menu_app, name="menu")


@menu_app.command("exec")
def menu_exec(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Menu item path (e.g., 'Edit/Play')")],
) -> None:
    """Execute a Unity menu item."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.menu.execute(path)
        if context.json_mode:
            print_json(result)
        else:
            if result.get("success"):
                print_success(result.get("message", f"Executed: {path}"))
            else:
                print_error(result.get("message", f"Failed: {path}"))
                raise typer.Exit(1) from None
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@menu_app.command("list")
def menu_list(
    ctx: typer.Context,
    filter_text: Annotated[
        str | None,
        typer.Option("--filter", "-f", help="Filter menu items (case-insensitive)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum items to return"),
    ] = 100,
) -> None:
    """List available menu items."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.menu.list(filter_text=filter_text, limit=limit)
        if context.json_mode:
            items = result.get("items", [])
            print_json(items)
        else:
            print_json(result)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@menu_app.command("context")
def menu_context(
    ctx: typer.Context,
    method: Annotated[str, typer.Argument(help="ContextMenu method name")],
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Target object path (hierarchy or asset)"),
    ] = None,
) -> None:
    """Execute a ContextMenu method on target object."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.menu.context(method=method, target=target)
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Asset Commands
# =============================================================================

asset_app = typer.Typer(help="Asset commands (Prefab, ScriptableObject)")
app.add_typer(asset_app, name="asset")


@asset_app.command("prefab")
def asset_prefab(
    ctx: typer.Context,
    path: Annotated[str, typer.Option("--path", "-p", help="Output path (e.g., Assets/Prefabs/My.prefab)")],
    source: Annotated[str | None, typer.Option("--source", "-s", help="Source GameObject name")] = None,
    source_id: Annotated[int | None, typer.Option("--source-id", help="Source GameObject instance ID")] = None,
) -> None:
    """Create a Prefab from a GameObject."""
    context: CLIContext = ctx.obj

    if not source and source_id is None:
        print_error("--source or --source-id required")
        raise typer.Exit(1) from None

    try:
        result = context.client.asset.create_prefab(
            path=path,
            source=source,
            source_id=source_id,
        )
        if context.json_mode:
            print_json(result)
        else:
            print_success(result.get("message", f"Prefab created: {path}"))
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@asset_app.command("scriptable-object")
def asset_scriptable_object(
    ctx: typer.Context,
    type_name: Annotated[str, typer.Option("--type", "-T", help="ScriptableObject type name")],
    path: Annotated[str, typer.Option("--path", "-p", help="Output path (e.g., Assets/Data/My.asset)")],
) -> None:
    """Create a ScriptableObject asset."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.asset.create_scriptable_object(
            type_name=type_name,
            path=path,
        )
        if context.json_mode:
            print_json(result)
        else:
            print_success(result.get("message", f"ScriptableObject created: {path}"))
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@asset_app.command("info")
def asset_info(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Asset path")],
) -> None:
    """Get asset information."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.asset.info(path=path)
        print_json(result, None)
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@asset_app.command("deps")
def asset_deps(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Asset path")],
    recursive: Annotated[
        bool,
        typer.Option("--recursive/--no-recursive", "-r/-R", help="Include indirect dependencies"),
    ] = True,
) -> None:
    """Get asset dependencies (what this asset depends on)."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.asset.deps(path=path, recursive=recursive)
        if context.json_mode:
            print_json(result)
        else:
            deps = result.get("dependencies", [])
            count = result.get("count", len(deps))
            console.print(f"[bold]Dependencies for {path}[/bold] ({count})")
            if result.get("recursive"):
                console.print("[dim](recursive)[/dim]")
            console.print()
            for dep in deps:
                console.print(f"  {dep.get('path')}")
                console.print(f"    [dim]type: {dep.get('type')}[/dim]")
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@asset_app.command("refs")
def asset_refs(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Asset path")],
) -> None:
    """Get asset referencers (what depends on this asset)."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.asset.refs(path=path)
        if context.json_mode:
            print_json(result)
        else:
            refs = result.get("referencers", [])
            count = result.get("count", len(refs))
            console.print(f"[bold]Referencers of {path}[/bold] ({count})")
            console.print()
            if count == 0:
                console.print("[dim]No references found[/dim]")
            else:
                for ref in refs:
                    console.print(f"  {ref.get('path')}")
                    console.print(f"    [dim]type: {ref.get('type')}[/dim]")
    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Config Commands
# =============================================================================

config_app = typer.Typer(help="Configuration commands")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Show current configuration."""
    context: CLIContext = ctx.obj
    config_file = UnityCLIConfig._find_config_file()

    if context.json_mode:
        # JSON mode
        data = {
            "config_file": str(config_file) if config_file else None,
            "relay_host": context.config.relay_host,
            "relay_port": context.config.relay_port,
            "timeout": context.config.timeout,
            "instance": context.config.instance,
            "log_types": context.config.log_types,
            "log_count": context.config.log_count,
        }
        print_json(data, None)
    else:
        console.print("[bold]=== Unity CLI Configuration ===[/bold]")
        console.print(f"Config file: {config_file or '[dim]Not found (using defaults)[/dim]'}")
        console.print(f"Relay host: {context.config.relay_host}")
        console.print(f"Relay port: {context.config.relay_port}")
        console.print(f"Timeout: {context.config.timeout}s")
        console.print(f"Instance: {context.config.instance or '[dim](default)[/dim]'}")
        console.print(f"Log types: {', '.join(context.config.log_types)}")
        console.print(f"Log count: {context.config.log_count}")


@config_app.command("init")
def config_init(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output path"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing config"),
    ] = False,
) -> None:
    """Generate default .unity-cli.toml configuration file."""
    output_path = output or Path(CONFIG_FILE_NAME)

    if output_path.exists() and not force:
        print_error(f"{output_path} already exists. Use --force to overwrite.")
        raise typer.Exit(1) from None

    default_config = UnityCLIConfig()
    output_path.write_text(default_config.to_toml())
    print_success(f"Created {output_path}")


# =============================================================================
# Project Commands (file-based, no Relay required)
# =============================================================================

project_app = typer.Typer(help="Project information (file-based, no Relay required)")
app.add_typer(project_app, name="project")


@project_app.command("info")
def project_info(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Unity project path"),
    ] = Path("."),
) -> None:
    """Show project information parsed from files.

    Displays: Unity version, product name, company, build scenes, packages.
    No Relay Server connection required.
    """
    from unity_cli.exceptions import ProjectError
    from unity_cli.hub.project import ProjectInfo

    context: CLIContext = ctx.obj

    try:
        info = ProjectInfo.from_path(path)

        if context.json_mode:
            print_json(info.to_dict())
        else:
            from rich.panel import Panel
            from rich.table import Table

            # Basic info
            console.print(Panel(f"[bold]{info.settings.product_name}[/bold]", subtitle=str(info.path)))
            console.print(f"Company: {info.settings.company_name}")
            console.print(f"Version: {info.settings.version}")
            console.print(f"Unity: {info.unity_version.version}")
            if info.unity_version.revision:
                console.print(f"Revision: [dim]{info.unity_version.revision}[/dim]")
            console.print(f"Screen: {info.settings.default_screen_width}x{info.settings.default_screen_height}")
            console.print()

            # Build scenes
            if info.build_settings.scenes:
                scene_table = Table(title="Build Scenes")
                scene_table.add_column("#", style="dim")
                scene_table.add_column("Path")
                scene_table.add_column("Enabled")

                for i, scene in enumerate(info.build_settings.scenes):
                    enabled = "[green]✓[/green]" if scene.enabled else "[red]✗[/red]"
                    scene_table.add_row(str(i), scene.path, enabled)
                console.print(scene_table)
                console.print()

            # Packages
            if info.packages.dependencies:
                pkg_table = Table(title=f"Packages ({len(info.packages.dependencies)})")
                pkg_table.add_column("Name", style="cyan")
                pkg_table.add_column("Version")
                pkg_table.add_column("Local")

                for pkg in info.packages.dependencies:
                    local = "[yellow]local[/yellow]" if pkg.is_local else ""
                    pkg_table.add_row(pkg.name, pkg.version, local)
                console.print(pkg_table)

    except ProjectError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@project_app.command("version")
def project_version(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Unity project path"),
    ] = Path("."),
) -> None:
    """Show Unity version for project."""
    from unity_cli.exceptions import ProjectVersionError
    from unity_cli.hub.project import ProjectVersion

    context: CLIContext = ctx.obj

    try:
        version = ProjectVersion.from_file(path)

        if context.json_mode:
            print_json({"version": version.version, "revision": version.revision})
        else:
            console.print(f"Unity: [cyan]{version.version}[/cyan]")
            if version.revision:
                console.print(f"Revision: [dim]{version.revision}[/dim]")

    except ProjectVersionError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


@project_app.command("packages")
def project_packages(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Unity project path"),
    ] = Path("."),
    include_modules: Annotated[
        bool,
        typer.Option("--include-modules", help="Include Unity built-in modules"),
    ] = False,
) -> None:
    """List installed packages from manifest.json."""
    from unity_cli.hub.project import is_unity_project

    context: CLIContext = ctx.obj
    path = path.resolve()

    if not is_unity_project(path):
        print_error(f"Not a valid Unity project: {path}", "INVALID_PROJECT")
        raise typer.Exit(1) from None

    manifest_file = path / "Packages/manifest.json"
    if not manifest_file.exists():
        print_error("manifest.json not found", "MANIFEST_NOT_FOUND")
        raise typer.Exit(1) from None

    import json

    data = json.loads(manifest_file.read_text())
    deps = data.get("dependencies", {})

    packages = []
    for name, version in sorted(deps.items()):
        if not include_modules and name.startswith("com.unity.modules."):
            continue
        is_local = version.startswith("file:")
        packages.append({"name": name, "version": version, "local": is_local})

    if context.json_mode:
        print_json(packages)
    else:
        from rich.table import Table

        table = Table(title=f"Packages ({len(packages)})")
        table.add_column("Name", style="cyan")
        table.add_column("Version")

        for pkg in packages:
            version_str = f"[yellow]{pkg['version']}[/yellow]" if pkg["local"] else pkg["version"]
            table.add_row(pkg["name"], version_str)
        console.print(table)


@project_app.command("tags")
def project_tags(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Unity project path"),
    ] = Path("."),
) -> None:
    """Show tags, layers, and sorting layers."""
    from unity_cli.hub.project import TagLayerSettings, is_unity_project

    context: CLIContext = ctx.obj
    path = path.resolve()

    if not is_unity_project(path):
        print_error(f"Not a valid Unity project: {path}", "INVALID_PROJECT")
        raise typer.Exit(1) from None

    settings = TagLayerSettings.from_file(path)

    if context.json_mode:
        print_json(
            {
                "tags": settings.tags,
                "layers": [{"index": i, "name": n} for i, n in settings.layers],
                "sorting_layers": settings.sorting_layers,
            }
        )
    else:
        from rich.table import Table

        # Tags
        if settings.tags:
            console.print("[bold]Tags:[/bold]")
            for tag in settings.tags:
                console.print(f"  - {tag}")
            console.print()
        else:
            console.print("[dim]No custom tags[/dim]")
            console.print()

        # Layers
        layer_table = Table(title="Layers")
        layer_table.add_column("#", style="dim", width=3)
        layer_table.add_column("Name", style="cyan")

        for idx, name in settings.layers:
            layer_table.add_row(str(idx), name)
        console.print(layer_table)
        console.print()

        # Sorting Layers
        if settings.sorting_layers:
            console.print("[bold]Sorting Layers:[/bold]")
            for i, layer in enumerate(settings.sorting_layers):
                console.print(f"  {i}: {layer}")


@project_app.command("quality")
def project_quality(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Unity project path"),
    ] = Path("."),
) -> None:
    """Show quality settings."""
    from unity_cli.hub.project import QualitySettings, is_unity_project

    context: CLIContext = ctx.obj
    path = path.resolve()

    if not is_unity_project(path):
        print_error(f"Not a valid Unity project: {path}", "INVALID_PROJECT")
        raise typer.Exit(1) from None

    settings = QualitySettings.from_file(path)

    if context.json_mode:
        print_json(
            {
                "current_quality": settings.current_quality,
                "levels": [
                    {
                        "name": lvl.name,
                        "shadow_resolution": lvl.shadow_resolution,
                        "shadow_distance": lvl.shadow_distance,
                        "vsync_count": lvl.vsync_count,
                        "lod_bias": lvl.lod_bias,
                        "anti_aliasing": lvl.anti_aliasing,
                    }
                    for lvl in settings.levels
                ],
            }
        )
    else:
        from rich.table import Table

        table = Table(title=f"Quality Levels (current: {settings.current_quality})")
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="cyan")
        table.add_column("Shadow Res")
        table.add_column("Shadow Dist")
        table.add_column("VSync")
        table.add_column("LOD Bias")
        table.add_column("AA")

        for i, lvl in enumerate(settings.levels):
            marker = "[green]►[/green]" if i == settings.current_quality else " "
            table.add_row(
                f"{marker}{i}",
                lvl.name,
                str(lvl.shadow_resolution),
                str(lvl.shadow_distance),
                str(lvl.vsync_count),
                str(lvl.lod_bias),
                str(lvl.anti_aliasing),
            )
        console.print(table)


@project_app.command("assemblies")
def project_assemblies(
    ctx: typer.Context,
    path: Annotated[
        Path,
        typer.Argument(help="Unity project path"),
    ] = Path("."),
) -> None:
    """List Assembly Definitions (.asmdef) in Assets/."""
    from unity_cli.hub.project import find_assembly_definitions, is_unity_project

    context: CLIContext = ctx.obj
    path = path.resolve()

    if not is_unity_project(path):
        print_error(f"Not a valid Unity project: {path}", "INVALID_PROJECT")
        raise typer.Exit(1) from None

    assemblies = find_assembly_definitions(path)

    if context.json_mode:
        print_json(
            [
                {
                    "name": asm.name,
                    "path": str(asm.path.relative_to(path)),
                    "references": asm.references,
                    "include_platforms": asm.include_platforms,
                    "exclude_platforms": asm.exclude_platforms,
                    "allow_unsafe": asm.allow_unsafe,
                    "auto_referenced": asm.auto_referenced,
                }
                for asm in assemblies
            ]
        )
    else:
        if not assemblies:
            console.print("[dim]No Assembly Definitions found in Assets/[/dim]")
            return

        from rich.table import Table

        table = Table(title=f"Assembly Definitions ({len(assemblies)})")
        table.add_column("Name", style="cyan")
        table.add_column("Path", style="dim")
        table.add_column("Refs", justify="right")
        table.add_column("Unsafe")

        for asm in assemblies:
            rel_path = asm.path.relative_to(path)
            unsafe = "[yellow]✓[/yellow]" if asm.allow_unsafe else ""
            table.add_row(asm.name, str(rel_path), str(len(asm.references)), unsafe)
        console.print(table)


# =============================================================================
# Open Command
# =============================================================================


@app.command("open")
def open_project(
    path: Annotated[Path, typer.Argument(help="Unity project path")],
    editor_version: Annotated[
        str | None,
        typer.Option("--editor", "-e", help="Override editor version"),
    ] = None,
    non_interactive: Annotated[
        bool,
        typer.Option("--non-interactive", "-y", help="Fail instead of prompting"),
    ] = False,
    wait: Annotated[
        bool,
        typer.Option("--wait", "-w", help="Wait for editor to close"),
    ] = False,
) -> None:
    """Open Unity project with appropriate editor version.

    Reads ProjectSettings/ProjectVersion.txt to detect required version.
    If version not installed, prompts for action.
    """
    from unity_cli.exceptions import EditorNotFoundError, ProjectError
    from unity_cli.hub.service import HubService

    try:
        service = HubService()
        service.open_project(
            project_path=path,
            editor_override=editor_version,
            non_interactive=non_interactive,
            wait=wait,
        )
        print_success(f"Opened project: {path}")
    except (ProjectError, EditorNotFoundError) as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Editor Commands (Unity Hub integration)
# =============================================================================

editor_app = typer.Typer(help="Unity Editor management (via Hub)")
app.add_typer(editor_app, name="editor")


@editor_app.command("list")
def editor_list(ctx: typer.Context) -> None:
    """List installed Unity editors."""
    from unity_cli.hub.paths import get_installed_editors

    context: CLIContext = ctx.obj
    editors = get_installed_editors()

    if context.json_mode:
        data = [{"version": e.version, "path": str(e.path)} for e in editors]
        print_json(data)
    else:
        if not editors:
            console.print("[dim]No Unity editors found[/dim]")
            return

        from rich.table import Table

        table = Table(title=f"Installed Editors ({len(editors)})")
        table.add_column("Version", style="cyan")
        table.add_column("Path", style="dim")

        for editor in editors:
            table.add_row(editor.version, str(editor.path))

        console.print(table)


@editor_app.command("install")
def editor_install(
    version: Annotated[str, typer.Argument(help="Unity version to install")],
    modules: Annotated[
        list[str] | None,
        typer.Option("--modules", "-m", help="Modules to install"),
    ] = None,
    changeset: Annotated[
        str | None,
        typer.Option("--changeset", "-c", help="Changeset for non-release versions"),
    ] = None,
) -> None:
    """Install Unity Editor via Hub CLI.

    Example: unity-cli editor install 2022.3.10f1 --modules android ios
    """
    from unity_cli.exceptions import HubError
    from unity_cli.hub.hub_cli import HubCLI

    try:
        hub = HubCLI()
        hub.install_editor(version=version, modules=modules, changeset=changeset)
        print_success(f"Installing Unity {version}")
        if modules:
            print_success(f"With modules: {', '.join(modules)}")
    except HubError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Selection Command
# =============================================================================


@app.command()
def selection(ctx: typer.Context) -> None:
    """Get current editor selection."""
    context: CLIContext = ctx.obj
    try:
        result = context.client.selection.get()

        if context.json_mode:
            print_json(result)
        else:
            count = result.get("count", 0)
            if count == 0:
                console.print("[dim]No objects selected[/dim]")
                return

            console.print(f"[bold]Selected: {count} object(s)[/bold]\n")

            active_go = result.get("activeGameObject")
            if active_go:
                console.print("[cyan]Active GameObject:[/cyan]")
                console.print(f"  Name: {active_go.get('name')}")
                console.print(f"  Instance ID: {active_go.get('instanceID')}")
                console.print(f"  Tag: {active_go.get('tag')}")
                console.print(f"  Layer: {active_go.get('layerName')} ({active_go.get('layer')})")
                console.print(f"  Path: {active_go.get('scenePath')}")

            active_transform = result.get("activeTransform")
            if active_transform:
                pos = active_transform.get("position", [])
                rot = active_transform.get("rotation", [])
                scale = active_transform.get("scale", [])
                console.print("\n[cyan]Transform:[/cyan]")
                if pos:
                    console.print(f"  Position: ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
                if rot:
                    console.print(f"  Rotation: ({rot[0]:.2f}, {rot[1]:.2f}, {rot[2]:.2f})")
                if scale:
                    console.print(f"  Scale: ({scale[0]:.2f}, {scale[1]:.2f}, {scale[2]:.2f})")

            game_objects = result.get("gameObjects", [])
            if len(game_objects) > 1:
                console.print(f"\n[cyan]All Selected GameObjects ({len(game_objects)}):[/cyan]")
                for go in game_objects:
                    console.print(f"  - {go.get('name')} (ID: {go.get('instanceID')})")

    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Screenshot Command
# =============================================================================


@app.command()
def screenshot(
    ctx: typer.Context,
    source: Annotated[
        str,
        typer.Option("--source", "-s", help="Capture source: game, scene, or camera"),
    ] = "game",
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Output file path"),
    ] = None,
    super_size: Annotated[
        int,
        typer.Option("--super-size", help="Resolution multiplier (1-4, game only)"),
    ] = 1,
    width: Annotated[
        int | None,
        typer.Option("--width", "-W", help="Image width (camera only, default: 1920)"),
    ] = None,
    height: Annotated[
        int | None,
        typer.Option("--height", "-H", help="Image height (camera only, default: 1080)"),
    ] = None,
    camera_name: Annotated[
        str | None,
        typer.Option("--camera", "-c", help="Camera name (camera only, default: Main Camera)"),
    ] = None,
) -> None:
    """Capture screenshot from GameView, SceneView, or Camera.

    Sources:
      game   - GameView (async, requires editor focus)
      scene  - SceneView
      camera - Camera.Render (sync, focus-independent)
    """
    context: CLIContext = ctx.obj

    if source not in ("game", "scene", "camera"):
        print_error(f"Invalid source: {source}. Use 'game', 'scene', or 'camera'", "INVALID_SOURCE")
        raise typer.Exit(1) from None

    try:
        result = context.client.screenshot.capture(
            source=source,  # type: ignore[arg-type]
            path=path,
            super_size=super_size,
            width=width,
            height=height,
            camera=camera_name,
        )

        if context.json_mode:
            print_json(result)
        else:
            print_success(f"Screenshot captured: {result.get('path')}")
            if result.get("note"):
                console.print(f"[dim]{result.get('note')}[/dim]")
            if result.get("camera"):
                console.print(f"[dim]Camera: {result.get('camera')}[/dim]")

    except UnityCLIError as e:
        print_error(e.message, e.code)
        raise typer.Exit(1) from None


# =============================================================================
# Completion Commands
# =============================================================================

_COMPLETION_SCRIPTS = {
    "zsh": """#compdef u unity unity-cli

_unity_cli() {
  eval $(env _TYPER_COMPLETE_ARGS="${words[1,$CURRENT]}" _U_COMPLETE=complete_zsh u)
}

_unity_cli "$@"
""",
    "bash": """_unity_cli() {
  local IFS=$'\\n'
  COMPREPLY=($(env _TYPER_COMPLETE_ARGS="${COMP_WORDS[*]}" _U_COMPLETE=complete_bash u))
  return 0
}

complete -o default -F _unity_cli u unity unity-cli
""",
    "fish": """complete -c u -f -a "(env _TYPER_COMPLETE_ARGS=(commandline -cp) _U_COMPLETE=complete_fish u)"
complete -c unity -f -a "(env _TYPER_COMPLETE_ARGS=(commandline -cp) _U_COMPLETE=complete_fish unity)"
complete -c unity-cli -f -a "(env _TYPER_COMPLETE_ARGS=(commandline -cp) _U_COMPLETE=complete_fish unity-cli)"
""",
}


@app.command("completion")
def completion(
    shell: Annotated[
        str | None,
        typer.Option("--shell", "-s", help="Shell type: zsh, bash, fish"),
    ] = None,
) -> None:
    """Generate shell completion script.

    Examples:
        u completion -s zsh > ~/.zsh/completions/_unity-cli
        u completion -s bash >> ~/.bashrc
        u completion -s fish > ~/.config/fish/completions/unity-cli.fish
    """
    import os

    # Auto-detect shell if not specified
    if shell is None:
        shell_env = os.environ.get("SHELL", "")
        if "zsh" in shell_env:
            shell = "zsh"
        elif "bash" in shell_env:
            shell = "bash"
        elif "fish" in shell_env:
            shell = "fish"
        else:
            shell = "zsh"  # Default to zsh

    shell = shell.lower()
    if shell not in _COMPLETION_SCRIPTS:
        err_console.print(f"[red]Unsupported shell: {shell}[/red]")
        err_console.print(f"Supported shells: {', '.join(_COMPLETION_SCRIPTS.keys())}")
        raise typer.Exit(1)

    # Output script to stdout (no Rich formatting)
    print(_COMPLETION_SCRIPTS[shell], end="")


# =============================================================================
# Entry Point
# =============================================================================


def cli_main() -> None:
    """CLI entry point."""
    app()


if __name__ == "__main__":
    cli_main()
