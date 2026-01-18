"""Orchestration layer for Unity Hub operations."""

from __future__ import annotations

from pathlib import Path

from unity_cli.exceptions import EditorNotFoundError, ProjectError
from unity_cli.hub.editor import launch_editor
from unity_cli.hub.interactive import is_tty, prompt_editor_selection
from unity_cli.hub.paths import (
    InstalledEditor,
    find_editor_by_version,
    get_installed_editors,
)
from unity_cli.hub.project import ProjectVersion, is_unity_project


class HubService:
    """High-level service for Unity Hub operations."""

    def open_project(
        self,
        project_path: Path,
        editor_override: str | None = None,
        non_interactive: bool = False,
        wait: bool = False,
    ) -> bool:
        """Open a Unity project with the appropriate editor.

        Flow:
        1. Validate project path
        2. Read ProjectVersion.txt to get required version
        3. Find matching installed editor
        4. If not found, prompt user (or fail in non-interactive mode)
        5. Launch editor

        Args:
            project_path: Path to Unity project.
            editor_override: Override editor version (skip version detection).
            non_interactive: If True, fail instead of prompting.
            wait: If True, wait for editor to close.

        Returns:
            True if editor was launched successfully.

        Raises:
            ProjectError: If project path is invalid.
            EditorNotFoundError: If required editor not installed and can't resolve.
        """
        project_path = project_path.resolve()

        if not is_unity_project(project_path):
            raise ProjectError(
                f"Not a valid Unity project: {project_path}",
                code="INVALID_PROJECT",
            )

        # Determine required version
        if editor_override:
            required_version = editor_override
        else:
            project_version = ProjectVersion.from_file(project_path)
            required_version = project_version.version

        # Resolve editor
        editor = self.resolve_editor(
            required_version=required_version,
            non_interactive=non_interactive,
        )

        if editor is None:
            raise EditorNotFoundError(
                f"Unity {required_version} is not installed and no alternative selected",
                code="EDITOR_NOT_RESOLVED",
            )

        # Launch
        launch_editor(editor.path, project_path, wait=wait)
        return True

    def resolve_editor(
        self,
        required_version: str,
        non_interactive: bool = False,
    ) -> InstalledEditor | None:
        """Resolve an editor for the required version.

        If exact version is installed, return it.
        Otherwise, prompt user to select (or return None in non-interactive mode).

        Args:
            required_version: The required Unity version.
            non_interactive: If True, don't prompt user.

        Returns:
            InstalledEditor if resolved, None otherwise.
        """
        # Check for exact match
        exact_match = find_editor_by_version(required_version)
        if exact_match is not None:
            return exact_match

        # Get all installed editors
        installed = get_installed_editors()

        if not installed:
            return None

        # Non-interactive mode: can't prompt
        if non_interactive or not is_tty():
            return None

        # Interactive mode: prompt user
        return prompt_editor_selection(required_version, installed)

    def list_installed_editors(self) -> list[InstalledEditor]:
        """List all installed Unity editors."""
        return get_installed_editors()
