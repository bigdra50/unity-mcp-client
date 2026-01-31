"""Build API for Unity CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unity_cli.client import RelayConnection


class BuildAPI:
    """Build pipeline operations via Relay Server."""

    def __init__(self, conn: RelayConnection) -> None:
        self._conn = conn

    def settings(self) -> dict[str, Any]:
        """Get current build settings."""
        return self._conn.send_request("build", {"action": "settings"})

    def build(
        self,
        target: str | None = None,
        output_path: str | None = None,
        scenes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a build.

        Args:
            target: BuildTarget name (e.g., 'StandaloneWindows64'). Uses active target if omitted.
            output_path: Output path. Uses 'Builds/<target>/<productName>' if omitted.
            scenes: Scene paths to include. Uses Build Settings scenes if omitted.
        """
        params: dict[str, Any] = {"action": "build"}
        if target is not None:
            params["target"] = target
        if output_path is not None:
            params["outputPath"] = output_path
        if scenes is not None:
            params["scenes"] = scenes
        return self._conn.send_request(
            "build",
            params,
            timeout_ms=600_000,
            retry_max_time_ms=600_000,
        )

    def scenes(self) -> dict[str, Any]:
        """Get build scenes list."""
        return self._conn.send_request("build", {"action": "scenes"})
