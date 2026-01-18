"""Rich-based output formatting utilities for Unity CLI.

Provides consistent, readable output formatting using Rich library.
Supports JSON output mode with field filtering for scripting.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

console = Console()
err_console = Console(stderr=True)


def filter_fields(data: Any, fields: list[str] | None) -> Any:
    """Filter data to include only specified fields.

    Args:
        data: Dict, list of dicts, or other data
        fields: Field names to include. None or empty returns all.

    Returns:
        Filtered data with only specified fields.
    """
    if not fields:
        return data

    # Convert to set for O(1) lookup
    fields_set = set(fields)

    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in fields_set}
    if isinstance(data, list):
        # Reuse the same set for all items
        return [_filter_dict(item, fields_set) for item in data]
    return data


def _filter_dict(item: Any, fields_set: set[str]) -> Any:
    """Internal helper to filter a single item with pre-computed set."""
    if isinstance(item, dict):
        return {k: v for k, v in item.items() if k in fields_set}
    return item


def print_json(data: Any, fields: list[str] | None = None) -> None:
    """Print data as JSON with optional field filtering.

    Args:
        data: Data to output
        fields: Fields to include (None for all)
    """
    filtered = filter_fields(data, fields)
    console.print_json(json.dumps(filtered, ensure_ascii=False))


def print_error(message: str, code: str | None = None) -> None:
    """Print error message to stderr.

    Args:
        message: Error message (will be escaped to prevent markup injection)
        code: Optional error code
    """
    text = Text()
    text.append("Error: ", style="bold red")
    text.append(escape(message))  # Escape untrusted content
    err_console.print(text)

    if code:
        code_text = Text()
        code_text.append("Code: ", style="dim")
        code_text.append(escape(code), style="yellow")  # Escape untrusted content
        err_console.print(code_text)


def print_success(message: str) -> None:
    """Print success message.

    Args:
        message: Success message
    """
    text = Text()
    text.append("[OK] ", style="bold green")
    text.append(message)
    console.print(text)


def print_warning(message: str) -> None:
    """Print warning message.

    Args:
        message: Warning message
    """
    text = Text()
    text.append("[WARN] ", style="bold yellow")
    text.append(message)
    console.print(text)


def print_info(message: str) -> None:
    """Print info message.

    Args:
        message: Info message
    """
    text = Text()
    text.append("[INFO] ", style="bold blue")
    text.append(message)
    console.print(text)


def print_instances_table(instances: list[dict[str, Any]]) -> None:
    """Print Unity instances as a formatted table.

    Args:
        instances: List of instance dicts with keys:
            - instance_id: Project path
            - project_name: Project name
            - unity_version: Unity version
            - status: Connection status
            - is_default: Whether this is the default instance
    """
    if not instances:
        console.print("No Unity instances connected", style="dim")
        return

    table = Table(title=f"Connected Instances ({len(instances)})")
    table.add_column("Project", style="cyan", no_wrap=True)
    table.add_column("Unity Version", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Default", justify="center")

    for inst in instances:
        project = escape(inst.get("project_name", inst.get("instance_id", "Unknown")))
        version = escape(inst.get("unity_version", "Unknown"))
        status = inst.get("status", "unknown")
        is_default = "[green]*[/green]" if inst.get("is_default") else ""

        # Status styling (status is controlled, no need to escape)
        status_style = {
            "ready": "green",
            "busy": "yellow",
            "reloading": "magenta",
            "disconnected": "red",
        }.get(status.lower(), "dim")

        table.add_row(
            project,
            version,
            Text(escape(status), style=status_style),
            is_default,
        )

    console.print(table)


def print_logs_table(logs: list[dict[str, Any]]) -> None:
    """Print console logs as a formatted table.

    Args:
        logs: List of log dicts with keys:
            - type: Log type (error, warning, log, etc.)
            - message: Log message
            - stackTrace: Optional stack trace
            - timestamp: Optional timestamp
    """
    if not logs:
        console.print("No logs found", style="dim")
        return

    table = Table(title=f"Console Logs ({len(logs)})")
    table.add_column("Type", style="bold", width=8)
    table.add_column("Message", overflow="fold")

    type_styles = {
        "error": "red",
        "exception": "red bold",
        "warning": "yellow",
        "log": "white",
        "assert": "magenta",
    }

    for log in logs:
        log_type = log.get("type", "log").lower()
        message = log.get("message", "")

        # Truncate long messages
        if len(message) > 200:
            message = message[:197] + "..."

        style = type_styles.get(log_type, "dim")
        table.add_row(
            Text(log_type.upper(), style=style),
            escape(message),  # Escape Unity log content
        )

    console.print(table)


def print_hierarchy_table(items: list[dict[str, Any]], show_components: bool = False) -> None:
    """Print scene hierarchy as a formatted table.

    Args:
        items: List of hierarchy item dicts with keys:
            - name: GameObject name
            - instanceID: Instance ID
            - depth: Hierarchy depth
            - childCount: Number of children
            - components: Optional list of component names
        show_components: Whether to show component column
    """
    if not items:
        console.print("No GameObjects in hierarchy", style="dim")
        return

    table = Table(title=f"Scene Hierarchy ({len(items)} objects)")
    table.add_column("Name", style="cyan")
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Children", justify="center")
    if show_components:
        table.add_column("Components", style="green")

    for item in items:
        depth = item.get("depth", 0)
        indent = "  " * depth
        name = escape(f"{indent}{item.get('name', 'Unknown')}")
        instance_id = str(item.get("instanceID", ""))
        child_count = str(item.get("childCount", 0))

        row = [name, instance_id, child_count]
        if show_components:
            components = item.get("components", [])
            comp_str = ", ".join(escape(c) for c in components[:3])
            row.append(comp_str + ("..." if len(components) > 3 else ""))

        table.add_row(*row)

    console.print(table)


def print_components_table(components: list[dict[str, Any]]) -> None:
    """Print component list as a formatted table.

    Args:
        components: List of component dicts with keys:
            - type: Component type name
            - enabled: Whether component is enabled
            - instanceID: Instance ID
    """
    if not components:
        console.print("No components found", style="dim")
        return

    table = Table(title=f"Components ({len(components)})")
    table.add_column("Type", style="cyan")
    table.add_column("Enabled", justify="center")
    table.add_column("ID", style="dim", justify="right")

    for comp in components:
        comp_type = escape(comp.get("type", "Unknown"))
        enabled = comp.get("enabled", True)
        instance_id = str(comp.get("instanceID", ""))

        enabled_display = "[green]Yes[/green]" if enabled else "[red]No[/red]"

        table.add_row(comp_type, enabled_display, instance_id)

    console.print(table)


def print_test_results_table(results: list[dict[str, Any]]) -> None:
    """Print test results as a formatted table.

    Args:
        results: List of test result dicts with keys:
            - name: Test name
            - result: Test result (Passed, Failed, Skipped, etc.)
            - duration: Test duration in seconds
            - message: Optional failure message
    """
    if not results:
        console.print("No test results", style="dim")
        return

    passed = sum(1 for r in results if r.get("result") == "Passed")
    failed = sum(1 for r in results if r.get("result") == "Failed")
    skipped = sum(1 for r in results if r.get("result") == "Skipped")

    table = Table(title=f"Test Results (Passed: {passed}, Failed: {failed}, Skipped: {skipped})")
    table.add_column("Test", style="cyan", overflow="fold")
    table.add_column("Result", justify="center")
    table.add_column("Duration", justify="right")

    result_styles = {
        "Passed": "green",
        "Failed": "red",
        "Skipped": "yellow",
        "Inconclusive": "magenta",
    }

    for test in results:
        name = escape(test.get("name", "Unknown"))
        result = test.get("result", "Unknown")
        duration = test.get("duration", 0)

        style = result_styles.get(result, "dim")
        duration_str = f"{duration:.3f}s" if isinstance(duration, float) else str(duration)

        table.add_row(name, Text(escape(result), style=style), duration_str)

    console.print(table)


def print_key_value(data: dict[str, Any], title: str | None = None) -> None:
    """Print dict as key-value pairs.

    Args:
        data: Dict to display
        title: Optional title
    """
    if title:
        console.print(f"[bold]{escape(title)}[/bold]")

    for key, value in data.items():
        console.print(f"  [cyan]{escape(str(key))}:[/cyan] {escape(str(value))}")
