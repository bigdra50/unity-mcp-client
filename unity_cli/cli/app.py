"""
Unity CLI - Typer Application
==============================

Main Typer application definition with basic commands
and sub-command groups for scene, tests, gameobject, component, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@console_app.command("get")
def console_get(
    ctx: typer.Context,
    types: Annotated[
        list[str] | None,
        typer.Option(
            "--types",
            "-t",
            help="Log types to filter (log, warning, error, assert, exception)",
        ),
    ] = None,
    count: Annotated[
        int,
        typer.Option("--count", "-c", help="Number of logs to retrieve"),
    ] = 20,
    filter_text: Annotated[
        str | None,
        typer.Option("--filter", "-f", help="Text to filter logs"),
    ] = None,
) -> None:
    """Get console logs."""
    context: CLIContext = ctx.obj
    try:
        log_types = types if types else context.config.log_types
        result = context.client.console.get(
            types=log_types,
            count=count,
            filter_text=filter_text,
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


@tests_app.command("run")
def tests_run(
    ctx: typer.Context,
    mode: Annotated[str, typer.Argument(help="Test mode (edit or play)")] = "edit",
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
    mode: Annotated[str, typer.Argument(help="Test mode (edit or play)")] = "edit",
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
# Entry Point
# =============================================================================


def cli_main() -> None:
    """CLI entry point."""
    app()


if __name__ == "__main__":
    cli_main()
