"""Asset API for Unity CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unity_cli.client import RelayConnection


class AssetAPI:
    """Asset operations for creating Prefabs and ScriptableObjects."""

    def __init__(self, conn: RelayConnection) -> None:
        self._conn = conn

    def create_prefab(
        self,
        path: str,
        source: str | None = None,
        source_id: int | None = None,
    ) -> dict[str, Any]:
        """Create a Prefab from a GameObject.

        Args:
            path: Asset path (e.g., 'Assets/Prefabs/MyPrefab.prefab')
            source: Source GameObject name
            source_id: Source GameObject instance ID

        Returns:
            Dictionary with created prefab info
        """
        params: dict[str, Any] = {"action": "create_prefab", "path": path}
        if source:
            params["source"] = source
        if source_id is not None:
            params["sourceId"] = source_id
        return self._conn.send_request("asset", params)

    def create_scriptable_object(
        self,
        type_name: str,
        path: str,
    ) -> dict[str, Any]:
        """Create a ScriptableObject asset.

        Args:
            type_name: ScriptableObject type name
            path: Asset path (e.g., 'Assets/Data/MyData.asset')

        Returns:
            Dictionary with created asset info
        """
        return self._conn.send_request("asset", {
            "action": "create_scriptable_object",
            "type": type_name,
            "path": path,
        })

    def info(self, path: str) -> dict[str, Any]:
        """Get asset information.

        Args:
            path: Asset path

        Returns:
            Dictionary with asset info (name, type, guid, etc.)
        """
        return self._conn.send_request("asset", {
            "action": "info",
            "path": path,
        })
