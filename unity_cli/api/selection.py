"""Selection API for Unity CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unity_cli.client import RelayConnection


class SelectionAPI:
    """Editor selection operations."""

    def __init__(self, conn: RelayConnection) -> None:
        self._conn = conn

    def get(self) -> dict[str, Any]:
        """Get current editor selection.

        Returns:
            Dictionary with selection information including:
            - count: Number of selected objects
            - activeObject: Currently active object (name, type, instanceID)
            - activeGameObject: Active GameObject details (name, tag, layer, etc.)
            - activeTransform: Transform of active object (position, rotation, scale)
            - objects: List of all selected objects
            - gameObjects: List of all selected GameObjects
            - assetGUIDs: List of selected asset GUIDs
        """
        return self._conn.send_request("selection", {"action": "get"})
