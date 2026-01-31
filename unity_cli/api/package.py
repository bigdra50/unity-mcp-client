"""Package API for Unity CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unity_cli.client import RelayConnection


class PackageAPI:
    """Package Manager operations via Relay Server."""

    def __init__(self, conn: RelayConnection) -> None:
        self._conn = conn

    def list(self) -> dict[str, Any]:
        """List installed packages."""
        return self._conn.send_request("package", {"action": "list"})

    def add(self, name: str) -> dict[str, Any]:
        """Add a package.

        Args:
            name: Package identifier (e.g., 'com.unity.textmeshpro@3.0.6')
        """
        return self._conn.send_request(
            "package",
            {"action": "add", "name": name},
        )

    def remove(self, name: str) -> dict[str, Any]:
        """Remove a package.

        Args:
            name: Package name (e.g., 'com.unity.textmeshpro')
        """
        return self._conn.send_request(
            "package",
            {"action": "remove", "name": name},
        )
