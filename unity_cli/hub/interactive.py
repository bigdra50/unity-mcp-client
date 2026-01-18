"""Interactive UI using InquirerPy."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from unity_cli.hub.paths import InstalledEditor


def is_tty() -> bool:
    """Check if running in an interactive TTY."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _has_inquirerpy() -> bool:
    """Check if InquirerPy is available."""
    try:
        import importlib.util

        return importlib.util.find_spec("InquirerPy") is not None
    except ImportError:
        return False


def prompt_editor_selection(
    required_version: str,
    editors: list[InstalledEditor],
) -> InstalledEditor | None:
    """Prompt user to select an editor when required version not installed.

    Args:
        required_version: The version required by the project.
        editors: List of installed editors to choose from.

    Returns:
        Selected InstalledEditor, or None if user chose to quit.
        Also returns None if not in TTY or InquirerPy not available.
    """
    if not is_tty():
        return None

    if not _has_inquirerpy():
        return None

    from InquirerPy import inquirer
    from InquirerPy.base.control import Choice

    choices: list[Choice] = [
        Choice(value=None, name="Quit"),
    ]

    for editor in editors:
        choices.append(Choice(value=editor, name=f"Use {editor.version}"))

    selected: InstalledEditor | None = inquirer.select(
        message=f"Unity {required_version} not installed. Choose an action:",
        choices=choices,
        default=None,
    ).execute()

    return selected


def prompt_confirm(message: str, default: bool = False) -> bool:
    """Prompt user for yes/no confirmation.

    Args:
        message: The confirmation message.
        default: Default value if user just presses Enter.

    Returns:
        True if confirmed, False otherwise.
        Returns default if not in TTY or InquirerPy not available.
    """
    if not is_tty():
        return default

    if not _has_inquirerpy():
        return default

    from InquirerPy import inquirer

    result: bool = inquirer.confirm(message=message, default=default).execute()
    return result
