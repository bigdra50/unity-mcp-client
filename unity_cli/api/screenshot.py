"""Screenshot API for Unity CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from unity_cli.client import RelayConnection


class ScreenshotAPI:
    """Screenshot capture operations."""

    def __init__(self, conn: RelayConnection) -> None:
        self._conn = conn

    def capture(
        self,
        source: Literal["game", "scene", "camera"] = "game",
        path: str | None = None,
        super_size: int = 1,
        width: int | None = None,
        height: int | None = None,
        camera: str | None = None,
    ) -> dict[str, Any]:
        """Capture a screenshot from GameView, SceneView, or Camera.

        Args:
            source: "game" for GameView (async, requires editor focus),
                    "scene" for SceneView,
                    "camera" for Camera.Render (sync, focus-independent)
            path: Output file path. If not specified, saves to Screenshots/ with timestamp
            super_size: Resolution multiplier for GameView (1-4). Ignored for scene/camera.
            width: Image width for camera source (default: 1920)
            height: Image height for camera source (default: 1080)
            camera: Camera GameObject name for camera source. Uses Main Camera if not specified.

        Returns:
            Dictionary with capture result including:
            - message: Status message
            - path: Output file path
            - source: Capture source ("game", "scene", or "camera")
            - width/height: Image dimensions (for scene/camera captures)
            - camera: Camera name (for camera captures)
        """
        params: dict[str, Any] = {
            "action": "capture",
            "source": source,
            "superSize": super_size,
        }
        if path is not None:
            params["path"] = path
        if width is not None:
            params["width"] = width
        if height is not None:
            params["height"] = height
        if camera is not None:
            params["camera"] = camera
        return self._conn.send_request("screenshot", params)
