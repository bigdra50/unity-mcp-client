"""Unity Hub CLI wrapper."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from unity_cli.exceptions import HubInstallError, HubNotFoundError
from unity_cli.hub.paths import locate_hub_cli


@dataclass(frozen=True)
class HubEditorInfo:
    """Editor info from Hub CLI."""

    version: str
    path: str
    modules: list[str]


class HubCLI:
    """Unity Hub CLI wrapper."""

    def __init__(self, hub_path: Path | None = None) -> None:
        """Initialize with optional custom Hub path.

        Args:
            hub_path: Custom path to Hub CLI. If None, auto-detect.

        Raises:
            HubNotFoundError: If Hub CLI cannot be found.
        """
        self._hub_path = hub_path or locate_hub_cli()
        if self._hub_path is None:
            raise HubNotFoundError(
                "Unity Hub CLI not found. Install Unity Hub or set UNITY_HUB_PATH.",
                code="HUB_NOT_FOUND",
            )

    def _run_command(
        self,
        args: list[str],
        timeout: float = 300.0,
    ) -> subprocess.CompletedProcess[str]:
        """Execute Hub CLI command.

        Args:
            args: Command arguments (without hub path).
            timeout: Command timeout in seconds.

        Returns:
            CompletedProcess with stdout/stderr.

        Raises:
            HubInstallError: If command fails.
        """
        cmd = [str(self._hub_path), "--", "--headless", *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result
        except subprocess.TimeoutExpired as e:
            raise HubInstallError(
                f"Hub CLI command timed out after {timeout}s",
                code="HUB_TIMEOUT",
            ) from e
        except FileNotFoundError as e:
            raise HubNotFoundError(
                f"Hub CLI not found at {self._hub_path}",
                code="HUB_NOT_FOUND",
            ) from e

    def list_editors(self) -> list[HubEditorInfo]:
        """List installed editors via Hub CLI.

        Returns:
            List of installed editor info.
        """
        result = self._run_command(["editors", "-i"])

        # Parse Hub CLI output
        # Format: version, installed at path
        # Example: "2022.3.10f1 , installed at /Applications/Unity/Hub/Editor/2022.3.10f1"
        editors: list[HubEditorInfo] = []

        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Parse "version , installed at path"
            if ", installed at " in line:
                parts = line.split(", installed at ")
                if len(parts) == 2:
                    version = parts[0].strip()
                    path = parts[1].strip()
                    editors.append(
                        HubEditorInfo(
                            version=version,
                            path=path,
                            modules=[],  # Hub CLI doesn't list modules in this command
                        )
                    )

        return editors

    def install_editor(
        self,
        version: str,
        modules: list[str] | None = None,
        changeset: str | None = None,
    ) -> bool:
        """Install editor version.

        Args:
            version: Unity version to install (e.g., "2022.3.10f1").
            modules: Optional modules to install (e.g., ["ios", "android"]).
            changeset: Optional changeset for non-release versions.

        Returns:
            True if installation succeeded.

        Raises:
            HubInstallError: If installation fails.
        """
        args = ["install", "-v", version]

        if changeset:
            args.extend(["-c", changeset])

        if modules:
            for module in modules:
                args.extend(["-m", module])

        result = self._run_command(args, timeout=3600.0)  # 1 hour for install

        if result.returncode != 0:
            raise HubInstallError(
                f"Failed to install Unity {version}: {result.stderr}",
                code="HUB_INSTALL_FAILED",
            )

        return True

    def install_modules(
        self,
        version: str,
        modules: list[str],
    ) -> bool:
        """Install modules for existing editor.

        Args:
            version: Unity version to add modules to.
            modules: Modules to install.

        Returns:
            True if installation succeeded.

        Raises:
            HubInstallError: If installation fails.
        """
        args = ["install-modules", "-v", version]

        for module in modules:
            args.extend(["-m", module])

        result = self._run_command(args, timeout=3600.0)

        if result.returncode != 0:
            raise HubInstallError(
                f"Failed to install modules for Unity {version}: {result.stderr}",
                code="HUB_MODULE_INSTALL_FAILED",
            )

        return True

    def get_available_releases(self) -> list[str]:
        """Get list of available Unity releases.

        Returns:
            List of available version strings.
        """
        result = self._run_command(["editors", "-r"])

        versions: list[str] = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("("):
                # Extract version from line
                version = line.split()[0] if line.split() else ""
                if version:
                    versions.append(version)

        return versions
